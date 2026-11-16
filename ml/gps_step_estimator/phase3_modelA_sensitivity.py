"""Phase 3 follow-ups for Model A (GPS-only step estimator). SUPPLEMENTARY; does not change Phase 2 headline numbers.
Run with the project venv (it has the library versions recorded for Phase 2: sklearn 1.9.1 / xgboost 3.4.1):
    .venv/Scripts/python.exe ml/gps_step_estimator/phase3_modelA_sensitivity.py

Part 1  timestamp-alignment sensitivity. Phase 2 headline (H0) treats positions.ms and steps.ms as one clock. Alternatives:
        H1  positions.ms is relative to testStart, so on the steps clock a fix is at ms + testStart
        LAG positions shifted by +/-1, 2, 5 s (position stamp + delta)
        Cleaning (C1-C4 of phase2_build_windows.py) is unaffected by a uniform shift, so fixes are cleaned once and re-stamped.
        Window span on the steps clock is the Phase 2 span [max(testStart,0), min(testEnd, last steps ms)]; target is unchanged.
        Models: RF/XGBoost with the FIXED Phase 2 hyper-parameters (HEAD training_config.json) and the Phase 2 subject split;
        second run re-tunes on validation with the Phase 2 grids.
Part 2  distance-anomaly tracks excluded (evaluation only; training+evaluation), fixed hyper-parameters.
Outputs (new paths only): results/metrics/phase3_modelA_sensitivity/*.json, results/metrics/phase3_modelA_anomaly_exclusion.json,
        datasets/dryad/processed/phase3_modelA_sensitivity/windows_*.csv. No model files are written.
"""
import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
import dryad_io as d  # noqa: E402

MET = ROOT / "results" / "metrics"
OUT = MET / "phase3_modelA_sensitivity"
WOUT = ROOT / "datasets" / "dryad" / "processed" / "phase3_modelA_sensitivity"
OUT.mkdir(parents=True, exist_ok=True)
WOUT.mkdir(parents=True, exist_ok=True)
SEED = 42
GAP_MAX_S, CONF_MAX_M, TELEPORT_MPS, WIN_MS, WIN_S = 10.0, 50.0, 10.0, 5000.0, 5.0
BINS = [0, 0.5, 1.0, 1.5, 2.0, np.inf]
LABELS = ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", ">2.0"]


def git_show(path):
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, check=True).stdout


