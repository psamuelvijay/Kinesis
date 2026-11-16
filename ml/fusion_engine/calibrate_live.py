"""Phase 4 work item 4: recalibrate ONLY the stationary GPS-jitter and stationary-IMU thresholds from REAL live stationary recordings in
datasets/live_recordings/calibration/. Refuses to read datasets/live_recordings/evaluation/ (the folder is never listed or opened).
No model is fitted: quantiles and counting only. Quantile levels are fixed here, before any live data are seen.

Recalibrated (all 'provisional (no live stationary calibration data)' in thresholds.json):
  V_MOVE_MPS       = max(frozen value, q99 of window-median GPS speed of stationary windows)       (GPS jitter must stay below 'moving')
  V_MOVE_DISP_MPS  = max(frozen value, q99 of displacement / covered seconds of stationary windows)
  STEP_ZERO_MAX    = ceil(q99 of the physical step increase per 5 s in stationary windows), capped at STEP_MIN - 1
  P_STAT_STATIONARY = max(0.5, q05 of the mean Model B P(STATIONARY) of stationary windows)
Everything else (ACC_MAX_M, COV_MIN, V_WALK_MAX_MPS, STEP_MIN, P_STAT_SUSPICIOUS, N, MIN_IMU_WINDOWS) is copied unchanged from the frozen file.
Data: scenarios S2 (table) and S3 (in hand), real GPS (isMock must be false), >= MIN_SESSIONS sessions and >= MIN_WINDOWS usable windows each.
Otherwise: status PENDING USER DATA, nothing is written except the status JSON. The frozen thresholds.json is never modified; the output is
ml/fusion_engine/thresholds_live.json plus results/metrics/phase4_live_thresholds_hash.json (use evaluate_live.py --use-live-calibration).
"""
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import engine  # noqa: E402
import ingest_live_logs as ING  # noqa: E402

