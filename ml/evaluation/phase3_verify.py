"""Phase 3 verification. Reruns the Model B pipeline twice, checks leakage / mapping / features,
raw dataset hashes, preservation hashes, and report-vs-JSON numbers.
Usage: python ml/evaluation/phase3_verify.py rerun   -> reruns pipeline twice, writes rerun section
       python ml/evaluation/phase3_verify.py checks  -> all other checks, writes phase3_verification.json
"""
import hashlib, json, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
M = ROOT / "results" / "metrics"
OUT = M / "phase3_verification.json"
OUTPUTS = [
    "results/metrics/activity_within_dataset_metrics.json",
    "results/metrics/activity_generalisation_metrics.json",
    "results/metrics/activity_test_predictions.csv",
    "results/metrics/activity_splits.json",
    "results/metrics/activity_preparation_report.json",
    "results/metrics/activity_feature_scale_comparison.json",
    "ml/models/activity_feature_list.json",
    "ml/models/activity_combined_xgboost.json",
    "ml/models/activity_motionsense_xgboost.json",
    "ml/models/activity_uci_xgboost.json",
]


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def hashes():
    return {o: sha(ROOT / o) for o in OUTPUTS}


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else {"checks": {}}


def rerun():
    res = load()
    snaps = {"existing_before_rerun": hashes()}
    for i in (1, 2):
        r = subprocess.run([sys.executable, "ml/activity_classifier/run_pipeline.py"], cwd=ROOT,
                           capture_output=True, text=True)
        snaps[f"run{i}_returncode"] = r.returncode
        snaps[f"run{i}"] = hashes()
    s = snaps
    res["checks"]["model_b_rerun_identical"] = {
        "run1_returncode": s["run1_returncode"], "run2_returncode": s["run2_returncode"],
        "run1_equals_run2": s["run1"] == s["run2"],
        "run1_equals_outputs_existing_before_rerun": s["run1"] == s["existing_before_rerun"],
        "differing_files_run1_vs_run2": [k for k in s["run1"] if s["run1"][k] != s["run2"][k]],
        "differing_files_vs_existing": [k for k in s["run1"] if s["run1"][k] != s["existing_before_rerun"][k]],
        "sha256_run2": s["run2"], "python": sys.executable,
        "passed": s["run1_returncode"] == 0 and s["run2_returncode"] == 0 and s["run1"] == s["run2"],
    }
    OUT.write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v for k, v in res["checks"]["model_b_rerun_identical"].items() if k != "sha256_run2"}, indent=1))


def checks():
    res = load()
    c = res["checks"]
    sp = json.loads((M / "activity_splits.json").read_text())
    # leakage
    leak = {}
    for ds in ("motionsense", "uci_har"):
        s = sp[ds]["split"]
        leak[ds] = {"train&val": sorted(set(s["train"]) & set(s["val"])),
                    "train&test": sorted(set(s["train"]) & set(s["test"])),
                    "val&test": sorted(set(s["val"]) & set(s["test"]))}
    c["zero_subject_leakage"] = {"overlaps": leak, "passed": all(not v for d in leak.values() for v in d.values())}
    # label map
    cfg = json.loads((ROOT / "ml/models/activity_training_config.json").read_text())
    lm = cfg["label_map"]
    bad = {ds: [k for k, v in m.items() if v == "STATIONARY" and k in ("jog", "ups", "dws", "WALKING_UPSTAIRS", "WALKING_DOWNSTAIRS", "WALKING")]
           for ds, m in lm.items()}
    stat = {ds: sorted(k for k, v in m.items() if v == "STATIONARY") for ds, m in lm.items()}
    c["no_jog_stairs_mapped_to_stationary"] = {"stationary_sources": stat, "violations": bad,
                                               "passed": all(not v for v in bad.values())}
    # model predictions (diagnostic, not a mapping check)
    w = json.loads((M / "activity_within_dataset_metrics.json").read_text())
    diag = {}
    for ds, jog_stairs in (("MotionSense", ("jog", "ups", "dws")), ("UCI_HAR", ("ups", "dws"))):
        d = w["datasets"][ds]["test"]["xgboost"]["diagnostic_by_original_activity"]
        diag[ds] = {"jog_stairs_windows": sum(d[a]["n"] for a in jog_stairs),
                    "predicted_STATIONARY": sum(d[a]["pred_STATIONARY"] for a in jog_stairs)}
    c["jog_stairs_predicted_stationary_diagnostic"] = {"selected_xgboost_test": diag,
                                                      "note": "model errors, not label mapping; informational"}
    # features
    fl = json.loads((ROOT / "ml/models/activity_feature_list.json").read_text())
    names = fl if isinstance(fl, list) else fl.get("features", fl.get("feature_list", []))
    forb = re.compile(r"gps|speed|lat|lon|step|distance|heading|altitude|conf|displacement|path", re.I)
    hits = [n for n in names if forb.search(n)]
    c["no_gps_or_step_features_in_model_b"] = {"n_features": len(names), "features": names,
                                               "forbidden_name_hits": hits, "passed": len(names) == 11 and not hits}
    # raw hashes
    pres = json.loads((M / "phase3_preservation_check.json").read_text())
    before = pres["before"]["sha256"]
    raw = [p for p in (ROOT / "datasets").rglob("*.zip") if "raw" in p.parts]
    rawres = {}
    for p in raw:
        rel = p.relative_to(ROOT).as_posix()
        rawres[rel] = {"before_in_snapshot": rel in before,
                       "equal": (rel in before and before[rel] == sha(p))}
    c["raw_dataset_hashes_unchanged"] = {"files": rawres,
        "passed": bool(rawres) and all(v["equal"] for v in rawres.values())}
    OUT.write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v.get("passed", None) for k, v in c.items()}, indent=1))



