"""Phase 3 Model B: single entry script. `python ml/activity_classifier/run_pipeline.py` reruns everything end to end.

Model B is a physical-ACTIVITY classifier (WALKING / STATIONARY / OTHER). It is NOT trained or evaluated on GPS spoofing.
Headline = within-dataset subject-independent evaluation. Cross-dataset and combined-model runs are a separate
generalisation experiment. Hyperparameters are chosen on validation subjects only; each test set is scored once per model.
"""
import itertools
import json
import platform
import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy
import sklearn
import xgboost
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
sys.path.insert(0, str(ROOT / "ml" / "feature_extraction"))
sys.path.insert(0, str(ROOT / "ml" / "evaluation"))
import activity_data as D  # noqa: E402
import activity_features as F  # noqa: E402
import activity_metrics as M  # noqa: E402

SEED = 42
MS_SPLIT = (16, 4, 4)
UCI_N_VAL_SUBJECTS = 5
MODELS_DIR = ROOT / "ml" / "models"
MET = ROOT / "results" / "metrics"
CMD = ROOT / "results" / "confusion_matrices"
PLT = ROOT / "results" / "plots"
CLS = D.CLASSES

GRIDS = {
    "random_forest": [dict(max_depth=d, min_samples_leaf=l) for d, l in itertools.product([8, 16, None], [1, 5])],
    "xgboost": [dict(max_depth=d, learning_rate=lr, n_estimators=n) for d, lr, n in itertools.product([3, 6], [0.05, 0.15], [150, 300])],
    "logistic_regression": [dict(C=c) for c in [0.01, 0.1, 1.0, 10.0]],
}
SELECTABLE = ["random_forest", "xgboost"]  # logistic regression and majority are baselines only


def jdump(obj, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=False))


def make_model(kind, params):
    if kind == "random_forest":
        return RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1, class_weight="balanced", **params)
    if kind == "xgboost":
        return XGBClassifier(objective="multi:softprob", tree_method="hist", random_state=SEED, n_jobs=4, **params)
    if kind == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=3000, random_state=SEED, **params))
    if kind == "majority":
        return DummyClassifier(strategy="most_frequent")
    raise ValueError(kind)


def fit(kind, params, X, y, weighted=True):
    m = make_model(kind, params)
    if not weighted:
        if kind == "random_forest":
            m.set_params(class_weight=None)
        elif kind == "logistic_regression":
            m.set_params(logisticregression__class_weight=None)
    if kind == "xgboost" and weighted:
        m.fit(X, y, sample_weight=compute_sample_weight("balanced", y))
    else:
        m.fit(X, y)
    return m


def mf1(y, p):
    return float(f1_score(y, p, labels=[0, 1, 2], average="macro", zero_division=0))


def tune(Xtr, ytr, Xva, yva):
    """Grid search scored on validation macro-F1 only. Returns {kind: {best_params, val_macro_f1, grid}}."""
    out = {}
    for kind in ["logistic_regression", "random_forest", "xgboost"]:
        res = []
        for pr in GRIDS[kind]:
            res.append({"params": pr, "val_macro_f1": mf1(yva, fit(kind, pr, Xtr, ytr).predict(Xva))})
        best = max(res, key=lambda r: r["val_macro_f1"])
        out[kind] = {"best_params": best["params"], "val_macro_f1": best["val_macro_f1"], "grid": res}
    sel = max(SELECTABLE, key=lambda k: out[k]["val_macro_f1"])
    return out, sel


def idx(meta, mask):
    return np.where(mask)[0]


def balance(meta, split_col):
    t = pd.crosstab(meta[split_col], meta["class_name"]).reindex(columns=CLS, fill_value=0)
    orig = pd.crosstab([meta[split_col], meta["orig_short"]], meta["class_name"]).reindex(columns=CLS, fill_value=0)
    return {"windows_by_class": {s: {c: int(t.loc[s, c]) for c in CLS} for s in t.index},
            "subjects": {s: int(meta.loc[meta[split_col] == s, "subject"].nunique()) for s in t.index},
            "windows_by_original_activity_and_class": {f"{a}|{b}": {c: int(v[c]) for c in CLS} for (a, b), v in orig.iterrows()}}


