"""Phase 2 Steps 6-7: Model A (GPS-only step estimator). Random Forest + XGBoost + baselines.
Run: .venv/Scripts/python.exe ml/gps_step_estimator/train_eval.py
Inputs : datasets/dryad/processed/windows_5s.csv, results/metrics/phase2_splits.json (+ alignment / monotonicity JSONs for the config)
Outputs: ml/models/*, results/metrics/phase2_model_metrics.json, results/metrics/phase2_test_predictions.csv, results/plots/*.png
Protocol: hyper-parameters chosen on the VALIDATION subjects only (models fit on TRAIN subjects only). The test subjects are
scored once, after the selection is frozen. Supplementary analyses (sensitivity, leave-subject-out) are labelled as such.
Inputs are the GPS-derived window features only; no step / IMU data is an input.
"""
import itertools
import json
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parents[2]
MET, MODELS, PLOTS = ROOT / "results" / "metrics", ROOT / "ml" / "models", ROOT / "results" / "plots"
for p in (MODELS, PLOTS):
    p.mkdir(parents=True, exist_ok=True)
SEED = 42
WIN_S = 5.0
MIN_BIN_N = 30          # speed bins with fewer windows are flagged
MIN_DIST_M = 0.5        # linear baseline: windows with GPS-speed distance below this are not used to fit the ratio
LABELS = ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", ">2.0"]

df = pd.read_csv(ROOT / "datasets" / "dryad" / "processed" / "windows_5s.csv")
splits = json.loads((MET / "phase2_splits.json").read_text())
summ = json.loads((MET / "phase2_windows_summary.json").read_text())
align = json.loads((MET / "phase2_alignment_check.json").read_text())
mono = json.loads((MET / "phase2_step_monotonicity_analysis.json").read_text())
FEATURES = summ["model_input_features"]
assert not set(FEATURES) & set(summ["not_inputs"])
SUB = {k: set(v) for k, v in splits["subjects"].items()}
assert not (SUB["train"] & SUB["validation"] or SUB["train"] & SUB["test"] or SUB["validation"] & SUB["test"])
df["set"] = df.subject.map({s: k for k, v in SUB.items() for s in v})
assert df["set"].notna().all()
df["distance_gps_m"] = df.speed_mean * WIN_S      # GPS speed x window length (baseline input; GPS only)
tr, va, te = (df[df.set == s].reset_index(drop=True) for s in ("train", "validation", "test"))


# ---------------------------------------------------------------- helpers
def reg_metrics(y, p):
    return {"n": int(len(y)), "MAE": float(mean_absolute_error(y, p)),
            "RMSE": float(np.sqrt(mean_squared_error(y, p))), "R2": float(r2_score(y, p)) if len(y) > 1 else None}


def track_level(d, p):
    g = d.assign(pred=p).groupby(["track", "subject"]).agg(actual=("steps_target", "sum"), pred=("pred", "sum"),
                                                            n_windows=("pred", "size")).reset_index()
    g["err"] = g.pred - g.actual
    g["abs_err"] = g.err.abs()
    g["pct_err"] = 100 * g.err / g.actual.replace(0, np.nan)
    pooled = 100 * g.err.sum() / g.actual.sum()
    return g, {"n_tracks": int(len(g)), "mean_abs_err_steps": float(g.abs_err.mean()),
               "median_abs_err_steps": float(g.abs_err.median()),
               "mean_abs_pct_err": float(g.pct_err.abs().mean()), "median_abs_pct_err": float(g.pct_err.abs().median()),
               "bias_steps_mean_signed": float(g.err.mean()), "bias_pct_mean_signed": float(g.pct_err.mean()),
               "pooled_bias_pct": float(pooled), "total_actual": float(g.actual.sum()), "total_pred": float(g.pred.sum())}


def by_bin(d, p, col):
    out = {}
    for lab in LABELS:
        m = (d[col] == lab).values
        n = int(m.sum())
        if n == 0:
            out[lab] = {"n": 0, "flag_too_few": True}
            continue
        r = reg_metrics(d.steps_target.values[m], np.asarray(p)[m])
        r["flag_too_few"] = n < MIN_BIN_N
        if n < 2:
            r["R2"] = None
        out[lab] = r
    return out


