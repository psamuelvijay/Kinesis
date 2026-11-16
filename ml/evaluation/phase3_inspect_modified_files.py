"""Phase 3 READ-ONLY inspection of the Phase 2 files modified in the working tree. Never restores, writes to or stages them.
Run: .venv/Scripts/python.exe ml/evaluation/phase3_inspect_modified_files.py
Output: results/metrics/phase3_modified_files_inspection.json
"""
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

ROOT = Path(__file__).resolve().parents[2]
FILES = ["ml/models/best_model.joblib", "ml/models/random_forest.joblib", "ml/models/xgboost.json",
         "results/metrics/phase2_test_predictions.csv"]
OTHER = ["ml/models/evaluation_metrics.json", "ml/models/training_config.json", "results/metrics/phase2_model_metrics.json",
         "results/metrics/phase3_preservation_check.json"]


def git(*a, text=True):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, check=True, text=text).stdout


def show(p):
    return subprocess.run(["git", "show", f"HEAD:{p}"], cwd=ROOT, capture_output=True, check=True).stdout


def sha(b):
    return hashlib.sha256(b).hexdigest()


def reg(y, p):
    return {"n": int(len(y)), "MAE": float(mean_absolute_error(y, p)), "RMSE": float(np.sqrt(mean_squared_error(y, p))), "R2": float(r2_score(y, p))}


