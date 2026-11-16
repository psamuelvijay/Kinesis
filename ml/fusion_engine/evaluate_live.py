"""Phase 4 work item 4: evaluate the FROZEN fusion engine on held-out live Android recordings (datasets/live_recordings/evaluation/).
Fusion is a consistency detector, not a learned spoofing classifier; Model B is an activity classifier not trained on spoofing.
No threshold is computed or changed here. Refuses to run if engine.py, split.json or the thresholds file differ from the frozen hashes in
results/metrics/phase4_thresholds_hash.json. Default thresholds = ml/fusion_engine/thresholds.json (frozen, with provisional stationary side).
--use-live-calibration uses ml/fusion_engine/thresholds_live.json (written by calibrate_live.py from the calibration folder only), after
verifying its own hash file and that its parent is the frozen thresholds.json.
Only real recordings are read. With no valid session this writes a PENDING status and no metric.

Metrics (reported states = after persistence N; 'movement accepted' = reported GENUINE_WALKING, 'movement flagged' = reported SUSPICIOUS):
  detection rate per session (S5 sessions with >= 1 flagged window) and per decision window (all windows / evaluable = not INSUFFICIENT_DATA)
  time to detection = seconds from the operator start to the end of the first flagged window
  false positive rate = flagged windows / sessions / episodes per hour on S1-S4 (genuine walking and stationary); S7 reported separately
  GPS distance falsely accepted = metres of GPS path (links between kept fixes) falling in windows reported GENUINE_WALKING, S5 (S6 separately)
  false 'movement accepted' rate on physically stationary sessions (S2, S3, S5)
  per-scenario confusion over {GENUINE_WALKING, STATIONARY, SUSPICIOUS_GPS_MOVEMENT, UNCERTAIN} (+ INSUFFICIENT_DATA column)
S6 (mock location while genuinely walking) is a conflict case: phone motion supports the walk, so a consistency check is not expected to flag it.
It is reported, never counted as a missed detection.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import engine  # noqa: E402
import ingest_live_logs as ING  # noqa: E402

MET = ROOT / "results" / "metrics"
FOUR = ("GENUINE_WALKING", "STATIONARY", "SUSPICIOUS_GPS_MOVEMENT", "UNCERTAIN")
OUT_JSON, OUT_CSV = MET / "phase4_live_eval.json", MET / "phase4_live_windows.csv"
FROZEN_SET = {"genuine_stationary_realgps": ("S1", "S2", "S3", "S4")}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_and_load(use_live):
    h = json.loads((MET / "phase4_thresholds_hash.json").read_text())
    for fn, key in (("thresholds.json", "thresholds_json_sha256"), ("split.json", "split_json_sha256"), ("engine.py", "engine_py_sha256")):
        if sha(ROOT / "ml/fusion_engine" / fn) != h[key]:
            sys.exit(f"REFUSED: {fn} differs from the frozen hash in results/metrics/phase4_thresholds_hash.json")
    path, label = ROOT / "ml/fusion_engine/thresholds.json", "frozen thresholds.json (stationary side provisional)"
    if use_live:
        lp, lh = ROOT / "ml/fusion_engine/thresholds_live.json", MET / "phase4_live_thresholds_hash.json"
        if not lp.exists() or not lh.exists():
            sys.exit("REFUSED: --use-live-calibration but thresholds_live.json / phase4_live_thresholds_hash.json do not exist (run calibrate_live.py on real calibration data)")
        lj = json.loads(lh.read_text())
        if sha(lp) != lj["thresholds_live_json_sha256"] or lj["parent_thresholds_json_sha256"] != h["thresholds_json_sha256"]:
            sys.exit("REFUSED: thresholds_live.json hash or parent hash mismatch")
        path, label = lp, "thresholds_live.json (stationary GPS-jitter and stationary-IMU thresholds recalibrated on live calibration recordings)"
    th, doc = engine.load_thresholds(path)
    return th, doc, h, label


def episodes(states, target="SUSPICIOUS_GPS_MOVEMENT"):
    return sum(1 for i, s in enumerate(states) if s == target and (i == 0 or states[i - 1] != target))


def rate(num, den):
    return float(num) / den if den else None


def qs(x):
    x = [v for v in x if v is not None]
    return {"n": len(x), "median": float(np.median(x)), "min": float(np.min(x)), "max": float(np.max(x))} if x else {"n": 0}


def confusion(df):
    """Rows: truth scenario; columns: predicted (reported) state over the four states plus INSUFFICIENT_DATA."""
    out = {}
    for sc, g in df.groupby("scenario"):
        c = {s: int((g.reported_state == s).sum()) for s in (*FOUR, "INSUFFICIENT_DATA")}
        raw = {s: int((g.state == s).sum()) for s in (*FOUR, "INSUFFICIENT_DATA")}
        exp = ING.SCENARIOS[sc][3]
        ev = int(len(g) - c["INSUFFICIENT_DATA"])
        out[sc] = {"name": ING.SCENARIOS[sc][0], "ground_truth": ING.SCENARIOS[sc][1], "expected_state": exp, "windows": int(len(g)),
                   "reported_counts": c, "raw_counts": raw, "evaluable_windows": ev,
                   "expected_state_rate_of_evaluable": rate(c[exp], ev) if exp else None,
                   "expected_state_rate_of_all": rate(c[exp], len(g)) if exp else None}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-live-calibration", action="store_true")
    a = ap.parse_args()
    th, tdoc, h, label = verify_and_load(a.use_live_calibration)
    df, infos, rejected = ING.scan_split("evaluation")
    if df is None:
        doc = {"status": "PENDING USER DATA", "detail": "datasets/live_recordings/evaluation/ has no valid session. No metric was computed; nothing was simulated.",
               "rejected_sessions": rejected, "thresholds_used": label, "thresholds_sha256": h["thresholds_json_sha256"]}
        OUT_JSON.write_text(json.dumps(doc, indent=1), encoding="utf-8")
        print("PENDING USER DATA:", doc["detail"])
        return
    rows = []
    for sid, g in df.groupby("session_id", sort=True):
        g = g.sort_values("win_idx")
        res = engine.run_sequence(ING.engine_inputs(g), th)
        for (_, r), x in zip(g.iterrows(), res):
            rows.append({**r.to_dict(), "state": x["state"], "reason": x["reason"], "reported_state": x["reported_state"],
                         "movement_flagged": bool(x["movement_flagged"]), "movement_accepted_reported": x["movement_accepted_reported"]})
    R = pd.DataFrame(rows)
    R.round(6).to_csv(OUT_CSV, index=False)
    hours = lambda d: len(d) * 5.0 / 3600.0  # noqa: E731
    flagged = lambda d: d.reported_state == "SUSPICIOUS_GPS_MOVEMENT"  # noqa: E731
    accepted = lambda d: d.reported_state == "GENUINE_WALKING"  # noqa: E731
    nonins = lambda d: d[d.reported_state != "INSUFFICIENT_DATA"]  # noqa: E731

    per_session = []
    for sid, g in R.groupby("session_id", sort=True):
        g = g.sort_values("win_idx")
        fl = list(flagged(g))
        first = next((i for i, f in enumerate(fl) if f), None)
        per_session.append({"session_id": sid, "scenario": g.scenario.iloc[0], "subject_id": g.subject_id.iloc[0], "device_model": g.device_model.iloc[0],
                            "windows": int(len(g)), "flagged_windows": int(sum(fl)), "accepted_windows": int(accepted(g).sum()),
                            "flagged_episodes": episodes(list(g.reported_state)),
                            "time_to_first_flag_s": (first + 1) * 5.0 if first is not None else None,
                            "gps_path_total_m": float(g.gps_link_path_m.sum()), "gps_path_in_accepted_windows_m": float(g.loc[accepted(g), "gps_link_path_m"].sum()),
                            "gps_path_in_flagged_windows_m": float(g.loc[flagged(g), "gps_link_path_m"].sum()),
                            "meets_min_duration": not any("below the protocol minimum" in w for i in infos if i["session_id"] == sid for w in i["warnings"])})
    P = pd.DataFrame(per_session)

    # ---- spoofing (S5) ----
    s5 = R[R.scenario == "S5"]
    ps5 = P[P.scenario == "S5"]
    spoof = {"definition": "S5: mock-location app on the same kind of route while the phone is physically stationary (setup ground truth). Expected: movement flagged.",
             "n_sessions": int(len(ps5)), "n_windows": int(len(s5)),
             "session_detection_rate": rate((ps5.flagged_windows > 0).sum(), len(ps5)),
             "window_detection_rate_all_windows": rate(flagged(s5).sum(), len(s5)),
             "window_detection_rate_evaluable_windows": rate(flagged(s5).sum(), len(nonins(s5))),
             "time_to_detection_s": qs([None if pd.isna(x) else x for x in ps5.time_to_first_flag_s]),
             "sessions_never_detected": [r for r in ps5.session_id[ps5.flagged_windows == 0]],
             "latency_floor_s": th["PERSISTENCE_N"] * 5.0,
             "gps_distance_falsely_accepted_m": float(ps5.gps_path_in_accepted_windows_m.sum()),
             "gps_distance_total_m": float(ps5.gps_path_total_m.sum()),
             "gps_distance_falsely_accepted_fraction": rate(ps5.gps_path_in_accepted_windows_m.sum(), ps5.gps_path_total_m.sum()),
             "false_movement_accepted_rate_windows": rate(accepted(s5).sum(), len(s5)),
             "reported_state_counts": {k: int((s5.reported_state == k).sum()) for k in (*FOUR, "INSUFFICIENT_DATA")},
             "insufficient_data_reasons": {k: int(v) for k, v in s5[s5.state == "INSUFFICIENT_DATA"].reason.str.replace(r"^missing:.*", "missing_input", regex=True).value_counts().items()}}
    if not len(ps5):
        spoof = {"status": "no S5 session in the evaluation folder: no detection rate computed"}

    # ---- false positives on genuine walking / stationary with real GPS (S1-S4) ----
    gen = R[R.scenario.isin(FROZEN_SET["genuine_stationary_realgps"])]
    pg = P[P.scenario.isin(FROZEN_SET["genuine_stationary_realgps"])]
    fpr = {"scenarios": "S1-S4 (genuine walking outdoors, stationary table, stationary in hand, pocket walking; real GPS)",
           "n_sessions": int(len(pg)), "n_windows": int(len(gen)),
           "window_false_flag_rate_all_windows": rate(flagged(gen).sum(), len(gen)),
           "window_false_flag_rate_evaluable_windows": rate(flagged(gen).sum(), len(nonins(gen))),
           "session_false_flag_rate": rate((pg.flagged_windows > 0).sum(), len(pg)),
           "false_flag_episodes_per_device_hour": rate(pg.flagged_episodes.sum(), hours(gen)),
           "device_hours": hours(gen),
           "per_scenario": {sc: {"windows": int(len(g)), "false_flag_windows": int(flagged(g).sum()),
                                 "false_flag_rate_all_windows": rate(flagged(g).sum(), len(g)),
                                 "genuine_movement_accepted_rate_all_windows": rate(accepted(g).sum(), len(g)) if ING.SCENARIOS[sc][1] == "walking" else None}
                            for sc, g in gen.groupby("scenario")}}
    # ---- false 'movement accepted' on physically stationary ----
    st = R[R.scenario.isin(("S2", "S3", "S5"))]
    fma = {"definition": "windows reported GENUINE_WALKING (movement accepted) while the phone is physically stationary (setup ground truth)",
           "per_scenario": {sc: {"windows": int(len(g)), "accepted_windows": int(accepted(g).sum()), "false_movement_accepted_rate": rate(accepted(g).sum(), len(g))}
                            for sc, g in st.groupby("scenario")},
           "all_stationary_sessions": {"windows": int(len(st)), "false_movement_accepted_rate": rate(accepted(st).sum(), len(st))}}
    s6, s7 = R[R.scenario == "S6"], R[R.scenario == "S7"]
    ps6 = P[P.scenario == "S6"]
    conflict = ({"note": "Mock location while genuinely walking (labelled conflict case). Phone motion and steps are real, so no consistency detector is expected to flag it. "
                         "Reported for transparency; NOT counted as missed detection.",
                 "n_sessions": int(len(ps6)), "n_windows": int(len(s6)), "reported_state_counts": {k: int((s6.reported_state == k).sum()) for k in (*FOUR, "INSUFFICIENT_DATA")},
                 "gps_path_in_accepted_windows_m": float(ps6.gps_path_in_accepted_windows_m.sum()), "gps_path_total_m": float(ps6.gps_path_total_m.sum())}
                if len(ps6) else {"status": "no S6 session"})
    other = ({"note": "Vehicle / stairs / jogging: expected UNCERTAIN; flags and acceptances here are false.", "n_windows": int(len(s7)),
              "movement_flagged_windows": int(flagged(s7).sum()), "movement_accepted_windows": int(accepted(s7).sum()),
              "reported_state_counts": {k: int((s7.reported_state == k).sum()) for k in (*FOUR, "INSUFFICIENT_DATA")}} if len(s7) else {"status": "no S7 session"})
    doc = {"status": "evaluated",
           "scope": "Consistency detector evaluated on real, held-out live recordings. Not a learned spoofing classifier; Model B is an activity classifier not trained on spoofing. "
                    "Ground truth = experimenter setup, not Location.isMock. Output wording: movement accepted / movement flagged.",
           "thresholds_used": label, "thresholds_sha256": h["thresholds_json_sha256"], "engine_sha256": h["engine_py_sha256"],
           "persistence_N": th["PERSISTENCE_N"], "provisional_thresholds": tdoc.get("provisional_thresholds"),
           "n_sessions": int(len(P)), "n_decision_windows": int(len(R)), "rejected_sessions": rejected,
           "sessions_below_min_duration": [r["session_id"] for r in per_session if not r["meets_min_duration"]],
           "spoofing_detection_S5": spoof, "false_positive_S1_S4": fpr, "false_movement_accepted_physically_stationary": fma,
           "conflict_case_S6": conflict, "other_behaviour_S7": other,
           "per_scenario_confusion": confusion(R), "per_session": per_session,
           "n_subjects": int(R.subject_id.nunique()), "n_devices": int(R.device_model.nunique()),
           "caveat": "Few sessions: report counts with the numbers; no confidence interval is claimed."}
    OUT_JSON.write_text(json.dumps(doc, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("n_sessions", "n_decision_windows", "spoofing_detection_S5", "false_positive_S1_S4")}, indent=1, default=float))


if __name__ == "__main__":
    main()