def eval_block(kind, params, model, X, meta, tag):
    p = model.predict(X); y = meta["y"].to_numpy()
    r = {"model": kind, "params": params, **M.metrics(y, p), "per_subject": M.per_subject(meta, y, p),
         "diagnostic_by_original_activity": M.diagnostic_by_original(meta, p), "key_error_rates": M.key_error_rates(meta, p)}
    return r, p


def pred_rows(meta, p, experiment, kind):
    d = meta[["dataset", "subject", "recording", "orig_activity", "orig_short", "class_name", "y"]].copy()
    d.insert(0, "experiment", experiment); d.insert(1, "model", kind)
    d["y_pred"] = p; d["pred_class"] = [CLS[i] for i in p]
    return d.rename(columns={"y": "y_true", "class_name": "true_class"})


def main():
    np.random.seed(SEED)
    for d in (MODELS_DIR, MET, CMD, PLT):
        d.mkdir(parents=True, exist_ok=True)
    # ---------------- data ----------------
    print("loading MotionSense ..."); Xm, mm, repm = D.load_motionsense()
    print("loading UCI HAR ..."); Xu, mu, repu = D.load_uci()
    Fm, Fu = F.extract_features(Xm), F.extract_features(Xu)
    assert np.isfinite(Fm).all() and np.isfinite(Fu).all()
    # ---------------- splits ----------------
    ms_subj = sorted(mm["subject"].unique().tolist())
    perm = np.random.RandomState(SEED).permutation(ms_subj).tolist()
    ms_sets = {"train": sorted(perm[:16]), "val": sorted(perm[16:20]), "test": sorted(perm[20:24])}
    mm["split"] = mm["subject"].map({s: k for k, v in ms_sets.items() for s in v})
    uci_train = sorted(mu.loc[mu.split_provided == "train", "subject"].unique().tolist())
    uci_test = sorted(mu.loc[mu.split_provided == "test", "subject"].unique().tolist())
    uperm = np.random.RandomState(SEED).permutation(uci_train).tolist()
    uci_sets = {"train": sorted(uperm[UCI_N_VAL_SUBJECTS:]), "val": sorted(uperm[:UCI_N_VAL_SUBJECTS]), "test": uci_test}
    mu["split"] = mu["subject"].map({s: k for k, v in uci_sets.items() for s in v})
    for nm, sets in [("MotionSense", ms_sets), ("UCI_HAR", uci_sets)]:
        a, b, c = map(set, (sets["train"], sets["val"], sets["test"]))
        assert not (a & b) and not (a & c) and not (b & c), f"subject overlap in {nm}"
    assert len(ms_subj) == 24 and [len(ms_sets[k]) for k in ("train", "val", "test")] == list(MS_SPLIT)
    assert len(uci_train) == 21 and len(uci_test) == 9 and not (set(uci_train) & set(uci_test))
    assert mm["split"].notna().all() and mu["split"].notna().all()
    # label-mapping safety test: jogging / stairs never STATIONARY
    for a in ["jog", "ups", "dws"]:
        assert D.MS_LABEL_MAP[a] != "STATIONARY"
    for a in ["WALKING_UPSTAIRS", "WALKING_DOWNSTAIRS"]:
        assert D.UCI_LABEL_MAP[a] == "OTHER"
    assert set(mm.loc[mm.orig_short.isin(["jog", "ups", "dws"]), "class_name"]) == {"OTHER"}
    assert set(mu.loc[mu.orig_short.isin(["ups", "dws"]), "class_name"]) == {"OTHER"}
    assert Xm.shape[2] == 6 and Xu.shape[2] == 6
    jdump({"seed": SEED, "motionsense": {"split": ms_sets, "n_subjects": {k: len(v) for k, v in ms_sets.items()}, "zero_overlap_asserted": True},
           "uci_har": {"split": uci_sets, "n_subjects": {k: len(v) for k, v in uci_sets.items()}, "zero_overlap_asserted": True,
                       "note": "test = provided UCI test subjects; val = 5 seeded subjects carved from the 21 provided train subjects"}},
          MET / "activity_splits.json")
    bal = {"MotionSense": balance(mm, "split"), "UCI_HAR": balance(mu, "split")}
    jdump({"motionsense": repm, "uci_har": repu, "class_balance_after_mapping": bal,
           "label_map": {"MotionSense": D.MS_LABEL_MAP, "UCI_HAR": D.UCI_LABEL_MAP}, "class_codes": {c: i for i, c in enumerate(CLS)},
           "window": {"samples": 128, "stride_motionsense": 64, "seconds_at_50hz": 2.56, "overlap": "50%"},
           "peak_params": {"prominence_g": F.PEAK_PROMINENCE_G, "distance_samples": F.PEAK_DISTANCE}}, MET / "activity_preparation_report.json")
    # ---------------- feature list / config skeleton ----------------
    jdump({"features": F.FEATURE_NAMES, "channels_in_window": D.CHANNELS, "n_features": len(F.FEATURE_NAMES),
           "orientation_independent": True, "excluded": ["total_acc", "gravity", "attitude", "561 UCI features", "GPS", "step features"]},
          MODELS_DIR / "activity_feature_list.json")

    sets = {}
    for nm, Fx, meta in [("MotionSense", Fm, mm), ("UCI_HAR", Fu, mu)]:
        sets[nm] = {s: (Fx[idx(meta, (meta.split == s).to_numpy())], meta[meta.split == s].reset_index(drop=True)) for s in ("train", "val", "test")}

    within, all_pred, chosen, fitted = {}, [], {}, {}
    # ---------------- headline: within-dataset ----------------
    for nm in ["MotionSense", "UCI_HAR"]:
        (Xtr, mtr), (Xva, mva), (Xte, mte) = sets[nm]["train"], sets[nm]["val"], sets[nm]["test"]
        ytr, yva = mtr.y.to_numpy(), mva.y.to_numpy()
        print(f"[{nm}] tuning on validation ...")
        tuned, sel = tune(Xtr, ytr, Xva, yva)
        base = DummyClassifier(strategy="most_frequent").fit(Xtr, ytr)
        # effect of class weighting, validation only
        wt_eff = {}
        for kind in ["logistic_regression", "random_forest", "xgboost"]:
            pr = tuned[kind]["best_params"]
            wt_eff[kind] = {"val_macro_f1_weighted": mf1(yva, fit(kind, pr, Xtr, ytr, True).predict(Xva)),
                            "val_macro_f1_unweighted": mf1(yva, fit(kind, pr, Xtr, ytr, False).predict(Xva))}
        res = {"selected_model_by_validation_macro_f1": sel, "tuning": tuned, "class_weighting_effect_on_validation": wt_eff,
               "n_windows": {"train": len(mtr), "val": len(mva), "test": len(mte)}, "test": {}}
        res["validation_majority_baseline_macro_f1"] = mf1(yva, base.predict(Xva))
        for kind in ["majority", "logistic_regression", "random_forest", "xgboost"]:
            pr = tuned[kind]["best_params"] if kind != "majority" else {}
            m = base if kind == "majority" else fit(kind, pr, Xtr, ytr)
            r, p = eval_block(kind, pr, m, Xte, mte, nm)  # test scored once per model
            res["test"][kind] = r
            all_pred.append(pred_rows(mte, p, f"within_{nm}", kind))
            M.save_confusion(r["confusion_matrix_counts"], f"within_{nm}_{kind}_test", CMD, f"Within-dataset {nm} test, {kind} (subject-independent)")
            if kind == sel:
                fitted[nm] = (m, pr)
        chosen[nm] = (sel, tuned[sel]["best_params"])
        within[nm] = res
        print(f"[{nm}] selected {sel}; test macro-F1 {res['test'][sel]['macro_f1']:.4f} acc {res['test'][sel]['accuracy']:.4f}")
    # ---------------- supplementary grouped CV ----------------
    cv = {}
    for nm in ["MotionSense", "UCI_HAR"]:
        kind, pr = chosen[nm]
        Xall = np.vstack([sets[nm][s][0] for s in ("train", "val", "test")]) if nm == "MotionSense" else np.vstack([sets[nm][s][0] for s in ("train", "val")])
        mall = pd.concat([sets[nm][s][1] for s in ("train", "val", "test")] if nm == "MotionSense" else [sets[nm][s][1] for s in ("train", "val")], ignore_index=True)
        y, g = mall.y.to_numpy(), mall.subject.to_numpy()
        splitter = LeaveOneGroupOut() if nm == "MotionSense" else GroupKFold(n_splits=5)
        pcv = np.zeros(len(y), dtype=int)
        for tr, te in splitter.split(Xall, y, g):
            pcv[te] = fit(kind, pr, Xall[tr], y[tr]).predict(Xall[te])
        cv[nm] = {"label": "SUPPLEMENTARY " + ("leave-one-subject-out over all 24 subjects" if nm == "MotionSense" else
                  "5-fold subject-grouped CV over the 21 provided UCI train subjects only (test subjects not used)"),
                  "model": kind, "params": pr, "hyperparameters_fixed_from_validation_tuning": True,
                  **M.metrics(y, pcv), "per_subject": M.per_subject(mall, y, pcv), "diagnostic_by_original_activity": M.diagnostic_by_original(mall, pcv)}
    jdump({"headline": True, "description": "Within-dataset subject-independent evaluation. Activity classification only; NOT trained or evaluated for GPS spoofing.",
           "seed": SEED, "datasets": within, "supplementary_grouped_cv": cv}, MET / "activity_within_dataset_metrics.json")

    # ---------------- generalisation experiments ----------------
    gen = {}
    Xms_tr, mms_tr = sets["MotionSense"]["train"]; Xu_tr, mu_tr = sets["UCI_HAR"]["train"]
    Xms_te, mms_te = sets["MotionSense"]["test"]; Xu_te, mu_te = sets["UCI_HAR"]["test"]
    Xms_all = np.vstack([sets["MotionSense"][s][0] for s in ("train", "val", "test")])
    mms_all = pd.concat([sets["MotionSense"][s][1] for s in ("train", "val", "test")], ignore_index=True)
    Xu_all = np.vstack([sets["UCI_HAR"][s][0] for s in ("train", "val", "test")])
    mu_all = pd.concat([sets["UCI_HAR"][s][1] for s in ("train", "val", "test")], ignore_index=True)

    def run(exp, kind, pr, Xtr, ytr, tests):
        m = fit(kind, pr, Xtr, ytr)
        out = {"model": kind, "params": pr, "n_train_windows": int(len(ytr)), "tests": {}}
        for tn, (Xt, mt) in tests.items():
            r, p = eval_block(kind, pr, m, Xt, mt, tn)
            out["tests"][tn] = r
            all_pred.append(pred_rows(mt, p, f"{exp}->{tn}", kind))
            M.save_confusion(r["confusion_matrix_counts"], f"gen_{exp}_to_{tn}", CMD, f"GENERALISATION {exp} -> {tn}")
        return m, out
    k, pr = chosen["MotionSense"]
    _, gen["train_MotionSense_test_UCI"] = run("MotionSense", k, pr, Xms_tr, mms_tr.y.to_numpy(),
                                               {"UCI_test": (Xu_te, mu_te), "UCI_all": (Xu_all, mu_all)})
    k, pr = chosen["UCI_HAR"]
    _, gen["train_UCI_test_MotionSense"] = run("UCI", k, pr, Xu_tr, mu_tr.y.to_numpy(),
                                               {"MotionSense_test": (Xms_te, mms_te), "MotionSense_all": (Xms_all, mms_all)})
    Xc_tr = np.vstack([Xms_tr, Xu_tr]); yc_tr = np.concatenate([mms_tr.y.to_numpy(), mu_tr.y.to_numpy()])
    Xc_va = np.vstack([sets["MotionSense"]["val"][0], sets["UCI_HAR"]["val"][0]])
    yc_va = np.concatenate([sets["MotionSense"]["val"][1].y.to_numpy(), sets["UCI_HAR"]["val"][1].y.to_numpy()])
    print("[combined] tuning on combined validation ...")
    tuned_c, sel_c = tune(Xc_tr, yc_tr, Xc_va, yc_va)
    comb_model, comb = run("Combined", sel_c, tuned_c[sel_c]["best_params"], Xc_tr, yc_tr,
                           {"MotionSense_test": (Xms_te, mms_te), "UCI_test": (Xu_te, mu_te)})
    comb.update({"selected_model_by_combined_validation_macro_f1": sel_c, "tuning": tuned_c,
                 "role": "candidate deployed activity model; trained on MotionSense train + UCI train subjects"})
    gen["combined_train_MotionSense_plus_UCI"] = comb
    # per-model combined results (all three classifiers) for transparency
    comb_all = {}
    for kind in ["logistic_regression", "random_forest", "xgboost"]:
        m = fit(kind, tuned_c[kind]["best_params"], Xc_tr, yc_tr)
        comb_all[kind] = {tn: {k2: v for k2, v in eval_block(kind, tuned_c[kind]["best_params"], m, Xt, mt, tn)[0].items()
                               if k2 in ("accuracy", "macro_f1", "weighted_f1", "per_class")} for tn, (Xt, mt) in
                          {"MotionSense_test": (Xms_te, mms_te), "UCI_test": (Xu_te, mu_te)}.items()}
    gen["combined_all_models_summary"] = comb_all
    # in-domain vs cross-domain macro-F1 summary
    summ = {"within_MotionSense_test": within["MotionSense"]["test"][chosen["MotionSense"][0]]["macro_f1"],
            "within_UCI_test": within["UCI_HAR"]["test"][chosen["UCI_HAR"][0]]["macro_f1"],
            "MotionSense_to_UCI_test": gen["train_MotionSense_test_UCI"]["tests"]["UCI_test"]["macro_f1"],
            "UCI_to_MotionSense_test": gen["train_UCI_test_MotionSense"]["tests"]["MotionSense_test"]["macro_f1"],
            "combined_on_MotionSense_test": comb["tests"]["MotionSense_test"]["macro_f1"],
            "combined_on_UCI_test": comb["tests"]["UCI_test"]["macro_f1"]}
    jdump({"headline": False, "label": "GENERALISATION EXPERIMENT (cross-dataset / combined); not the headline. Activity classification only; "
           "NOT trained or evaluated for GPS spoofing.", "seed": SEED, "macro_f1_summary": summ,
           "domain_shift_note": "MotionSense: iPhone 6s, front trouser pocket, Core Motion userAcceleration (sensor-fusion gravity removal). "
           "UCI HAR: Samsung Galaxy S II, waist, body_acc by 0.3 Hz Butterworth gravity separation after median + 20 Hz Butterworth filtering.",
           "experiments": gen}, MET / "activity_generalisation_metrics.json")

    # ---------------- predictions ----------------
    pd.concat(all_pred, ignore_index=True).to_csv(MET / "activity_test_predictions.csv", index=False)

    # ---------------- feature scale comparison (sanity, datasets only) ----------------
    idxn = {n: i for i, n in enumerate(F.FEATURE_NAMES)}
    scale = {}
    for nm, Fx, meta in [("MotionSense", Fm, mm), ("UCI_HAR", Fu, mu)]:
        scale[nm] = {}
        for c in CLS:
            msk = (meta.class_name == c).to_numpy()
            scale[nm][c] = {f: {q: float(np.percentile(Fx[msk, idxn[f]], v)) for q, v in (("p10", 10), ("median", 50), ("p90", 90))}
                            for f in ("acc_mag_mean", "acc_mag_std", "gyro_mag_mean", "acc_dominant_freq_hz")}
    jdump({"description": "Distribution of window-level features per dataset and class (all windows). Scale sanity only; the Dryad Phase 1 motion.csv was NOT used.",
           "quantiles": scale}, MET / "activity_feature_scale_comparison.json")
    fig, ax = plt.subplots(1, 3, figsize=(12, 3.8))
    for a, f in zip(ax, ["acc_mag_mean", "acc_mag_std", "gyro_mag_mean"]):
        data, lab = [], []
        for c in CLS:
            for nm, Fx, meta in [("MotionSense", Fm, mm), ("UCI_HAR", Fu, mu)]:
                data.append(Fx[(meta.class_name == c).to_numpy(), idxn[f]]); lab.append(f"{c[:4]}\n{nm[:2]}")
        a.boxplot(data, tick_labels=lab, showfliers=False); a.set_title(f); a.tick_params(axis="x", labelsize=7)
        if f != "acc_mag_mean":
            a.set_yscale("symlog", linthresh=0.01)
    fig.suptitle("Window feature distributions by class: MotionSense (Mo) vs UCI HAR (UC)"); fig.tight_layout()
    fig.savefig(PLT / "activity_feature_scale_by_dataset.png", dpi=120); plt.close(fig)
    # class balance plot
    fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
    for a, nm in zip(ax, ["MotionSense", "UCI_HAR"]):
        b = bal[nm]["windows_by_class"]; bottom = np.zeros(3)
        for i, c in enumerate(CLS):
            vals = np.array([b[s][c] for s in ("train", "val", "test")]); a.bar(["train", "val", "test"], vals, bottom=bottom, label=c); bottom += vals
        a.set_title(f"{nm} windows by class"); a.legend(fontsize=7)
    fig.tight_layout(); fig.savefig(PLT / "activity_class_balance.png", dpi=120); plt.close(fig)
    # model comparison plot (test macro-F1, within-dataset)
    fig, ax = plt.subplots(figsize=(6.5, 3.6)); w = 0.35
    kinds = ["majority", "logistic_regression", "random_forest", "xgboost"]
    for j, nm in enumerate(["MotionSense", "UCI_HAR"]):
        ax.bar(np.arange(4) + j * w, [within[nm]["test"][k]["macro_f1"] for k in kinds], w, label=nm)
    ax.set_xticks(np.arange(4) + w / 2); ax.set_xticklabels(["majority", "log.reg.", "RF", "XGB"]); ax.set_ylabel("test macro-F1")
    ax.set_title("Within-dataset subject-independent test macro-F1"); ax.legend(); fig.tight_layout()
    fig.savefig(PLT / "activity_within_dataset_macro_f1.png", dpi=120); plt.close(fig)
    # generalisation plot
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.bar(range(len(summ)), list(summ.values())); ax.set_xticks(range(len(summ))); ax.set_xticklabels([k.replace("_", "\n") for k in summ], fontsize=6)
    ax.set_ylabel("test macro-F1"); ax.set_title("Generalisation experiment (cross-dataset) vs within-dataset"); fig.tight_layout()
    fig.savefig(PLT / "activity_generalisation_macro_f1.png", dpi=120); plt.close(fig)
    # combined model feature importance
    imp = getattr(comb_model, "feature_importances_", None)
    if imp is not None:
        fig, ax = plt.subplots(figsize=(6, 4)); o = np.argsort(imp)
        ax.barh(np.array(F.FEATURE_NAMES)[o], imp[o]); ax.set_title(f"Combined model ({sel_c}) feature importance"); fig.tight_layout()
        fig.savefig(PLT / "activity_combined_feature_importance.png", dpi=120); plt.close(fig)

    # ---------------- save models ----------------
    saved = []
    def save(model, name, kind):
        joblib.dump(model, MODELS_DIR / f"{name}.joblib"); saved.append(f"{name}.joblib")
        if kind == "xgboost":
            model.get_booster().save_model(str(MODELS_DIR / f"{name}.json")); saved.append(f"{name}.json")
    for nm, key in [("MotionSense", "motionsense"), ("UCI_HAR", "uci")]:
        save(fitted[nm][0], f"activity_{key}_{chosen[nm][0]}", chosen[nm][0])
    save(comb_model, f"activity_combined_{sel_c}", sel_c)
    cfg = {"purpose": "Physical-activity classifier (WALKING/STATIONARY/OTHER). Not trained or evaluated on GPS spoofing.",
           "seed": SEED, "class_codes": {c: i for i, c in enumerate(CLS)}, "label_map": {"MotionSense": D.MS_LABEL_MAP, "UCI_HAR": D.UCI_LABEL_MAP},
           "window": {"samples": 128, "fs_hz": 50, "stride_motionsense": 64}, "feature_list": F.FEATURE_NAMES,
           "peak_params": {"prominence_g": F.PEAK_PROMINENCE_G, "distance_samples": F.PEAK_DISTANCE},
           "splits": {"motionsense": ms_sets, "uci_har": uci_sets},
           "selected": {"MotionSense": {"model": chosen["MotionSense"][0], "params": chosen["MotionSense"][1]},
                        "UCI_HAR": {"model": chosen["UCI_HAR"][0], "params": chosen["UCI_HAR"][1]},
                        "Combined": {"model": sel_c, "params": tuned_c[sel_c]["best_params"]}},
           "imbalance_handling": "class_weight='balanced' (RF, logistic regression) / balanced sample_weight (XGBoost); no resampling",
           "grids": GRIDS, "rf_n_estimators": 300, "saved_models": saved,
           "models_trained_on": {"activity_motionsense_*": "MotionSense train subjects", "activity_uci_*": "UCI train subjects (minus validation)",
                                 "activity_combined_*": "MotionSense train + UCI train subjects"},
           "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": scipy.__version__,
                        "scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__, "joblib": joblib.__version__,
                        "matplotlib": matplotlib.__version__}}
    jdump(cfg, MODELS_DIR / "activity_training_config.json")
    print("done")


if __name__ == "__main__":
    main()