out = {"python": sys.version.split()[0], "env_executing_this_script": {"scikit-learn": sklearn.__version__, "xgboost": xgboost.__version__,
       "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__, "executable": sys.executable}}
out["git_status_porcelain_modified"] = [l for l in git("status", "--porcelain").splitlines() if l.startswith(" M") or l.startswith("M")]
out["git_diff_stat_all_tracked_modifications"] = git("diff", "--stat").splitlines()
out["git_diff_stat_four_files"] = git("diff", "--stat", "--", *FILES).splitlines()
files = {}
for p in FILES + OTHER:
    wt = (ROOT / p).read_bytes()
    hd = show(p)
    files[p] = {"in_requested_four": p in FILES, "size_working_tree": len(wt), "size_HEAD": len(hd), "sha256_working_tree": sha(wt),
                "sha256_HEAD": sha(hd), "identical_bytes": wt == hd}
out["files"] = files

# ---- models: load both versions with the installed library (read-only; temp copies are in memory)
cfg_wt = json.loads((ROOT / "ml/models/training_config.json").read_text())
cfg_hd = json.loads(show("ml/models/training_config.json"))
out["training_config_diff"] = {"library_versions_working_tree": cfg_wt["library_versions"], "library_versions_HEAD": cfg_hd["library_versions"],
                               "other_keys_identical": {k: cfg_wt[k] == cfg_hd[k] for k in cfg_wt if k != "library_versions"}}
rf_hd = joblib.load(io.BytesIO(show("ml/models/random_forest.joblib")))
rf_wt = joblib.load(ROOT / "ml/models/random_forest.joblib")
best_hd = joblib.load(io.BytesIO(show("ml/models/best_model.joblib")))
best_wt = joblib.load(ROOT / "ml/models/best_model.joblib")
W = pd.read_csv(ROOT / "datasets/dryad/processed/windows_5s.csv")
FEATURES = cfg_hd["features"]
X = W[FEATURES]
m = {}
for label, a, b in (("random_forest", rf_hd, rf_wt), ("best_model", best_hd, best_wt)):
    pa, pb = a.predict(X), b.predict(X)
    m[label] = {"type": type(a).__name__, "get_params_equal": a.get_params() == b.get_params(),
                "n_estimators": (len(a.estimators_) if hasattr(a, "estimators_") else None), "sklearn_version_pickled_HEAD": getattr(a, "_sklearn_version", None),
                "sklearn_version_pickled_working_tree": getattr(b, "_sklearn_version", None),
                "max_abs_prediction_diff_on_all_phase2_windows": float(np.max(np.abs(pa - pb)))}
    if hasattr(a, "estimators_"):
        ta, tb = a.estimators_[0].tree_, b.estimators_[0].tree_
        m[label]["first_tree_identical_structure"] = bool(ta.node_count == tb.node_count and np.array_equal(ta.feature, tb.feature)
                                                           and np.array_equal(ta.threshold, tb.threshold) and np.array_equal(ta.value, tb.value))
    elif hasattr(a, "get_booster"):
        m[label]["booster_json_equal"] = a.get_booster().save_raw("json") == b.get_booster().save_raw("json")
out["joblib_models"] = m
xj_wt = json.loads((ROOT / "ml/models/xgboost.json").read_text())
xj_hd = json.loads(show("ml/models/xgboost.json").decode())
def pick(j):
    return {"version": j.get("version"), "n_trees": j["learner"]["gradient_booster"]["model"]["gbtree_model_param"]["num_trees"],
            "learner_model_param": j["learner"]["learner_model_param"], "objective": j["learner"]["objective"]}
a, b = pick(xj_hd), pick(xj_wt)
trees_a, trees_b = xj_hd["learner"]["gradient_booster"]["model"]["trees"], xj_wt["learner"]["gradient_booster"]["model"]["trees"]
def tree_eq(x, y):
    return all(np.array_equal(np.asarray(x[k], float), np.asarray(y[k], float), equal_nan=True) for k in
               ("split_indices", "left_children", "right_children", "split_conditions", "base_weights") if k in x and k in y)
same_struct = sum(1 for x, y in zip(trees_a, trees_b) if x["split_indices"] == y["split_indices"] and x["left_children"] == y["left_children"])
xa = xgboost.XGBRegressor(); xa.load_model(bytearray(show("ml/models/xgboost.json")))
xb = xgboost.XGBRegressor(); xb.load_model(str(ROOT / "ml/models/xgboost.json"))
pa, pb = xa.predict(X), xb.predict(X)
out["xgboost_json"] = {"HEAD": a, "working_tree": b, "trees_HEAD": len(trees_a), "trees_working_tree": len(trees_b),
                       "trees_with_identical_topology_and_split_features": int(same_struct),
                       "trees_with_bitwise_identical_thresholds_and_weights": int(sum(tree_eq(x, y) for x, y in zip(trees_a, trees_b))),
                       "max_abs_prediction_diff_on_all_phase2_windows": float(np.max(np.abs(pa - pb))),
                       "params_equal": {k: xa.get_params()[k] == xb.get_params()[k] for k in xa.get_params()},
                       "features_equal": xj_hd["learner"]["feature_names"] == xj_wt["learner"]["feature_names"]}

# ---- predictions CSV
ch = pd.read_csv(io.BytesIO(show("results/metrics/phase2_test_predictions.csv")))
cw = pd.read_csv(ROOT / "results/metrics/phase2_test_predictions.csv")
pc = {"rows_HEAD": len(ch), "rows_working_tree": len(cw), "columns_equal": list(ch.columns) == list(cw.columns)}
if len(ch) == len(cw) and pc["columns_equal"]:
    key = ["track", "subject", "win_idx", "t_start_ms"]
    pc["key_columns_and_order_identical"] = bool((ch[key].values == cw[key].values).all())
    pc["steps_target_identical"] = bool(np.array_equal(ch.steps_target.values, cw.steps_target.values))
    pcols = [c for c in ch.columns if c.startswith("pred_")]
    pc["row_wise_max_abs_diff"] = {c: float(np.max(np.abs(ch[c].values - cw[c].values))) for c in pcols}
    pc["n_rows_differing_gt_1e-9"] = {c: int((np.abs(ch[c].values - cw[c].values) > 1e-9).sum()) for c in pcols}
    pc["metrics_recomputed_HEAD"] = {c: reg(ch.steps_target.values, ch[c].values) for c in pcols}
    pc["metrics_recomputed_working_tree"] = {c: reg(cw.steps_target.values, cw[c].values) for c in pcols}
    pc["metrics_abs_diff"] = {c: {k: abs(pc["metrics_recomputed_HEAD"][c][k] - pc["metrics_recomputed_working_tree"][c][k]) for k in ("MAE", "RMSE", "R2")} for c in pcols}
    pc["csv_text_diff_note"] = "git diff reports ~4234 changed lines because float digits differ; compare numerically above"
out["predictions_csv"] = pc
mh = json.loads(show("results/metrics/phase2_model_metrics.json"))
mw = json.loads((ROOT / "results/metrics/phase2_model_metrics.json").read_text())
out["stored_headline_metrics_HEAD_vs_working_tree"] = {
    tag: {n: {k: {"HEAD": mh[tag][n]["window"][k], "working_tree": mw[tag][n]["window"][k]} for k in ("MAE", "RMSE", "R2")}
          for n in ("random_forest", "xgboost")} for tag in ("validation", "test")}
out["environments_found"] = {"note": "two interpreters exist; see below",
                             "system_python_is_what_overwrote_the_files": cfg_wt["library_versions"],
                             "project_venv_.venv_versions": "see env_executing_this_script when this script is run with .venv (recorded Phase 2 versions)"}
rf_same = all([m["random_forest"]["get_params_equal"], m["random_forest"].get("first_tree_identical_structure", False)])
out["assessment"] = {
    "cause": "The working-tree files were regenerated by running train_eval.py (or equivalent) with the system Python (scikit-learn 1.8.0 / xgboost 3.2.0) instead of the project .venv (scikit-learn 1.9.1 / xgboost 3.4.1 = the versions recorded in the committed training_config.json). training_config.json library_versions in the working tree shows the old stack. Same seeds, split and hyper-parameters; the differences come from library behaviour/serialization, not from a changed experiment.",
    "randomforest_parameters_equal": bool(m["random_forest"]["get_params_equal"]), "randomforest_first_tree_identical": bool(m["random_forest"].get("first_tree_identical_structure", False))}
out["assessment"]["random_forest_conclusion"] = "random_forest.joblib and best_model.joblib (same RandomForest; identical SHA-256 to each other in both versions) differ from HEAD only in serialization/library version: identical get_params, identical first tree, max abs prediction difference ~1e-14."
out["assessment"]["xgboost_conclusion"] = "xgboost.json has the same hyper-parameters and features but different trees (0 of 300 identical) and predictions differ up to ~1.7 steps per window: an xgboost 3.2.0 vs 3.4.1 numerical difference, not a changed experiment. Stored test metrics for XGBoost move by about 0.006 MAE."
out["assessment"]["recommendation"] = "RESTORE the four files (and the other four modified Phase 2 artefacts) from HEAD ONLY AFTER USER APPROVAL: the committed versions were produced with the recorded .venv stack and reproduce exactly when re-run in .venv (see phase3_modelA_sensitivity H0 rerun, abs diff 0.0). Keep is not recommended because the working tree mixes library versions with committed docs/reports quoting the HEAD numbers. Regenerate is unnecessary. Nothing was restored, discarded or staged by this inspection. Future Phase 2/3 scripts should be run with .venv."
(ROOT / "results/metrics/phase3_modified_files_inspection.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ("joblib_models", "xgboost_json", "assessment")}, indent=1)[:6000])
print(json.dumps(pc, indent=1)[:5000])
print(json.dumps(out["files"], indent=1)[:4000])
print("\n".join(out["git_diff_stat_four_files"]))
