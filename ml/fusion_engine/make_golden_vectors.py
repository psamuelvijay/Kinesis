"""Write ml/fusion_engine/golden_vectors.json: REAL decision-window inputs (Dryad calibration subjects) with the expected engine output,
for reimplementation checks (Kotlin). Single-window vectors use decide_window with no history; sequence vectors use run_sequence.
Selection is deterministic: for each (state, reason) the first window in (track, win_idx) order, then a second one from a different track
if available. Expected outputs are produced by engine.py with the frozen thresholds; they are regression targets, not accuracy claims.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import engine  # noqa: E402

FIELDS = ["gps_speed_mps", "gps_displacement_m", "gps_covered_s", "gps_coverage_frac", "gps_path_m", "gps_conf_m",
          "imu_n_windows", "p_stationary", "p_walking", "p_other", "physical_steps"]


def clean(d):
    return {k: (None if (isinstance(v, float) and np.isnan(v)) else (int(v) if k in ("imu_n_windows", "physical_steps") else float(v))) for k, v in d.items()}


def main():
    th, tdoc = engine.load_thresholds(ROOT / "ml/fusion_engine/thresholds.json")
    split = json.loads((ROOT / "ml/fusion_engine/split.json").read_text())
    S = pd.read_csv(ROOT / "results/metrics/phase4_fusion_signals.csv")
    C = S[S.subject.isin(split["calibration_subjects"])].sort_values(["track", "win_idx"]).reset_index(drop=True)
    seen, vecs = {}, []
    for _, row in C.iterrows():
        inp = clean({k: row[k] for k in FIELDS})
        r = engine.decide_window(inp, th)
        key = (r["state"], r["reason"])
        used = seen.setdefault(key, [])
        if len(used) >= 2 or row.track in used:
            continue
        used.append(row.track)
        vecs.append({"id": f"{r['state']}|{r['reason']}|{row.track}#{int(row.win_idx)}", "source": {"track": row.track, "win_idx": int(row.win_idx), "subject": int(row.subject)},
                     "input": inp, "expected": {"state": r["state"], "reason": r["reason"], "movement_accepted": r["movement_accepted"],
                                                "explanation": r.get("explanation")}})
    # one real session excerpt for persistence (first 40 windows of the first calibration track with a raw SUSPICIOUS window, else of the first track)
    seq_track = None
    for tr, g in C.groupby("track", sort=True):
        res = engine.run_sequence([clean({k: r[k] for k in FIELDS}) for _, r in g.iterrows()], th)
        if any(x["state"] == "SUSPICIOUS_GPS_MOVEMENT" for x in res):
            seq_track = tr
            break
    seq_track = seq_track or C.track.iloc[0]
    g = C[C.track == seq_track].head(40)
    inputs = [clean({k: r[k] for k in FIELDS}) for _, r in g.iterrows()]
    res = engine.run_sequence(inputs, th)
    doc = {"description": "Golden vectors from real Dryad calibration-subject windows. input -> expected state. Regression/reimplementation targets only.",
           "thresholds_sha256_note": "vectors are valid for ml/fusion_engine/thresholds.json as hashed in results/metrics/phase4_thresholds_hash.json",
           "thresholds": {k: v for k, v in th.items()},
           "single_window_vectors": vecs,
           "sequence_vectors": [{"source_track": seq_track, "persistence_N": th["PERSISTENCE_N"], "inputs": inputs,
                                 "expected_raw_states": [r["state"] for r in res], "expected_reported_states": [r["reported_state"] for r in res],
                                 "expected_movement_flagged": [r["movement_flagged"] for r in res]}]}
    (ROOT / "ml/fusion_engine/golden_vectors.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(len(vecs), sorted(seen.keys()), seq_track)


if __name__ == "__main__":
    main()
