"""Phase 4 work item 2/3: hand-set fusion thresholds from QUANTILES of genuine Dryad walking, calibration subjects only.
No model is fitted here (quantiles and counting only). Held-out subjects are never read: the script asserts this.
Writes ml/fusion_engine/thresholds.json and results/metrics/phase4_thresholds_hash.json (SHA-256 freeze) and
results/metrics/phase4_calibration.json (supporting numbers). Run BEFORE evaluate.py; evaluate.py refuses to run if the hash differs.

Quantile levels are fixed here, before any held-out evaluation:
  ACC_MAX_M        p99 of window mean confInterval          (GPS accuracy gate; windows above are INSUFFICIENT_DATA)
  COV_MIN          p10 of GPS coverage fraction             (fix coverage of the 5 s window)
  V_MOVE_MPS       p05 of window median GPS speed           (lower quantile of genuine walking = 'significant movement')
  V_MOVE_DISP_MPS  p05 of displacement / covered seconds
  V_WALK_MAX_MPS   p99 of window median GPS speed           (upper end of the pedestrian envelope; above = running/vehicle -> UNCERTAIN)
  STEP_MIN         p05 of physical step increase per 5 s   (step-cadence lower quantile = 'steps increase')
  P_STAT_SUSPICIOUS max(0.5, p99 of mean P(STATIONARY))     (Model B false-STATIONARY level on genuine walking)
Provisional (no real stationary data exist in the repository): STEP_ZERO_MAX = 1, P_STAT_STATIONARY = 0.5, and the whole 'GPS still'
side of the table (V_MOVE_*, used as the still/moving boundary because no stationary GPS jitter distribution can be measured).
Persistence N: smallest N >= 2 whose false SUSPICIOUS episodes per genuine-walking hour (calibration subjects) <= TARGET_FP_EPISODES_PER_H,
else the largest candidate. The calibration false-flag figures are in-sample (optimistic).
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
import engine  # noqa: E402
import dryad_io as DIO  # noqa: E402

Q = {"ACC_MAX_M": 0.99, "COV_MIN": 0.10, "V_MOVE_MPS": 0.05, "V_MOVE_DISP_MPS": 0.05, "V_WALK_MAX_MPS": 0.99, "STEP_MIN": 0.05, "P_STAT_SUSPICIOUS": 0.99}
N_CANDIDATES = (1, 2, 3, 4)
N_MIN_DESIGN = 2
TARGET_FP_EPISODES_PER_H = 1.0
WIN_S = 5.0
FIELDS = ["gps_speed_mps", "gps_displacement_m", "gps_covered_s", "gps_coverage_frac", "gps_path_m", "gps_conf_m",
          "imu_n_windows", "p_stationary", "p_walking", "p_other", "physical_steps"]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def to_inputs(df):
    out = []
    for r in df[FIELDS].to_dict("records"):
        out.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in r.items()})
    return out


def qv(x, q):
    return float(np.quantile(np.asarray(x, float), q))


def sequences(df, th, n):
    """Run the engine per track. Returns list of (track_df, results)."""
    out = []
    for tr, g in df.groupby("track", sort=True):
        g = g.sort_values("win_idx")
        out.append((g, engine.run_sequence(to_inputs(g), th, n)))
    return out


def episode_count(states):
    return sum(1 for i, s in enumerate(states) if s == "SUSPICIOUS_GPS_MOVEMENT" and (i == 0 or states[i - 1] != "SUSPICIOUS_GPS_MOVEMENT"))


def latency_s(res):
    """Seconds from track start to the end of the first window whose reported state is GENUINE_WALKING (None if never)."""
    for i, r in enumerate(res):
        if r["reported_state"] == "GENUINE_WALKING":
            return (i + 1) * WIN_S
    return None


def main():
    split = json.loads((ROOT / "ml/fusion_engine/split.json").read_text())
    cal = split["calibration_subjects"]
    S = pd.read_csv(ROOT / "results/metrics/phase4_fusion_signals.csv")
    C = S[S.subject.isin(cal)].copy()
    assert not set(C.subject.unique()) & set(split["heldout_subjects"]), "held-out subject in calibration data"
    assert set(C.subject.unique()) == set(cal)
    n_tracks, n_win_all = int(C.track.nunique()), int(len(C))

    # ---- quality gates ----
    V = C[C.gps_present & C.gps_displacement_m.notna() & (C.gps_covered_s > 0)]
    acc_max = qv(V.gps_conf_m, Q["ACC_MAX_M"])
    cov_min = qv(V.gps_coverage_frac, Q["COV_MIN"])
    G = V[(V.gps_conf_m <= acc_max) & (V.gps_coverage_frac >= cov_min) & (V.imu_n_windows >= 1)].copy()
    G["disp_speed"] = G.gps_displacement_m / G.gps_covered_s
    vals = {
        "ACC_MAX_M": acc_max, "COV_MIN": cov_min,
        "V_MOVE_MPS": qv(G.gps_speed_mps, Q["V_MOVE_MPS"]),
        "V_MOVE_DISP_MPS": qv(G.disp_speed, Q["V_MOVE_DISP_MPS"]),
        "V_WALK_MAX_MPS": qv(G.gps_speed_mps, Q["V_WALK_MAX_MPS"]),
        "STEP_MIN": qv(G.physical_steps, Q["STEP_MIN"]),
        "P_STAT_SUSPICIOUS": max(0.5, qv(G.p_stationary, Q["P_STAT_SUSPICIOUS"])),
    }
    cols = {"ACC_MAX_M": ("gps_conf_m", V), "COV_MIN": ("gps_coverage_frac", V), "V_MOVE_MPS": ("gps_speed_mps", G), "V_MOVE_DISP_MPS": ("disp_speed", G),
            "V_WALK_MAX_MPS": ("gps_speed_mps", G), "STEP_MIN": ("physical_steps", G), "P_STAT_SUSPICIOUS": ("p_stationary", G)}
    per_subject = {k: {str(s): qv(g[c], Q[k]) for s, g in d.groupby("subject")} for k, (c, d) in cols.items()}
    PROV = "provisional (no live stationary calibration data)"
    CAL = "calibrated on Dryad genuine hand-held walking (calibration subjects)"
    desc = {
        "ACC_MAX_M": ("m", "mean GPS confInterval of the window above which the window is INSUFFICIENT_DATA", "window mean confInterval", CAL, V),
        "COV_MIN": ("fraction", "minimum fraction of the 5 s window covered by kept GPS fixes", "gps coverage_frac", CAL, V),
        "V_MOVE_MPS": ("m/s", "GPS reported speed (window median) at or above which GPS movement is 'significant'. Also the still/moving boundary: the still side is " + PROV, "window median valid GPS speed", CAL + "; still side: " + PROV, G),
        "V_MOVE_DISP_MPS": ("m/s", "displacement / covered seconds at or above which displacement movement is 'significant'; still side " + PROV, "gps displacement_m / covered_dur_s", CAL + "; still side: " + PROV, G),
        "V_WALK_MAX_MPS": ("m/s", "GPS speed above which movement is outside the pedestrian envelope (running / cycling / vehicle) -> UNCERTAIN", "window median valid GPS speed", CAL, G),
        "STEP_MIN": ("steps per 5 s", "physical step increase counted as 'steps increase'", "physical step increment per 5 s window (running max of steps.csv)", CAL, G),
        "P_STAT_SUSPICIOUS": ("probability", "mean Model B P(STATIONARY) required for SUSPICIOUS (never below 0.5)", "mean P_stationary of Model B windows in the decision window", CAL, G),
    }
    thr = {}
    for k, (unit, meaning, quantity, status, d) in desc.items():
        thr[k] = {"value": vals[k], "unit": unit, "meaning": meaning, "quantity": quantity,
                  "provenance": {"dataset": "Dryad (real, genuine hand-held walking; no spoofing)", "quantile": Q[k], "subjects": cal,
                                 "n_tracks": int(d.track.nunique()), "n_windows": int(len(d)), "per_subject_quantile": per_subject[k]},
                  "status": status}
    thr["STEP_ZERO_MAX"] = {"value": 1, "unit": "steps per 5 s", "meaning": "physical step increase counted as 'steps ~0' (one spurious pedometer step tolerated)",
                            "provenance": {"dataset": "hand-set design constant; no real stationary pedometer data in the repository"}, "status": PROV}
    thr["P_STAT_STATIONARY"] = {"value": 0.5, "unit": "probability", "meaning": "mean Model B P(STATIONARY) required for the STATIONARY state (majority)",
                                "provenance": {"dataset": "hand-set design constant; Dryad has no stationary windows, Model B STATIONARY recall on this domain is unknown"}, "status": PROV}
    thr["MIN_IMU_WINDOWS"] = {"value": 1, "unit": "Model B windows", "meaning": "minimum Model B windows fully inside the decision window",
                              "provenance": {"dataset": "design constant (a 5 s window holds at most 2 windows of 2.56 s at stride 1.28 s)"}, "status": "design constant"}

    # ---- stationary-data search (reported, never invented) ----
    pre = post = pre_speed = tr_pre = 0
    md = DIO.metadata()
    for tn in md[md.subject.isin(cal) & (md.hasMotion == True) & (md.hasGNSS == True)].testName:  # noqa: E712
        t = DIO.load_track(str(tn))
        e, p = t["events"].iloc[0], t["positions"]
        a, b = p[p.ms < e.testStart - 1000], p[p.ms > e.testEnd + 1000]
        pre += len(a); post += len(b); pre_speed += int(pd.to_numeric(a.speed, errors="coerce").ge(0).sum()); tr_pre += int(len(a) > 0)
    stationary_search = {
        "dryad_events_columns": ["signalStart", "testStart", "testEnd"], "dryad_events_contain_standing_periods": False,
        "fixes_before_testStart_minus_1s_calibration_tracks": int(pre), "tracks_with_such_fixes": tr_pre, "of_which_valid_speed": pre_speed,
        "fixes_after_testEnd_plus_1s": int(post),
        "decision": "NOT used as stationary evidence: these are GNSS warm-up fixes before the walk starts, with no label that the phone was stationary "
                    "(valid speeds up to about 5 m/s were seen in a pre-check of calibration tracks) and no matching stationary motion/pedometer record. "
                    "Zero-step windows inside walks (pedometer latency) are also not stationary: their median GPS speed is above V_MOVE.",
        "live_recordings": {"calibration_dir_files": sorted(p.name for p in (ROOT / "datasets/live_recordings/calibration").glob("*") if p.name != ".gitkeep"),
                            "evaluation_dir_files": sorted(p.name for p in (ROOT / "datasets/live_recordings/evaluation").glob("*") if p.name != ".gitkeep")},
        "conclusion": "No real stationary GPS or pedometer data available. Stationary-side thresholds are provisional (no live stationary calibration data).",
    }

    # ---- persistence N ----
    th0 = {k: v["value"] for k, v in thr.items()}
    th0["PERSISTENCE_N"] = 1
    hours = n_win_all * WIN_S / 3600.0
    ntab = {}
    for n in N_CANDIDATES:
        seqs = sequences(C, th0, n)
        eps = sum(episode_count([r["reported_state"] for r in res]) for _, res in seqs)
        conf_w = sum(sum(r["reported_state"] == "SUSPICIOUS_GPS_MOVEMENT" for r in res) for _, res in seqs)
        raw_w = sum(sum(r["state"] == "SUSPICIOUS_GPS_MOVEMENT" for r in res) for _, res in seqs)
        lats = [latency_s(res) for _, res in seqs]
        lat_ok = [x for x in lats if x is not None]
        ntab[str(n)] = {"false_suspicious_episodes": int(eps), "false_suspicious_episodes_per_walking_hour": eps / hours,
                        "false_suspicious_windows_reported": int(conf_w), "false_suspicious_windows_raw": int(raw_w),
                        "median_time_to_first_GENUINE_WALKING_s": float(np.median(lat_ok)) if lat_ok else None,
                        "tracks_never_GENUINE_WALKING": int(sum(x is None for x in lats)), "tracks": len(lats),
                        "decision_latency_floor_s": n * WIN_S}
    chosen = next((n for n in N_CANDIDATES if n >= N_MIN_DESIGN and ntab[str(n)]["false_suspicious_episodes_per_walking_hour"] <= TARGET_FP_EPISODES_PER_H), N_CANDIDATES[-1])
    th0["PERSISTENCE_N"] = chosen

    # ---- in-sample state distribution on calibration (optimistic, documentation only) ----
    seqs = sequences(C, th0, chosen)
    cnt = {s: 0 for s in engine.STATES}
    for _, res in seqs:
        for r in res:
            cnt[r["state"]] += 1
    in_sample = {"n_windows": n_win_all, "raw_state_fractions": {k: v / n_win_all for k, v in cnt.items()}, "raw_state_counts": cnt}

    doc = {
        "version": 1, "status": "frozen (SHA-256 in results/metrics/phase4_thresholds_hash.json)",
        "scope": "Hand-set consistency thresholds. Fusion is a consistency detector, not a spoofing classifier. Model B is an activity classifier not trained on spoofing. "
                 "No ML training in the fusion layer; values are quantiles of genuine Dryad walking measured on calibration subjects only.",
        "decision_window_s": WIN_S,
        "aggregation": {"model_b_windows": "probability mean over Model B windows (128 samples at 50 Hz, stride 64) lying fully inside the decision window",
                        "imu_class": "argmax of the mean probabilities; ties STATIONARY > WALKING > OTHER",
                        "majority_vote": "not used (reported nowhere); probability mean keeps the class margin available to the rules"},
        "persistence": {"N": chosen, "rule": "reported state changes to a decisive state after N consecutive identical raw states; UNCERTAIN/INSUFFICIENT_DATA are reported immediately",
                        "selection": {"candidates": list(N_CANDIDATES), "design_minimum": N_MIN_DESIGN, "target_false_suspicious_episodes_per_walking_hour": TARGET_FP_EPISODES_PER_H,
                                      "calibration_table_in_sample": ntab}},
        "calibration_subjects": cal, "calibration_tracks": n_tracks, "calibration_windows_all": n_win_all, "calibration_windows_gate_pass": int(len(G)),
        "thresholds": thr,
        "provisional_thresholds": [k for k, v in thr.items() if "provisional" in v["status"]],
        "input_files_sha256": {"results/metrics/phase4_fusion_signals.csv": sha(ROOT / "results/metrics/phase4_fusion_signals.csv"),
                               "ml/fusion_engine/split.json": sha(ROOT / "ml/fusion_engine/split.json")},
    }
    (ROOT / "ml/fusion_engine/thresholds.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    h = {"thresholds_json_sha256": sha(ROOT / "ml/fusion_engine/thresholds.json"), "split_json_sha256": sha(ROOT / "ml/fusion_engine/split.json"),
         "engine_py_sha256": sha(ROOT / "ml/fusion_engine/engine.py"),
         "frozen_before": "any held-out evaluation (evaluate.py verifies these hashes first)"}
    (ROOT / "results/metrics/phase4_thresholds_hash.json").write_text(json.dumps(h, indent=1), encoding="utf-8")
    cal_doc = {"quantile_levels": Q, "per_subject_quantiles": per_subject, "gate_pass_windows": int(len(G)),
               "windows_all": n_win_all, "stationary_data_search": stationary_search, "persistence_table_in_sample": ntab,
               "persistence_chosen": chosen, "in_sample_state_distribution": in_sample,
               "note": "All calibration false-flag figures are in-sample (thresholds were computed from the same windows) and therefore optimistic."}
    (ROOT / "results/metrics/phase4_calibration.json").write_text(json.dumps(cal_doc, indent=1), encoding="utf-8")
    print(json.dumps({k: v["value"] for k, v in thr.items()}, indent=1), "N", chosen)
    print(json.dumps(ntab, indent=1)); print(in_sample["raw_state_fractions"]); print(stationary_search["fixes_before_testStart_minus_1s_calibration_tracks"])


if __name__ == "__main__":
    main()
