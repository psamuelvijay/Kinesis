"""Phase 4: build the per-decision-window input table for the fusion engine from REAL Dryad data (all 146 tracks with GNSS + motion).
No thresholds are used here; the table is the same for calibration and held-out subjects. Deterministic, read-only on datasets/.

Decision window = Model A's non-overlapping 5 s window (start = max(testStart,0) + k*5 s, up to min(testEnd, last steps ms)).
  GPS columns   : datasets/dryad/processed/windows_5s.csv (Phase 2 cleaned GPS window features). A window absent from that file was
                  excluded by the Phase 2 GPS rules (gap > 10 s / no kept fix / no valid speed); it is kept here with GPS = NaN so the
                  engine reports INSUFFICIENT_DATA instead of silently dropping it.
  Model B       : results/metrics/phase4_dryad_modelB_windows.csv (frozen Model B on 128-sample, 50 Hz windows, stride 64).
                  A Model B window belongs to a decision window if all its samples lie inside it: start >= a and start + 127*20 ms <= b.
                  Aggregation = mean of probabilities (see engine.aggregate_model_b).
  Physical steps: Dryad steps.csv running-max increment inside the window (Phase 2 definition). STAND-IN for Android
                  TYPE_STEP_COUNTER / TYPE_STEP_DETECTOR increments (Dryad steps come from the phone pedometer API).
  Model A steps : frozen ml/models/best_model.joblib on the Phase 2 features; comparison only, never a rule input.
Output: results/metrics/phase4_fusion_signals.csv
"""
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import dryad_io as DIO  # noqa: E402
import engine  # noqa: E402

WIN_MS = 5000.0
B_LAST_SAMPLE_MS = 127 * 20.0


def speed_bin(v):
    return "unknown" if not np.isfinite(v) else "<1.0" if v < 1.0 else "1.0-1.3" if v < 1.3 else "1.3-1.6" if v < 1.6 else ">=1.6"


def cum_fn(st):
    st = st.sort_values("ms", kind="stable")
    ms, rm = st.ms.values.astype(float), np.maximum.accumulate(st.steps.values.astype(float))

    def f(t):
        i = np.searchsorted(ms, t, side="right") - 1
        return 0.0 if i < 0 else float(rm[i])
    return f


def main():
    W = pd.read_csv(ROOT / "datasets/dryad/processed/windows_5s.csv")
    B = pd.read_csv(ROOT / "results/metrics/phase4_dryad_modelB_windows.csv")
    md = DIO.metadata()
    md = md[(md["hasMotion"] == True) & (md["hasGNSS"] == True)]  # noqa: E712
    model_a = joblib.load(ROOT / "ml/models/best_model.joblib")
    feats = json.loads((ROOT / "results/metrics/phase2_windows_summary.json").read_text())["model_input_features"]
    W = W.copy()
    W["model_a_steps"] = model_a.predict(W[feats])
    Wi = {(r.track, int(r.win_idx)): r for r in W.itertuples(index=False)}
    Bg = {k: g.sort_values("win_start_ms") for k, g in B.groupby("track")}
    rows, skipped = [], []
    for _, m in md.sort_values(["subject", "testID"]).iterrows():
        name = str(m["testName"])
        t = DIO.load_track(name)
        if t["positions"] is None or t["steps"] is None or t["events"] is None:
            skipped.append(name)
            continue
        ev, st = t["events"].iloc[0], t["steps"]
        start = max(float(ev.testStart), 0.0)
        end = min(float(ev.testEnd), float(st.ms.max()))
        nwin = int(np.floor((end - start) / WIN_MS))
        cum = cum_fn(st)
        bg = Bg.get(name)
        bs = bg.win_start_ms.values if bg is not None else np.array([])
        bp = bg[["p_STATIONARY", "p_WALKING", "p_OTHER"]].values if bg is not None else np.zeros((0, 3))
        dev = str(m["device"])
        for k in range(nwin):
            a, b = start + k * WIN_MS, start + (k + 1) * WIN_MS
            sel = (bs >= a) & (bs + B_LAST_SAMPLE_MS <= b)
            agg = engine.aggregate_model_b([tuple(x) for x in bp[sel]])
            w = Wi.get((name, k))
            row = dict(track=name, subject=int(m["subject"]), os="iOS" if dev.startswith("Apple") else "Android", device=dev,
                       speed_bin=speed_bin(float(m["average_walking_speed"])), win_idx=k, t_start_ms=a, t_rel_s=k * 5.0,
                       gps_present=w is not None,
                       gps_speed_mps=w.speed_median if w is not None else np.nan,
                       gps_displacement_m=w.displacement_m if w is not None else np.nan,
                       gps_covered_s=w.covered_dur_s if w is not None else np.nan,
                       gps_coverage_frac=w.coverage_frac if w is not None else np.nan,
                       gps_path_m=w.path_m if w is not None else np.nan,
                       gps_conf_m=w.conf_mean if w is not None else np.nan,
                       model_a_steps=w.model_a_steps if w is not None else np.nan,
                       distance_anomaly=bool(w.distance_anomaly) if w is not None else False,
                       imu_n_windows=agg["imu_n_windows"],
                       p_stationary=agg["p_stationary"], p_walking=agg["p_walking"], p_other=agg["p_other"],
                       physical_steps=cum(b) - cum(a))
            rows.append(row)
    S = pd.DataFrame(rows)
    for c in ("p_stationary", "p_walking", "p_other"):
        S[c] = S[c].astype(float).round(6)
    S = S.round({"gps_speed_mps": 6, "gps_displacement_m": 6, "gps_covered_s": 6, "gps_coverage_frac": 6, "gps_path_m": 6, "gps_conf_m": 6, "model_a_steps": 4, "t_start_ms": 3})
    S.to_csv(ROOT / "results/metrics/phase4_fusion_signals.csv", index=False)
    print(len(S), S.track.nunique(), S.subject.nunique(), "skipped", skipped, "gps_present", int(S.gps_present.sum()), "imu>=1", int((S.imu_n_windows >= 1).sum()))


if __name__ == "__main__":
    main()