MET = ROOT / "results" / "metrics"
Q_SPEED, Q_DISP, Q_STEPS, Q_PSTAT = 0.99, 0.99, 0.99, 0.05
MIN_SESSIONS, MIN_WINDOWS = 2, 60   # per scenario (60 windows = 5 min of 5 s windows)
PROV_PREFIX = "provisional"


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    h = json.loads((MET / "phase4_thresholds_hash.json").read_text())
    if sha(ROOT / "ml/fusion_engine/thresholds.json") != h["thresholds_json_sha256"]:
        sys.exit("REFUSED: frozen thresholds.json differs from its recorded hash")
    th, doc = engine.load_thresholds(ROOT / "ml/fusion_engine/thresholds.json")
    status_path = MET / "phase4_live_calibration.json"
    df, infos, rejected = ING.scan_split("calibration")

    def pending(msg):
        status_path.write_text(json.dumps({"status": "PENDING USER DATA", "detail": msg, "rejected_sessions": rejected,
                                           "stationary_thresholds": "provisional (no live stationary calibration data)",
                                           "thresholds_live_written": False}, indent=1), encoding="utf-8")
        print("PENDING USER DATA:", msg)

    if df is None:
        return pending("datasets/live_recordings/calibration/ has no valid session; thresholds stay provisional (no live stationary calibration data).")
    S = df[df.scenario.isin(("S2", "S3"))].copy()
    # GPS-jitter windows: GPS quality gates of the frozen engine; IMU windows additionally need Model B and the step counter
    g = S[S.gps_present & S.gps_displacement_m.notna() & (S.gps_covered_s > 0) & (S.gps_conf_m <= th["ACC_MAX_M"]) & (S.gps_coverage_frac >= th["COV_MIN"])].copy()
    g["disp_speed"] = g.gps_displacement_m / g.gps_covered_s
    gi = g[(g.imu_n_windows >= th["MIN_IMU_WINDOWS"]) & g.physical_steps.notna() & g.p_stationary.notna()]
    need = {}
    for sc in ("S2", "S3"):
        need[sc] = {"sessions": int(S[S.scenario == sc].session_id.nunique()), "gps_windows": int((g.scenario == sc).sum()), "imu_windows": int((gi.scenario == sc).sum())}
    if any(v["sessions"] < MIN_SESSIONS or v["gps_windows"] < MIN_WINDOWS or v["imu_windows"] < MIN_WINDOWS for v in need.values()):
        return pending(f"insufficient stationary calibration data (need >= {MIN_SESSIONS} sessions and >= {MIN_WINDOWS} usable windows per scenario): {need}")

    new = {"V_MOVE_MPS": max(th["V_MOVE_MPS"], float(np.quantile(g.gps_speed_mps, Q_SPEED))),
           "V_MOVE_DISP_MPS": max(th["V_MOVE_DISP_MPS"], float(np.quantile(g.disp_speed, Q_DISP))),
           "STEP_ZERO_MAX": float(min(math.ceil(float(np.quantile(gi.physical_steps, Q_STEPS))), th["STEP_MIN"] - 1)),
           "P_STAT_STATIONARY": max(0.5, float(np.quantile(gi.p_stationary, Q_PSTAT)))}
    capped = math.ceil(float(np.quantile(gi.physical_steps, Q_STEPS))) > th["STEP_MIN"] - 1
    # cost of the higher still/moving boundary on genuine Dryad walking (calibration subjects), read-only context
    cost = None
    sp = MET / "phase4_fusion_signals.csv"
    if sp.exists():
        d = pd.read_csv(sp)
        split = json.loads((ROOT / "ml/fusion_engine/split.json").read_text())
        d = d[d.subject.isin(split["calibration_subjects"]) & d.gps_present & d.gps_displacement_m.notna() & (d.gps_covered_s > 0)]
        ds = d.gps_displacement_m / d.gps_covered_s
        cost = {"dryad_walking_windows": int(len(d)), "frac_below_frozen_V_MOVE_MPS": float((d.gps_speed_mps < th["V_MOVE_MPS"]).mean()),
                "frac_below_new_V_MOVE_MPS": float((d.gps_speed_mps < new["V_MOVE_MPS"]).mean()),
                "frac_below_frozen_V_MOVE_DISP_MPS": float((ds < th["V_MOVE_DISP_MPS"]).mean()),
                "frac_below_new_V_MOVE_DISP_MPS": float((ds < new["V_MOVE_DISP_MPS"]).mean())}
    live = json.loads((ROOT / "ml/fusion_engine/thresholds.json").read_text())
    for k, v in new.items():
        e = live["thresholds"][k]
        e["frozen_value"] = e["value"]
        e["value"] = v
        e["status"] = "calibrated on live stationary recordings (datasets/live_recordings/calibration, S2+S3, real GPS)"
        e["provenance"] = {"dataset": "live Android recordings, calibration folder only", "sessions": need,
                           "quantile": {"V_MOVE_MPS": Q_SPEED, "V_MOVE_DISP_MPS": Q_DISP, "STEP_ZERO_MAX": Q_STEPS, "P_STAT_STATIONARY": Q_PSTAT}[k]}
    live["status"] = "live stationary recalibration of 4 thresholds; parent = frozen thresholds.json"
    live["provisional_thresholds"] = [k for k, v in live["thresholds"].items() if str(v["status"]).startswith(PROV_PREFIX)]
    out = ROOT / "ml/fusion_engine/thresholds_live.json"
    out.write_text(json.dumps(live, indent=1), encoding="utf-8")
    (MET / "phase4_live_thresholds_hash.json").write_text(json.dumps({"thresholds_live_json_sha256": sha(out), "parent_thresholds_json_sha256": h["thresholds_json_sha256"],
                                                                      "calibration_signals": f"{len(S)} windows from {len(infos)} calibration sessions"}, indent=1), encoding="utf-8")
    status_path.write_text(json.dumps({"status": "calibrated", "thresholds_live_written": True, "old": {k: th[k] for k in new}, "new": new,
                                       "step_zero_max_capped_at_STEP_MIN_minus_1": bool(capped), "data": need, "cost_on_dryad_genuine_walking": cost,
                                       "quantile_levels": {"speed": Q_SPEED, "disp": Q_DISP, "steps": Q_STEPS, "p_stationary_lower": Q_PSTAT},
                                       "rejected_sessions": rejected}, indent=1), encoding="utf-8")
    print(json.dumps(new, indent=1))


if __name__ == "__main__":
    main()