def by_subject(d, p):
    out = {}
    for s, g in d.assign(pred=p).groupby("subject"):
        r = reg_metrics(g.steps_target.values, g.pred.values)
        r["mean_actual"], r["mean_pred"] = float(g.steps_target.mean()), float(g.pred.mean())
        out[str(int(s))] = r
    return out


def full_report(d, preds):
    rep = {}
    for name, p in preds.items():
        _, tl = track_level(d, p)
        rep[name] = {"window": reg_metrics(d.steps_target.values, p), "track_level": tl,
                     "by_speed_bin_gps": by_bin(d, p, "speed_bin_gps"), "by_speed_bin_ref": by_bin(d, p, "speed_bin_ref"),
                     "per_subject": by_subject(d, p)}
    return rep


# ---------------------------------------------------------------- models
class MeanBaseline:
    def fit(self, X, y):
        self.m = float(np.mean(y)); return self
    def predict(self, X):
        return np.full(len(X), self.m)


class LinearDistBaseline:
    """steps = distance_gps_m * k ; k = median(steps / distance) over train windows with distance >= MIN_DIST_M."""
    def fit(self, d, y):
        m = d.distance_gps_m.values >= MIN_DIST_M
        self.k = float(np.median(np.asarray(y)[m] / d.distance_gps_m.values[m])); return self
    def predict(self, d):
        return self.k * d.distance_gps_m.values


def rf(**kw):
    return RandomForestRegressor(n_estimators=300, random_state=SEED, n_jobs=-1, **kw)


def xgb(**kw):
    return XGBRegressor(objective="reg:squarederror", subsample=0.8, colsample_bytree=0.8, random_state=SEED, n_jobs=4,
                        tree_method="hist", **kw)


GRIDS = {
    "random_forest": (rf, [dict(max_depth=a, min_samples_leaf=b, max_features=c)
                           for a, b, c in itertools.product([8, 16, None], [1, 5, 20], [0.5, 1.0])]),
    "xgboost": (xgb, [dict(max_depth=a, learning_rate=b, n_estimators=n, min_child_weight=c)
                      for a, b, n, c in itertools.product([3, 5], [0.03, 0.1], [300], [1, 10])]),
}


def fit_pred(maker, params, trn, tst):
    m = maker(**params).fit(trn[FEATURES], trn.steps_target)
    return m, m.predict(tst[FEATURES])


# ---------------------------------------------------------------- tuning on validation
tuning, best_params, models = {}, {}, {}
for name, (maker, grid) in GRIDS.items():
    res = []
    for prm in grid:
        _, pv = fit_pred(maker, prm, tr, va)
        res.append({"params": prm, **reg_metrics(va.steps_target.values, pv)})
    res.sort(key=lambda r: r["MAE"])
    tuning[name] = res
    best_params[name] = res[0]["params"]
    models[name], _ = fit_pred(maker, best_params[name], tr, va)
mean_b = MeanBaseline().fit(tr, tr.steps_target)
lin_b = LinearDistBaseline().fit(tr, tr.steps_target)


def predict_all(d):
    return {"baseline_train_mean": mean_b.predict(d), "baseline_linear_distance": lin_b.predict(d),
            "random_forest": models["random_forest"].predict(d[FEATURES]),
            "xgboost": models["xgboost"].predict(d[FEATURES])}


pv = predict_all(va)
val_rep = full_report(va, pv)
best_name = min(("random_forest", "xgboost"), key=lambda n: val_rep[n]["window"]["MAE"])   # selection on validation MAE only

