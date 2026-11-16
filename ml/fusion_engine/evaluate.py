"""Phase 4 work item 3: evaluation of the frozen fusion engine on HELD-OUT Dryad subjects (genuine walking only).
Loads ml/fusion_engine/thresholds.json read-only after verifying its SHA-256 against results/metrics/phase4_thresholds_hash.json.
Contains no code that computes or changes thresholds. Dryad has no spoofing, so NO spoofing detection rate is computed or reported:
every SUSPICIOUS window here is a false positive on genuine walking.
Outputs: results/metrics/phase4_dryad_eval.json, results/metrics/phase4_dryad_heldout_windows.csv
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import engine  # noqa: E402

WIN_S = 5.0
FIELDS = ["gps_speed_mps", "gps_displacement_m", "gps_covered_s", "gps_coverage_frac", "gps_path_m", "gps_conf_m",
          "imu_n_windows", "p_stationary", "p_walking", "p_other", "physical_steps"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def frac(states, denom=None):
    n = len(states) if denom is None else denom
    return {s: (sum(1 for x in states if x == s) / n if n else None) for s in engine.STATES}


def counts(states):
    return {s: int(sum(1 for x in states if x == s)) for s in engine.STATES}


def summarise(df, hours):
    raw, rep = list(df["state"]), list(df["reported_state"])
    ev = [s for s in raw if s != "INSUFFICIENT_DATA"]
    eps = 0
    for _, g in df.groupby("track"):
        s = list(g.sort_values("win_idx").reported_state)
        eps += sum(1 for i, x in enumerate(s) if x == "SUSPICIOUS_GPS_MOVEMENT" and (i == 0 or s[i - 1] != "SUSPICIOUS_GPS_MOVEMENT"))
    return {"n_windows": int(len(df)), "n_tracks": int(df.track.nunique()), "walking_hours": hours,
            "raw_counts": counts(raw), "raw_fraction_of_all_windows": frac(raw),
            "n_evaluable_windows_excluding_INSUFFICIENT_DATA": len(ev), "raw_fraction_of_evaluable_windows": frac(ev) if ev else None,
            "reported_counts_after_persistence": counts(rep), "reported_fraction_of_all_windows": frac(rep),
            "false_suspicious_raw_windows": counts(raw)["SUSPICIOUS_GPS_MOVEMENT"],
            "false_suspicious_raw_fraction_of_all_windows": counts(raw)["SUSPICIOUS_GPS_MOVEMENT"] / len(df) if len(df) else None,
            "false_suspicious_reported_windows": counts(rep)["SUSPICIOUS_GPS_MOVEMENT"],
            "false_suspicious_reported_fraction_of_all_windows": counts(rep)["SUSPICIOUS_GPS_MOVEMENT"] / len(df) if len(df) else None,
            "false_suspicious_reported_episodes": int(eps), "false_suspicious_reported_episodes_per_walking_hour": eps / hours if hours else None}


def main():
    h = json.loads((ROOT / "results/metrics/phase4_thresholds_hash.json").read_text())
    assert sha(ROOT / "ml/fusion_engine/thresholds.json") == h["thresholds_json_sha256"], "thresholds.json changed after freeze"
    assert sha(ROOT / "ml/fusion_engine/split.json") == h["split_json_sha256"], "split.json changed after freeze"
    assert sha(ROOT / "ml/fusion_engine/engine.py") == h["engine_py_sha256"], "engine.py changed after freeze"
    th, tdoc = engine.load_thresholds(ROOT / "ml/fusion_engine/thresholds.json")
    split = json.loads((ROOT / "ml/fusion_engine/split.json").read_text())
    assert not set(split["calibration_subjects"]) & set(split["heldout_subjects"])
    S = pd.read_csv(ROOT / "results/metrics/phase4_fusion_signals.csv")
    Hd = S[S.subject.isin(split["heldout_subjects"])].copy()
    assert not set(Hd.subject.unique()) & set(split["calibration_subjects"])
    Hd = Hd.sort_values(["track", "win_idx"]).reset_index(drop=True)

    out_rows = []
    for tr, g in Hd.groupby("track", sort=True):
        inputs = [{k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in r.items()} for r in g[FIELDS].to_dict("records")]
        res = engine.run_sequence(inputs, th)
        for (_, row), r in zip(g.iterrows(), res):
            out_rows.append({"track": tr, "subject": int(row.subject), "os": row.os, "speed_bin": row.speed_bin, "win_idx": int(row.win_idx),
                             "state": r["state"], "reason": r["reason"], "reported_state": r["reported_state"],
                             "gps_speed_mps": row.gps_speed_mps, "p_stationary": row.p_stationary, "p_walking": row.p_walking, "physical_steps": row.physical_steps,
                             "model_a_steps": row.model_a_steps, "distance_anomaly": row.distance_anomaly,
                             "explanation": json.dumps(r["explanation"], sort_keys=True) if "explanation" in r else ""})
    R = pd.DataFrame(out_rows)
    R.to_csv(ROOT / "results/metrics/phase4_dryad_heldout_windows.csv", index=False)
    hours_of = lambda d: len(d) * WIN_S / 3600.0  # noqa: E731

    ev = {"scope": "Genuine Dryad walking, held-out subjects only. Dryad has no spoofing: no detection rate is reported. Fusion is a consistency detector, not a spoofing classifier; "
                   "Model B is an activity classifier not trained on spoofing. Any SUSPICIOUS window below is a false positive.",
          "thresholds_sha256": h["thresholds_json_sha256"], "split_sha256": h["split_json_sha256"], "engine_sha256": h["engine_py_sha256"],
          "signals_sha256": sha(ROOT / "results/metrics/phase4_fusion_signals.csv"),
          "persistence_N": th["PERSISTENCE_N"], "heldout_subjects": split["heldout_subjects"],
          "provisional_thresholds": tdoc["provisional_thresholds"],
          "overall": summarise(R, hours_of(R)),
          "overall_excluding_phase2_distance_anomaly_tracks": summarise(R[~R.distance_anomaly.astype(bool)], hours_of(R[~R.distance_anomaly.astype(bool)])),
          "per_subject": {str(s): summarise(g, hours_of(g)) for s, g in R.groupby("subject")},
          "per_os": {k: summarise(g, hours_of(g)) for k, g in R.groupby("os")},
          "per_speed_range_mps_track_average": {k: summarise(g, hours_of(g)) for k, g in R.groupby("speed_bin")}}
    # ---- UNCERTAIN / INSUFFICIENT reasons ----
    rs = R.copy()
    rs["reason_group"] = rs.reason.str.replace(r"^missing:.*", "missing_input(gps window excluded by Phase 2, single GPS fix so no displacement, or no Model B window)", regex=True)
    ev["reasons_by_state"] = {st: {k: int(v) for k, v in g.reason_group.value_counts().sort_index().items()} for st, g in rs.groupby("state")}
    # Phase 2 GPS window exclusions for the held-out tracks
    c2 = json.loads((ROOT / "results/metrics/phase2_cleaning_report.json").read_text())["per_track"]
    tr_set = set(R.track.unique())
    agg = {"long_gap_overlap": 0, "no_fix": 0, "no_valid_speed": 0}
    for t in c2:
        if t["track"] in tr_set:
            for k in agg:
                agg[k] += t["win_excl"][k]
    ev["windows_excluded"] = {
        "generated_decision_windows": int(len(R)), "gps_window_absent_phase2_exclusion": int((~Hd.gps_present).sum()),
        "phase2_exclusion_reasons_for_heldout_tracks": agg,
        "no_model_b_window": int((Hd.imu_n_windows < 1).sum()),
        "INSUFFICIENT_DATA_total": int((R.state == "INSUFFICIENT_DATA").sum()),
        "note": "Excluded windows stay in the denominator ('raw_fraction_of_all_windows'); a second denominator excludes INSUFFICIENT_DATA."}
    # ---- time to decision ----
    def first(g, cond):
        s = list(g.sort_values("win_idx").reported_state)
        for i, x in enumerate(s):
            if cond(x):
                return (i + 1) * WIN_S
        return None
    ttd = {}
    for name, cond in (("first_reported_GENUINE_WALKING", lambda x: x == "GENUINE_WALKING"), ("first_reported_decisive_state", lambda x: x in engine.DECISIVE)):
        v = [first(g, cond) for _, g in R.groupby("track")]
        got = [x for x in v if x is not None]
        ttd[name] = {"tracks": len(v), "tracks_never": len(v) - len(got),
                     "seconds_quantiles": {f"p{int(q * 100):02d}": float(np.quantile(got, q)) for q in (0.1, 0.5, 0.9)} if got else None}
    ev["time_to_decision_s"] = {"definition": "seconds from the start of the walk (first decision window) to the END of the first window whose reported (post-persistence) state matches; "
                                             "lower bound is N x 5 s", **ttd}
    # ---- Model A comparison (analysis only) ----
    m = Hd[Hd.gps_present & Hd.model_a_steps.notna()]
    def mae(d):
        return {"n": int(len(d)), "mae_steps_per_5s": float((d.model_a_steps - d.physical_steps).abs().mean()), "mean_bias": float((d.model_a_steps - d.physical_steps).mean())} if len(d) else None
    ev["model_a_comparison_only"] = {"note": "Model A is not an input to any rule. The saved model was pickled with scikit-learn 1.9.1 and is run with 1.8.0 here (version-mismatch warning); values are indicative.",
                                     "all_heldout": mae(m), "subject_12_out_of_sample_for_model_a": mae(m[m.subject == 12]),
                                     "subjects_3_10_11_model_a_validation_subjects": mae(m[m.subject.isin([3, 10, 11])])}
    ev["reporting_rules_followed"] = ["no spoofing detection rate", "no synthetic or perturbed GPS data", "no thresholds computed in this script"]
    (ROOT / "results/metrics/phase4_dryad_eval.json").write_text(json.dumps(ev, indent=1, default=float), encoding="utf-8")
    o = ev["overall"]
    print(json.dumps({"n": o["n_windows"], "raw": o["raw_fraction_of_all_windows"], "susp_raw": o["false_suspicious_raw_windows"], "susp_rep": o["false_suspicious_reported_windows"],
                      "eps_per_h": o["false_suspicious_reported_episodes_per_walking_hour"], "ttd": ttd}, indent=1))
    for s, v in ev["per_subject"].items():
        print(s, v["n_windows"], {k: round(x, 3) for k, x in v["raw_fraction_of_all_windows"].items()}, v["false_suspicious_raw_windows"], v["false_suspicious_reported_windows"])


if __name__ == "__main__":
    main()