def report_and_preservation():
    res = load()
    c = res["checks"]
    rep = (ROOT / "results" / "phase3_report.md").read_text(encoding="utf-8")
    w = json.loads((M / "activity_within_dataset_metrics.json").read_text())
    g = json.loads((M / "activity_generalisation_metrics.json").read_text())
    exp = []
    for ds in ("MotionSense", "UCI_HAR"):
        for mdl in ("majority", "logistic_regression", "random_forest", "xgboost"):
            t = w["datasets"][ds]["test"][mdl]
            for k in ("accuracy", "macro_f1", "weighted_f1"):
                exp.append((f"{ds}.{mdl}.{k}", f"{t[k]:.4f}"))
        cm = w["datasets"][ds]["test"]["xgboost"]["confusion_matrix_counts"]
        exp.append((f"{ds}.xgb.cm", json.dumps(cm, separators=(",", ":"))))
    for ds in ("MotionSense", "UCI_HAR"):
        cv = w["supplementary_grouped_cv"][ds]
        exp += [(f"cv.{ds}.acc", f"{cv['accuracy']:.4f}"), (f"cv.{ds}.f1", f"{cv['macro_f1']:.4f}")]
    ex = g["experiments"]
    for name, exp_k, tk in (("MS_to_UCI_test", "train_MotionSense_test_UCI", "UCI_test"), ("MS_to_UCI_all", "train_MotionSense_test_UCI", "UCI_all"),
                            ("UCI_to_MS_test", "train_UCI_test_MotionSense", "MotionSense_test"), ("UCI_to_MS_all", "train_UCI_test_MotionSense", "MotionSense_all"),
                            ("comb_MS", "combined_train_MotionSense_plus_UCI", "MotionSense_test"), ("comb_UCI", "combined_train_MotionSense_plus_UCI", "UCI_test")):
        t = ex[exp_k]["tests"][tk]
        exp += [(f"{name}.acc", f"{t['accuracy']:.4f}"), (f"{name}.f1", f"{t['macro_f1']:.4f}")]
    # error analysis counts
    for ds in ("MotionSense", "UCI_HAR"):
        d = w["datasets"][ds]["test"]["xgboost"]["diagnostic_by_original_activity"]
        for a, v in d.items():
            exp.append((f"{ds}.{a}.row", f"{v['pred_WALKING']} / {v['pred_STATIONARY']} / {v['pred_OTHER']} (n={v['n']})"))
    # model A
    sens = json.loads((M / "phase3_modelA_sensitivity" / "alignment_sensitivity_fixed_params.json").read_text())
    an = json.loads((M / "phase3_modelA_anomaly_exclusion.json").read_text())
    prep = json.loads((M / "activity_preparation_report.json").read_text())
    exp += [("ms.windows", f"{prep['motionsense']['n_windows']:,}"), ("uci.windows", f"{prep['uci_har']['n_windows']:,}"),
            ("ms.rows", f"{prep['motionsense']['rows_total']:,}")]
    for sp in ("evaluation_only_exclusion",):
        t = an[sp]["test"]["excluded_flagged_tracks"]
        exp += [("anom.eval_only.rf", f"{t['random_forest']['MAE']:.4f}"), ("anom.eval_only.xgb", f"{t['xgboost']['MAE']:.4f}")]
    t = an["training_and_evaluation_exclusion"]["test"]
    exp += [("anom.train_eval.rf", f"{t['random_forest']['MAE']:.4f}"), ("anom.train_eval.xgb", f"{t['xgboost']['MAE']:.4f}")]
    cond = sens["conditions"]
    missing = [(k, v) for k, v in exp if v not in rep]
    c["report_numbers_match_json"] = {"n_values_checked": len(exp), "not_found_in_report": missing,
                                      "note": "each expected string is generated from the JSON files and searched in results/phase3_report.md",
                                      "passed": not missing}
    # git HEAD hash check of the four restored files
    four = ["ml/models/best_model.joblib", "ml/models/random_forest.joblib", "ml/models/xgboost.json", "results/metrics/phase2_test_predictions.csv"]
    gh = {}
    for f in four:
        blob = subprocess.run(["git", "show", f"HEAD:{f}"], cwd=ROOT, capture_output=True).stdout
        gh[f] = {"head_sha256": hashlib.sha256(blob).hexdigest(), "worktree_sha256": sha(ROOT / f)}
        wt = (ROOT / f).read_bytes()
        gh[f]["equal_bytes"] = gh[f]["head_sha256"] == gh[f]["worktree_sha256"]
        gh[f]["equal_after_CRLF_to_LF"] = hashlib.sha256(wt.replace(b"\r\n", b"\n")).hexdigest() == gh[f]["head_sha256"]
        gh[f]["equal"] = gh[f]["equal_bytes"] or gh[f]["equal_after_CRLF_to_LF"]
    c["four_phase2_files_vs_git_HEAD"] = {"files": gh, "passed": all(v["equal"] for v in gh.values()),
        "note": "informational: shows whether the four files currently equal HEAD (restored by an earlier step)"}
    # preservation compare
    r = subprocess.run([sys.executable, "ml/evaluation/preservation_hash.py", "compare"], cwd=ROOT, capture_output=True, text=True)
    pres = json.loads((M / "phase3_preservation_check.json").read_text())
    cmp_ = pres["comparison"]
    before = pres["before"]["sha256"]
    groups = {"docs_pptx_pdf_md": [k for k in before if k.startswith("docs/")],
              "agents_dir": [k for k in before if k.startswith(".agents/")],
              "four_modified_phase2_files": four}
    summ = {n: {"n": len(ks), "changed_or_missing": [k for k in ks if k in cmp_["changed_or_missing"]]} for n, ks in groups.items()}
    c["preservation_byte_identical_to_before"] = {
        "compare_exit_code": r.returncode, "summary_by_group": summ,
        "changed_or_missing": cmp_["changed_or_missing"], "added_files_count": len(cmp_["added"]),
        "added_files": cmp_["added"],
        "strict_identical_including_approved_exception": cmp_["identical"],
        "approved_exception": {"files": four, "expected_state": "equals git HEAD", "all_equal_HEAD": c["four_phase2_files_vs_git_HEAD"]["passed"]},
        "added_files_all_phase3_modelA_sensitivity_outputs": all("phase3_modelA_sensitivity" in a for a in cmp_["added"]),
        "passed": (set(cmp_["changed_or_missing"]) <= set(four)) and c["four_phase2_files_vs_git_HEAD"]["passed"]
                  and not summ["docs_pptx_pdf_md"]["changed_or_missing"] and not summ["agents_dir"]["changed_or_missing"]
                  and all("phase3_modelA_sensitivity" in a for a in cmp_["added"]),
        "explanation": "Restoring exactly these four files from HEAD was approved_by_user=true (user chat message answering the modela-followups approval request, confirmed by the orchestrator). Expected state = equals HEAD. docs/ and .agents/ must be byte-identical, every other file unchanged vs its before-hash. Added files are new Model A sensitivity window CSVs (Phase 3 outputs).",
    }
    OUT.write_text(json.dumps(res, indent=2))
    print(json.dumps({k: v.get("passed", None) for k, v in c.items()}, indent=1))
    print(missing, summ)
if __name__ == "__main__":
    {"rerun": rerun, "checks": checks, "final": report_and_preservation}[sys.argv[1]]()