# permutation importance on VALIDATION (not test)
imp = {}
for name in ("random_forest", "xgboost"):
    pi = permutation_importance(models[name], va[FEATURES], va.steps_target, n_repeats=5, random_state=SEED,
                                scoring="neg_mean_absolute_error", n_jobs=1)
    native = models[name].feature_importances_
    imp[name] = {"native_importance": dict(zip(FEATURES, map(float, native))),
                 "native_type": "impurity (MDI)" if name == "random_forest" else "xgboost default (gain-based)",
                 "permutation_MAE_increase_validation_mean": dict(zip(FEATURES, map(float, pi.importances_mean))),
                 "permutation_MAE_increase_validation_std": dict(zip(FEATURES, map(float, pi.importances_std)))}

# ---------------------------------------------------------------- freeze, save, then score TEST once
joblib.dump(models["random_forest"], MODELS / "random_forest.joblib", compress=3)
models["xgboost"].save_model(str(MODELS / "xgboost.json"))
joblib.dump(models[best_name], MODELS / "best_model.joblib", compress=3)
joblib.dump({"mean": mean_b.m, "steps_per_meter_median": lin_b.k, "min_dist_m": MIN_DIST_M, "window_s": WIN_S},
            MODELS / "baselines.joblib")
(MODELS / "feature_list.json").write_text(json.dumps({"features": FEATURES, "target": "steps_target (steps per 5 s window)",
                                                      "baseline_distance": "speed_mean * 5 s (GPS only)"}, indent=1))

pt = predict_all(te)
test_rep = full_report(te, pt)
pred_df = te[["track", "subject", "win_idx", "t_start_ms", "speed_bin_gps", "distance_anomaly", "steps_target"]].copy()
for k, v in pt.items():
    pred_df["pred_" + k] = v
pred_df.to_csv(MET / "phase2_test_predictions.csv", index=False)

# ---------------------------------------------------------------- supplementary analyses (labelled)
anom_tracks = set(df[df.distance_anomaly].track)
def refit_eval(trn, label_shift=None):
    out = {}
    for name, (maker, _) in GRIDS.items():
        m = maker(**best_params[name]).fit(trn[FEATURES], trn.steps_target)
        out[name] = m
    return out


sens = {"note": "SUPPLEMENTARY. Hyper-parameters fixed from the primary validation tuning; not used for model selection."}
# (a) anomaly-ratio tracks: evaluate same models on subsets; and retrain without anomaly tracks
for tag, d, p in (("validation", va, pv), ("test", te, pt)):
    keep = ~d.distance_anomaly.values
    sens.setdefault("anomaly_tracks_excluded_from_evaluation_only", {})[tag] = {
        "n_windows_excluded": int((~keep).sum()),
        "included": {k: reg_metrics(d.steps_target.values, v) for k, v in p.items()},
        "excluded": {k: reg_metrics(d.steps_target.values[keep], np.asarray(v)[keep]) for k, v in p.items()}}
tr_na = tr[~tr.distance_anomaly]
m_na = refit_eval(tr_na)
sens["anomaly_tracks_excluded_from_training_and_evaluation"] = {
    "n_train_windows": int(len(tr_na)),
    **{tag: {n: reg_metrics(d.steps_target.values[~d.distance_anomaly.values],
                            m.predict(d[~d.distance_anomaly][FEATURES])) for n, m in m_na.items()}
       for tag, d in (("validation", va), ("test", te))}}

# (b) alignment-convention sensitivity: pair features of window i with the target of window i+k (k=+-1 => positions shifted by
# 5 s relative to steps). Coarse (5 s granularity), only consecutive windows within a track, applied to all sets.
def shifted(d, k):
    d = d.sort_values(["track", "win_idx"]).copy()
    key = d.set_index(["track", "win_idx"]).steps_target
    tgt = [key.get((t, w + k), np.nan) for t, w in zip(d.track, d.win_idx)]
    d["steps_target"] = tgt
    return d.dropna(subset=["steps_target"]).reset_index(drop=True)
sens["alignment_convention_sensitivity"] = {
    "description": "LABELLED SENSITIVITY ONLY. Features of window i paired with the target of window i+k (k in -1,0,+1; 5 s = one "
                   "window). k=0 is the adopted H0 convention. Coarse: sub-window shifts and the testStart (H1) re-basing are not tested.",
    "shifts": {}}