# ------------------------------------------------------------------ cleaning (copy of phase2_build_windows.py logic)
def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    la1, la2, lo1, lo2 = map(np.radians, (lat1, lat2, lon1, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def teleport_drop(p):
    p = p.reset_index(drop=True)
    while len(p) > 2:
        dist = hav(p.latitude.values[:-1], p.longitude.values[:-1], p.latitude.values[1:], p.longitude.values[1:])
        dt = np.maximum(np.diff(p.ms.values) / 1000.0, 1.0)
        v = dist / dt
        bad_link = v > TELEPORT_MPS
        left = np.r_[True, bad_link]
        right = np.r_[bad_link, True]
        bad = left & right & (np.r_[False, bad_link] | np.r_[bad_link, False])
        if not bad.any():
            break
        score = np.r_[0, v] + np.r_[v, 0]
        score[~bad] = -1
        p = p.drop(index=int(np.argmax(score))).reset_index(drop=True)
    return p


def cum_fn(st):
    st = st.sort_values("ms", kind="stable")
    ms, rm = st.ms.values.astype(float), np.maximum.accumulate(st.steps.values.astype(float))

    def f(T):
        i = np.searchsorted(ms, T, side="right") - 1
        return 0.0 if i < 0 else float(rm[i])
    return f


def bin_label(v):
    if v is None or not np.isfinite(v):
        return "unknown"
    return LABELS[int(np.searchsorted(BINS, v, side="right") - 1)]


def clean_all():
    out = []
    for name, meta in d.model_a_tracks():
        t = d.load_track(name)
        p = t["positions"]
        p = p[np.isfinite(p[["ms", "latitude", "longitude"]].values).all(axis=1)].sort_values("ms", kind="stable").drop_duplicates()
        conf = p.confInterval
        p = p[conf.notna() & (conf >= 0) & (conf <= CONF_MAX_M)]
        p = teleport_drop(p)
        sp = pd.to_numeric(p.speed, errors="coerce")
        p = p.assign(speed_ok=(sp.notna() & (sp >= 0)).values)
        out.append((name, meta, t["events"].iloc[0], t["steps"], p))
    return out


def build_windows(cleaned, delta_ms_fn):
    """delta_ms_fn(testStart) -> ms added to every position stamp (steps clock = positions.ms + delta)."""
    rows = []
    for name, meta, ev, st, p0 in cleaned:
        ts, te = float(ev.testStart), float(ev.testEnd)
        p = p0.assign(ms=p0.ms.astype(float) + delta_ms_fn(ts))
        ms = p.ms.values.astype(float)
        gaps = np.diff(ms) / 1000.0
        glist = [(ms[i], ms[i + 1]) for i in np.where(gaps > GAP_MAX_S)[0]]
        start = max(ts, 0.0)
        end = min(te, float(st.ms.max()))
        nwin = int(np.floor((end - start) / WIN_MS))
        cum = cum_fn(st)
        meta_speed = float(meta["average_walking_speed"])
        trows = []
        for k in range(nwin):
            a, b = start + k * WIN_MS, start + (k + 1) * WIN_MS
            inc = cum(b) - cum(a)
            if any(g0 < b and g1 > a for g0, g1 in glist):
                continue
            w = p[(p.ms >= a) & (p.ms < b)]
            if len(w) < 1:
                continue
            v = w.speed[w.speed_ok].values.astype(float)
            if len(v) == 0:
                continue
            dist = hav(w.latitude.values[:-1], w.longitude.values[:-1], w.latitude.values[1:], w.longitude.values[1:])
            one = len(w) < 2
            path = np.nan if one else float(dist.sum())
            disp = np.nan if one else float(hav(w.latitude.values[0], w.longitude.values[0], w.latitude.values[-1], w.longitude.values[-1]))
            covered = (w.ms.values[-1] - w.ms.values[0]) / 1000.0
            trows.append(dict(
                track=name, subject=int(meta["subject"]), win_idx=k, t_start_ms=a, steps_target=inc,
                n_fixes=len(w), n_speed_valid=len(v), displacement_m=disp, path_m=path,
                speed_mean=v.mean(), speed_median=float(np.median(v)), speed_max=v.max(), speed_std=v.std(),
                speed_delta=float(v[-1] - v[0]), conf_mean=float(w.confInterval.mean()),
                coverage_frac=covered / (WIN_MS / 1000.0), covered_dur_s=covered,
                derived_speed_mps=(path / covered if (not one and covered > 0) else np.nan),
                speed_bin_gps=bin_label(v.mean()), speed_bin_ref=bin_label(meta_speed)))
        df = pd.DataFrame(trows)
        if len(df):
            prev = df.set_index("win_idx")
            for col, new in [("speed_mean", "lag_speed_mean"), ("path_m", "lag_path_m")]:
                df[new] = df.win_idx.map(lambda k: prev[col].get(k - 1, np.nan))
        rows.append(df)
    return pd.concat(rows, ignore_index=True)


# ------------------------------------------------------------------ models / metrics (as in train_eval.py)
def reg_metrics(y, p):
    return {"n": int(len(y)), "MAE": float(mean_absolute_error(y, p)),
            "RMSE": float(np.sqrt(mean_squared_error(y, p))), "R2": float(r2_score(y, p)) if len(y) > 1 else None}


def rf(**kw):
    return RandomForestRegressor(n_estimators=300, random_state=SEED, n_jobs=-1, **kw)


def xgb(**kw):
    return XGBRegressor(objective="reg:squarederror", subsample=0.8, colsample_bytree=0.8, random_state=SEED, n_jobs=4,
                        tree_method="hist", **kw)


MAKERS = {"random_forest": rf, "xgboost": xgb}
GRIDS = {
    "random_forest": [dict(max_depth=a, min_samples_leaf=b, max_features=c)
                      for a, b, c in itertools.product([8, 16, None], [1, 5, 20], [0.5, 1.0])],
    "xgboost": [dict(max_depth=a, learning_rate=b, n_estimators=n, min_child_weight=c)
                for a, b, n, c in itertools.product([3, 5], [0.03, 0.1], [300], [1, 10])],
}
cfg_head = json.loads(git_show("ml/models/training_config.json"))
FIXED = cfg_head["best_params"]
FEATURES = cfg_head["features"]
SPLITS = json.loads((MET / "phase2_splits.json").read_text())["subjects"]
SUB = {k: set(v) for k, v in SPLITS.items()}
assert not (SUB["train"] & SUB["validation"] or SUB["train"] & SUB["test"] or SUB["validation"] & SUB["test"])


def split(W):
    W = W.copy()
    W["set"] = W.subject.map({s: k for k, v in SUB.items() for s in v})
    assert W["set"].notna().all()
    return tuple(W[W.set == s].reset_index(drop=True) for s in ("train", "validation", "test"))


class LinB:
    def fit(self, d_, y):
        m = d_.speed_mean.values * WIN_S >= 0.5
        self.k = float(np.median(np.asarray(y)[m] / (d_.speed_mean.values[m] * WIN_S)))
        return self

    def predict(self, d_):
        return self.k * d_.speed_mean.values * WIN_S


def fit_models(trn, params):
    return {n: MAKERS[n](**params[n]).fit(trn[FEATURES], trn.steps_target) for n in MAKERS}


def tune(trn, val):
    best = {}
    for n, grid in GRIDS.items():
        res = []
        for prm in grid:
            m = MAKERS[n](**prm).fit(trn[FEATURES], trn.steps_target)
            res.append((reg_metrics(val.steps_target.values, m.predict(val[FEATURES]))["MAE"], prm))
        res.sort(key=lambda r: r[0])
        best[n] = res[0][1]
    return best


def preds_for(models, lin, dset):
    p = {n: m.predict(dset[FEATURES]) for n, m in models.items()}
    p["baseline_linear_distance"] = lin.predict(dset)
    return p


def per_subject(dset, p):
    return {str(int(s)): reg_metrics(g.steps_target.values, np.asarray(p)[g.index.values]) for s, g in dset.groupby("subject")}


def per_bin(dset, p):
    out = {}
    for lab in LABELS:
        m = (dset.speed_bin_gps == lab).values
        out[lab] = reg_metrics(dset.steps_target.values[m], np.asarray(p)[m]) if m.sum() > 1 else {"n": int(m.sum())}
    return out


def evaluate(W, params, ref_keys=None):
    tr, va, te = split(W)
    models = fit_models(tr, params)
    lin = LinB().fit(tr, tr.steps_target)
    pv, pt = preds_for(models, lin, va), preds_for(models, lin, te)
    res = {"n_windows": {"train": len(tr), "validation": len(va), "test": len(te)}, "params": params,
           "validation": {n: reg_metrics(va.steps_target.values, p) for n, p in pv.items()},
           "test": {n: reg_metrics(te.steps_target.values, p) for n, p in pt.items()},
           "test_per_subject": {n: per_subject(te, p) for n, p in pt.items() if n != "baseline_linear_distance"},
           "test_by_speed_bin_gps": {n: per_bin(te, p) for n, p in pt.items() if n != "baseline_linear_distance"}}
    if ref_keys is not None:  # test windows present in the H0 headline window set (same rows, different features)
        m = pd.Series(list(zip(te.track, te.win_idx))).isin(ref_keys).values
        res["test_on_windows_common_with_H0"] = {"n": int(m.sum()), **{n: reg_metrics(te.steps_target.values[m], np.asarray(p)[m]) for n, p in pt.items()}}
    return res, (tr, va, te, models, lin, pv, pt)


def main():
    versions = {"python": sys.version.split()[0], "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__,
                "numpy": np.__version__, "pandas": pd.__version__}
    print(versions)
    cleaned = clean_all()
    head_metrics = json.loads(git_show("results/metrics/phase2_model_metrics.json"))
    conds = {"H0_headline": lambda ts: 0.0, "H1_positions_relative_to_testStart": lambda ts: ts}
    for s in (1, 2, 5):
        conds[f"lag_plus{s}s"] = (lambda s_: (lambda ts: s_ * 1000.0))(s)
        conds[f"lag_minus{s}s"] = (lambda s_: (lambda ts: -s_ * 1000.0))(s)

    # ---- verify H0 rebuild == Phase 2 windows file
    Wh = build_windows(cleaned, conds["H0_headline"])
    W2 = pd.read_csv(ROOT / "datasets" / "dryad" / "processed" / "windows_5s.csv")
    cols = [c for c in Wh.columns]
    A = Wh[cols].reset_index(drop=True)
    B = W2[cols].reset_index(drop=True)
    same_shape = A.shape == B.shape
    rebuild = {"same_shape": bool(same_shape), "shape_rebuilt": list(A.shape), "shape_phase2": list(B.shape)}
    if same_shape:
        num = [c for c in cols if A[c].dtype.kind in "fi"]
        rebuild["max_abs_diff_numeric"] = float(np.nanmax(np.abs(A[num].values.astype(float) - B[num].values.astype(float))))
        rebuild["nan_pattern_equal"] = bool((A[num].isna().values == B[num].isna().values).all())
        rebuild["string_cols_equal"] = bool((A[["track", "speed_bin_gps", "speed_bin_ref"]] == B[["track", "speed_bin_gps", "speed_bin_ref"]]).all().all())
    anom = sorted(W2[W2.distance_anomaly].track.unique())
    excl = json.loads((MET / "phase2_exclusions.json").read_text())["distance_anomaly_tracks"]
    anom_flagged = sorted(excl["tracks"])
    print("H0 rebuild vs windows_5s.csv:", rebuild)
    print("flagged anomaly tracks:", len(anom_flagged), "with >=1 kept window:", len(anom))
    ref_keys = set(zip(Wh.track, Wh.win_idx))

    # ---- Part 1
    sens = {"description": "SUPPLEMENTARY alignment sensitivity; Phase 2 headline (H0) unchanged.", "versions": versions,
            "h0_rebuild_vs_windows_5s_csv": rebuild, "fixed_params_source": "git HEAD ml/models/training_config.json best_params",
            "fixed_params": FIXED, "conditions": {}}
    sens_retuned = {"description": "SUPPLEMENTARY second run: hyper-parameters re-tuned on VALIDATION per condition (Phase 2 grids).",
                    "versions": versions, "conditions": {}}
    for tag, fn in conds.items():
        W = Wh if tag == "H0_headline" else build_windows(cleaned, fn)
        W["distance_anomaly"] = W.track.isin(anom_flagged)
        W.to_csv(WOUT / f"windows_{tag}.csv", index=False)
        r, ctx = evaluate(W, FIXED, ref_keys)
        sens["conditions"][tag] = r
        tr, va, te = ctx[0], ctx[1], ctx[2]
        bp = tune(tr, va)
        r2, _ = evaluate(W, bp, ref_keys)
        sens_retuned["conditions"][tag] = r2
        t = r["test"]
        print(f"{tag:38s} n_test={len(te):5d} RF MAE={t['random_forest']['MAE']:.4f} R2={t['random_forest']['R2']:.4f} | "
              f"XGB MAE={t['xgboost']['MAE']:.4f} R2={t['xgboost']['R2']:.4f} | retuned RF {r2['test']['random_forest']['MAE']:.4f} XGB {r2['test']['xgboost']['MAE']:.4f}", flush=True)
    # compare H0 reproduction with committed headline
    cmp = {}
    for n in ("random_forest", "xgboost"):
        for tag in ("validation", "test"):
            h = head_metrics[tag][n]["window"]
            o = sens["conditions"]["H0_headline"][tag][n]
            cmp[f"{n}_{tag}"] = {k: {"committed_HEAD": h[k], "rerun_venv": o[k], "abs_diff": abs(h[k] - o[k])} for k in ("MAE", "RMSE", "R2")}
    sens["h0_rerun_vs_committed_headline"] = cmp
    for cond, r in sens["conditions"].items():
        base = sens["conditions"]["H0_headline"]["test"]
        r["delta_vs_H0_test"] = {n: {k: r["test"][n][k] - base[n][k] for k in ("MAE", "RMSE", "R2")} for n in MAKERS}
    (OUT / "alignment_sensitivity_fixed_params.json").write_text(json.dumps(sens, indent=1))
    (OUT / "alignment_sensitivity_retuned.json").write_text(json.dumps(sens_retuned, indent=1))

    # ---- Part 2: anomaly exclusion on H0 windows, fixed params
    W = Wh.copy()
    W["distance_anomaly"] = W.track.isin(anom_flagged)
    tr, va, te = split(W)
    models = fit_models(tr, FIXED)
    lin = LinB().fit(tr, tr.steps_target)
    pv, pt = preds_for(models, lin, va), preds_for(models, lin, te)
    res = {"note": "SUPPLEMENTARY. Headline keeps the anomalous tracks. Fixed Phase 2 hyper-parameters, Phase 2 subject split, venv libraries.",
           "versions": versions, "anomaly_definition": excl["definition"], "n_flagged_tracks": len(anom_flagged),
           "flagged_tracks": anom_flagged, "n_flagged_with_kept_windows": len(anom),
           "flagged_tracks_without_kept_windows": sorted(set(anom_flagged) - set(anom)),
           "windows_in_flagged_tracks": {"train": int(tr.distance_anomaly.sum()), "validation": int(va.distance_anomaly.sum()), "test": int(te.distance_anomaly.sum())},
           "flagged_tracks_by_split": {s: sorted(set(x[x.distance_anomaly].track)) for s, x in (("train", tr), ("validation", va), ("test", te))}}
    ev_only, tr_ev = {}, {}
    for tag, dset, p in (("validation", va, pv), ("test", te, pt)):
        keep = ~dset.distance_anomaly.values
        ev_only[tag] = {"n_windows_excluded": int((~keep).sum()),
                        "included_all_tracks": {k: reg_metrics(dset.steps_target.values, v) for k, v in p.items()},
                        "excluded_flagged_tracks": {k: reg_metrics(dset.steps_target.values[keep], np.asarray(v)[keep]) for k, v in p.items()}}
    tr_na = tr[~tr.distance_anomaly].reset_index(drop=True)
    m_na = fit_models(tr_na, FIXED)
    lin_na = LinB().fit(tr_na, tr_na.steps_target)
    tr_ev["n_train_windows"] = len(tr_na)
    for tag, dset in (("validation", va), ("test", te)):
        dn = dset[~dset.distance_anomaly].reset_index(drop=True)
        p = preds_for(m_na, lin_na, dn)
        tr_ev[tag] = {"n_windows": len(dn), **{k: reg_metrics(dn.steps_target.values, v) for k, v in p.items()}}
    res["evaluation_only_exclusion"] = ev_only
    res["training_and_evaluation_exclusion"] = tr_ev
    # verify vs Phase 2 stored values (committed HEAD and working tree)
    head_s = head_metrics["supplementary"]
    wt_s = json.loads((MET / "phase2_model_metrics.json").read_text())["supplementary"]
    ver = {}
    for src, s in (("committed_HEAD", head_s), ("working_tree_modified", wt_s)):
        v = {}
        for tag in ("validation", "test"):
            for n in MAKERS:
                a = s["anomaly_tracks_excluded_from_evaluation_only"][tag]["excluded"][n]
                b = ev_only[tag]["excluded_flagged_tracks"][n]
                v[f"eval_only_{tag}_{n}"] = {k: {"phase2": a[k], "now": b[k], "abs_diff": abs(a[k] - b[k])} for k in ("MAE", "RMSE", "R2")}
                a = s["anomaly_tracks_excluded_from_training_and_evaluation"][tag][n]
                b = tr_ev[tag][n]
                v[f"train_eval_{tag}_{n}"] = {k: {"phase2": a[k], "now": b[k], "abs_diff": abs(a[k] - b[k])} for k in ("MAE", "RMSE", "R2")}
        v["max_abs_diff_over_all"] = max(x["abs_diff"] for e in v.values() for x in e.values())
        ver[src] = v
    res["comparison_with_phase2_stored_supplementary"] = ver
    res["phase2_headline_included_for_reference"] = {tag: {n: head_metrics[tag][n]["window"] for n in MAKERS} for tag in ("validation", "test")}
    (MET / "phase3_modelA_anomaly_exclusion.json").write_text(json.dumps(res, indent=1))
    print("anomaly verify max abs diff vs HEAD:", ver["committed_HEAD"]["max_abs_diff_over_all"],
          "vs working tree:", ver["working_tree_modified"]["max_abs_diff_over_all"])
    for tag in ("test",):
        print("eval-only excluded:", {n: ev_only[tag]["excluded_flagged_tracks"][n] for n in MAKERS})
        print("train+eval excluded:", {n: tr_ev[tag][n] for n in MAKERS})


if __name__ == "__main__":
    main()