for k in (-1, 0, 1):
    trk, vak, tek = (shifted(x, k) for x in (tr, va, te))
    ms = refit_eval(trk)
    lin = LinearDistBaseline().fit(trk, trk.steps_target)
    sens["alignment_convention_sensitivity"]["shifts"][str(k)] = {
        tag: {**{n: reg_metrics(d.steps_target.values, m.predict(d[FEATURES])) for n, m in ms.items()},
              "baseline_linear_distance": reg_metrics(d.steps_target.values, lin.predict(d))}
        for tag, d in (("validation", vak), ("test", tek))}

# (c) leave-one-subject-out over all 18 subjects (supplementary, NOT the headline result)
loso_rows, loso_pred = [], []
for s in sorted(df.subject.unique()):
    trn, tst = df[df.subject != s], df[df.subject == s]
    preds = {"baseline_train_mean": MeanBaseline().fit(trn, trn.steps_target).predict(tst),
             "baseline_linear_distance": LinearDistBaseline().fit(trn, trn.steps_target).predict(tst)}
    for name, (maker, _) in GRIDS.items():
        preds[name] = maker(**best_params[name]).fit(trn[FEATURES], trn.steps_target).predict(tst[FEATURES])
    for n, p in preds.items():
        r = reg_metrics(tst.steps_target.values, p)
        loso_rows.append({"subject": int(s), "model": n, **r})
        loso_pred.append(pd.DataFrame({"model": n, "y": tst.steps_target.values, "p": p}))
loso = pd.DataFrame(loso_rows)
allp = pd.concat(loso_pred)
sens["leave_one_subject_out_all_18_subjects"] = {
    "note": "SUPPLEMENTARY, not the headline result. Hyper-parameters fixed from the primary tuning (which used validation subjects 3,10,11, "
            "so these folds are not fully independent of tuning).",
    "pooled_over_all_windows": {n: reg_metrics(g.y.values, g.p.values) for n, g in allp.groupby("model")},
    "per_subject_MAE_mean_std": {n: {"mean": float(g.MAE.mean()), "std": float(g.MAE.std()), "min": float(g.MAE.min()),
                                      "max": float(g.MAE.max())} for n, g in loso.groupby("model")},
    "per_subject": loso.to_dict(orient="records")}

# ---------------------------------------------------------------- plots (test set)
colors = {"random_forest": "tab:green", "xgboost": "tab:orange"}
fig, ax = plt.subplots(1, 2, figsize=(11, 5))
for a, n in zip(ax, ("random_forest", "xgboost")):
    a.scatter(te.steps_target, pt[n], s=5, alpha=0.3, color=colors[n])
    a.plot([0, 15], [0, 15], "k--", lw=1)
    a.set_xlabel("actual steps / 5 s"); a.set_ylabel("predicted steps / 5 s")
    a.set_title(f"{n}: test (R2={test_rep[n]['window']['R2']:.3f})")
fig.tight_layout(); fig.savefig(PLOTS / "phase2_pred_vs_actual_test.png", dpi=130); plt.close(fig)
fig, ax = plt.subplots(2, 2, figsize=(11, 8))
for j, n in enumerate(("random_forest", "xgboost")):
    r = te.steps_target.values - pt[n]
    ax[0, j].scatter(pt[n], r, s=5, alpha=0.3, color=colors[n]); ax[0, j].axhline(0, color="k", lw=1)
    ax[0, j].set_xlabel("predicted"); ax[0, j].set_ylabel("residual (actual - predicted)"); ax[0, j].set_title(f"{n}: residual vs predicted (test)")
    ax[1, j].hist(r, bins=60, color=colors[n]); ax[1, j].set_xlabel("residual"); ax[1, j].set_title(f"{n}: residual histogram (test)")
fig.tight_layout(); fig.savefig(PLOTS / "phase2_residuals_test.png", dpi=130); plt.close(fig)
fig, ax = plt.subplots(figsize=(7, 4))
mods = ["baseline_train_mean", "baseline_linear_distance", "random_forest", "xgboost"]
w = 0.2
for i, n in enumerate(mods):
    ax.bar(np.arange(5) + i * w, [test_rep[n]["by_speed_bin_gps"][l].get("MAE", np.nan) for l in LABELS], w, label=n)
ax.set_xticks(np.arange(5) + 1.5 * w)
ax.set_xticklabels([f"{l}\n(n={test_rep['random_forest']['by_speed_bin_gps'][l]['n']})" for l in LABELS])
ax.set_xlabel("GPS speed bin (m/s)"); ax.set_ylabel("test MAE (steps / 5 s)"); ax.legend(fontsize=7)
fig.tight_layout(); fig.savefig(PLOTS / "phase2_mae_by_speed_bin_test.png", dpi=130); plt.close(fig)
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
for a, n in zip(ax, ("random_forest", "xgboost")):
    v = pd.Series(imp[n]["permutation_MAE_increase_validation_mean"]).sort_values()
    a.barh(v.index, v.values, color=colors[n]); a.set_title(f"{n}: permutation importance (validation, MAE increase)")
fig.tight_layout(); fig.savefig(PLOTS / "phase2_feature_importance.png", dpi=130); plt.close(fig)

# ---------------------------------------------------------------- config + metrics JSON
versions = {"python": sys.version.split()[0], "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__,
            "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__}
config = {"seed": SEED, "split_seed": splits["seed"], "split_ids": splits["subjects"], "library_versions": versions,
          "features": FEATURES, "selected_model": best_name, "selection_rule": "lowest validation window MAE (models fit on train subjects only)",
          "search_grids": {k: v[1] for k, v in GRIDS.items()}, "best_params": best_params,
          "fixed_params": {"random_forest": {"n_estimators": 300}, "xgboost": {"subsample": 0.8, "colsample_bytree": 0.8, "tree_method": "hist",
                                                                                "objective": "reg:squarederror"}},
          "final_fit_data": "train subjects only (validation used for selection, not merged into training)",
          "nan_handling": "feature NaNs (single-fix windows: displacement/path/derived speed; first window of a track: lag_*) are passed natively to RF (sklearn>=1.4) and XGBoost",
          "baselines": {"baseline_train_mean": f"predicts train-mean steps ({mean_b.m:.4f})",
                        "baseline_linear_distance": f"steps = {lin_b.k:.4f} steps/m x (GPS speed_mean x 5 s); k = median ratio over train windows with distance >= {MIN_DIST_M} m"},
          "alignment_decision": align.get("decision", {}).get("convention"),
          "alignment_confidence": align.get("decision", {}).get("confidence"),
          "step_handling_decision": mono.get("decision", mono.get("recommended_handling")),
          "window_target": "cum(T_end)-cum(T_start), cum = running max of steps counter (monotonicity decision)",
          "no_imu_or_step_features": True, "test_scored_once_after_freeze": True}
metrics = {"versions": versions, "selected_model": best_name,
           "baseline_params": {"train_mean": mean_b.m, "steps_per_meter_median": lin_b.k},
           "tuning_validation": tuning, "validation": val_rep, "test": test_rep, "feature_importance": imp,
           "test_target_stats": {"mean": float(te.steps_target.mean()), "std": float(te.steps_target.std())},
           "validation_target_stats": {"mean": float(va.steps_target.mean()), "std": float(va.steps_target.std())},
           "supplementary": sens, "speed_bin_min_n_flag": MIN_BIN_N}
(MODELS / "training_config.json").write_text(json.dumps(config, indent=1, default=str))
(MODELS / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=1))
(MET / "phase2_model_metrics.json").write_text(json.dumps(metrics, indent=1))
print("selected", best_name, best_params[best_name])
for tag, rep in (("VAL", val_rep), ("TEST", test_rep)):
    for n, r in rep.items():
        w_ = r["window"]; t_ = r["track_level"]
        print(tag, n, f"MAE={w_['MAE']:.4f} RMSE={w_['RMSE']:.4f} R2={w_['R2']:.4f} | track MAPE={t_['mean_abs_pct_err']:.2f}% pooled bias={t_['pooled_bias_pct']:.2f}%")
