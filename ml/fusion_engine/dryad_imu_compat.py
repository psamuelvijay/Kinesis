"""Phase 4 work item 1: Dryad IMU compatibility check and Dryad -> Model B input pipeline (read-only, deterministic).

Inputs: Dryad motion.csv (accelX/Y/Z gravity removed, accelWithGX/Y/Z, rotRateAlpha/Beta/Gamma, ms, interval),
        MotionSense/UCI HAR training windows (via ml/preprocessing/activity_data.py), frozen Model B (combined).
Outputs: results/metrics/phase4_dryad_imu_check.json, results/metrics/phase4_dryad_modelB_windows.csv.
No randomness, no model fitting. Model B is only loaded and used for predict_proba.

Pipeline (see PIPELINE dict): m/s^2 -> g (/9.80665); gyro deg/s -> rad/s (documented DeviceMotionEvent unit, tested against data);
timestamp-based linear interpolation to a 50 Hz grid inside [testStart, testEnd], only between two observed samples that are at most
MAX_GAP_MS apart; 128-sample windows, stride 64; windows with any invalid grid point or fewer than MIN_OBS observed samples dropped and counted.
"""
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
sys.path.insert(0, str(ROOT / "ml" / "feature_extraction"))
import activity_data as AD  # noqa: E402
import dryad_io as DIO  # noqa: E402
from activity_features import FEATURE_NAMES, extract_features  # noqa: E402

G = 9.80665
DEG2RAD = np.pi / 180.0
FS, WIN, STRIDE = 50, 128, 64
STEP_MS = 1000.0 / FS
MAX_GAP_MS = 100.0   # max distance between the two observed samples bracketing an interpolated point
MIN_OBS = 64         # min observed samples inside a window span (>= half of 128, ~25 Hz effective)
PIPELINE = {
    "accel_columns": ["accelX", "accelY", "accelZ"], "accel_unit_in": "m/s^2", "accel_to_g": f"divide by {G}",
    "gyro_columns": ["rotRateAlpha", "rotRateBeta", "rotRateGamma"], "gyro_unit_in": "deg/s (see gyro_unit_evidence)",
    "gyro_to_rad_s": "multiply by pi/180", "walk_interval": "events.csv testStart..testEnd (ms), samples outside are not windowed",
    "timestamps": "motion.ms (device ms); stable sort, exact duplicate ms dropped (first kept)",
    "resample": f"linear interpolation to {FS} Hz grid, grid point valid only if bracketing observed samples are <= {MAX_GAP_MS} ms apart",
    "window": f"{WIN} samples, stride {STRIDE} (50% overlap), all {WIN} grid points valid",
    "under_coverage": f"window dropped if < {MIN_OBS} observed samples fall inside its time span",
    "features": "ml/feature_extraction/activity_features.extract_features (unchanged)",
    "model": "ml/models/activity_combined_xgboost.joblib (frozen)",
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def q(x, qs=(0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return None
    return {"n": int(len(x)), **{f"p{int(round(k * 100)):02d}": float(np.quantile(x, k)) for k in qs}}


def os_of(dev):
    return "iOS" if str(dev).startswith("Apple") else "Android"


def speed_bin(v):
    if not np.isfinite(v):
        return "unknown"
    return "<1.0" if v < 1.0 else "1.0-1.3" if v < 1.3 else "1.3-1.6" if v < 1.6 else ">=1.6"


def resample_windows(ms, acc_g, gyr_rads, t_start, t_end):
    """Return windows (n,128,6) float64, start_ms list, and drop-count dict. Observed-only interpolation."""
    order = np.argsort(ms, kind="stable")
    ms, acc_g, gyr_rads = ms[order], acc_g[order], gyr_rads[order]
    keep = np.concatenate([[True], np.diff(ms) > 0])  # drops exact duplicates (and equal-after-sort)
    ms, acc_g, gyr_rads = ms[keep], acc_g[keep], gyr_rads[keep]
    d = {"grid_points": 0, "grid_invalid_gap": 0, "windows_possible": 0, "windows_dropped_gap": 0,
         "windows_dropped_undercoverage": 0, "windows_kept": 0}
    if len(ms) < 2:
        return np.zeros((0, WIN, 6)), [], d
    t0 = max(t_start, ms[0])
    t1 = min(t_end, ms[-1])
    if t1 <= t0:
        return np.zeros((0, WIN, 6)), [], d
    grid = t0 + STEP_MS * np.arange(int(np.floor((t1 - t0) / STEP_MS)) + 1)
    i1 = np.clip(np.searchsorted(ms, grid, side="left"), 0, len(ms) - 1)
    exact = ms[i1] == grid
    i0 = np.where(exact, i1, np.maximum(i1 - 1, 0))
    gap = ms[i1] - ms[i0]
    valid = gap <= MAX_GAP_MS
    d["grid_points"], d["grid_invalid_gap"] = int(len(grid)), int((~valid).sum())
    sig = np.column_stack([acc_g, gyr_rads])
    out = np.column_stack([np.interp(grid, ms, sig[:, c]) for c in range(6)])
    W, starts = [], []
    nwin = (len(grid) - WIN) // STRIDE + 1 if len(grid) >= WIN else 0
    d["windows_possible"] = int(nwin)
    for k in range(nwin):
        a, b = k * STRIDE, k * STRIDE + WIN
        if not valid[a:b].all():
            d["windows_dropped_gap"] += 1
            continue
        nobs = int(((ms >= grid[a]) & (ms <= grid[b - 1])).sum())
        if nobs < MIN_OBS:
            d["windows_dropped_undercoverage"] += 1
            continue
        W.append(out[a:b]); starts.append(float(grid[a]))
    d["windows_kept"] = len(W)
    return (np.stack(W) if W else np.zeros((0, WIN, 6))), starts, d


def main():
    md = DIO.metadata()
    md = md[(md["hasMotion"] == True) & (md["hasGNSS"] == True)].copy()  # noqa: E712
    tracks = []
    for _, r in md.iterrows():
        name = str(r["testName"])
        p = DIO.DATA / f"subject_{name.split('_')[0]}" / name
        mo, ev = DIO.read_csv(p / "motion.csv"), DIO.read_csv(p / "events.csv")
        if mo is None or ev is None:
            continue
        tracks.append((name, r, mo, ev))
    subjects = sorted({str(r["subject"]) for _, r, _, _ in tracks}, key=int)

    # ---- raw column checks (whole motion files) ----
    acc_cols, accg_cols, gy_cols = ["accelX", "accelY", "accelZ"], ["accelWithGX", "accelWithGY", "accelWithGZ"], PIPELINE["gyro_columns"]
    trk_rows, ts_issue = [], {"tracks_non_monotonic_ms": 0, "tracks_duplicate_ms": 0, "tracks_interval_col_ne_diff": 0}
    A, AG, GD, GV = [], [], [], []
    for name, r, mo, ev in tracks:
        ms = mo["ms"].to_numpy(float)
        dms = np.diff(ms)
        nonmono = int((dms < 0).sum()); dup = int((dms == 0).sum())
        ts_issue["tracks_non_monotonic_ms"] += nonmono > 0
        ts_issue["tracks_duplicate_ms"] += dup > 0
        a, ag, gy = (mo[c].to_numpy(float) for c in (acc_cols, accg_cols, gy_cols)) if False else (mo[acc_cols].to_numpy(float), mo[accg_cols].to_numpy(float), mo[gy_cols].to_numpy(float))
        t0, t1 = float(ev["testStart"].iloc[0]), float(ev["testEnd"].iloc[0])
        m = (ms >= t0) & (ms <= t1)
        am, agm, gm = np.linalg.norm(a, axis=1), np.linalg.norm(ag, axis=1), np.linalg.norm(gy, axis=1)
        gvec = np.linalg.norm(ag - a, axis=1)
        pos = dms[dms > 0]
        trk_rows.append({"track": name, "subject": int(r["subject"]), "device": r["device"], "os": os_of(r["device"]),
                         "app": r["smartphone app"], "speed_mps": float(r["average_walking_speed"]),
                         "n_rows": int(len(mo)), "n_in_walk": int(m.sum()), "nonmono": nonmono, "dup": dup,
                         "median_dt_ms": float(np.median(pos)) if len(pos) else None,
                         "mean_rate_hz": float(1000.0 * (len(ms) - 1) / (ms.max() - ms.min())) if ms.max() > ms.min() else None,
                         "max_gap_ms": float(dms.max()) if len(dms) else None,
                         "frac_dt_gt_100ms": float((dms > MAX_GAP_MS).mean()) if len(dms) else None,
                         "acc_mag_median": float(np.median(am[m])), "accG_mag_median": float(np.median(agm[m])),
                         "gravity_vec_mag_median": float(np.median(gvec[m])), "gyro_mag_median": float(np.median(gm[m])),
                         "accel_resolution_step": float(np.min(np.diff(np.unique(a[:, 0]))) if len(np.unique(a[:, 0])) > 1 else np.nan)})
        A.append(am[m]); AG.append(agm[m]); GD.append(gvec[m]); GV.append(gm[m])
    T = pd.DataFrame(trk_rows)
    A, AG, GD, GV = map(np.concatenate, (A, AG, GD, GV))
    # gravity consistency: accelWithG - accel should be a ~constant-magnitude 9.8 vector
    # (per-track direction stability measured as the std of unit-vector components)
    gdir_std = []
    for name, r, mo, ev in tracks:
        v = mo[accg_cols].to_numpy(float) - mo[acc_cols].to_numpy(float)
        u = v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)
        gdir_std.append(float(np.sqrt((np.diff(u, axis=0) ** 2).sum(1).mean() / 2)) if len(u) > 1 else np.nan)
    T["gravity_dir_step_rms"] = gdir_std

    imu = {
        "n_tracks": int(len(T)), "n_subjects": int(len(subjects)), "subjects": subjects,
        "track_selection": "metadata hasMotion==TRUE and hasGNSS==TRUE, non-empty motion.csv and events.csv",
        "samples_in_walk_interval": int(len(A)),
        "units": {
            "dryad_documentation": "Dryad API dataset record (datasets/dryad/docs/dryad_api_dataset.json) gives no unit for motion.csv columns (Verified by reading abstract/methods). "
                                   "Column names (accelWithG, rotRateAlpha/Beta/Gamma, interval) match the W3C DeviceMotionEvent API (acceleration, accelerationIncludingGravity in m/s^2, rotationRate alpha/beta/gamma in deg/s, interval in ms); "
                                   "the methods text says the first app is a web-application retrieving acceleration, rotation rate and orientation (Inferred mapping to DeviceMotionEvent).",
            "accelWithG_magnitude_g_units": q(AG / G), "accelWithG_magnitude_raw": q(AG),
            "accel_gravity_removed_magnitude_raw": q(A),
            "accelWithG_minus_accel_magnitude_raw": q(GD),
            "accel_unit_conclusion": "m/s^2 if accelWithG magnitude median is ~9.8 and the (accelWithG - accel) magnitude median is ~9.8 (see numbers; Verified from data)",
            "gravity_direction_step_rms_per_track": q(T["gravity_dir_step_rms"]),
        },
    }
    am_med, ag_med, gd_med = float(np.median(A)), float(np.median(AG)), float(np.median(GD))
    imu["units"]["accel_checks"] = {"median_accelWithG_mag": ag_med, "median_accelWithG_minus_accel_mag": gd_med,
                                     "median_accel_gravity_removed_mag": am_med,
                                     "accelWithG_is_m_per_s2": bool(9.0 <= ag_med <= 10.6),
                                     "accelWithG_minus_accel_is_gravity_vector": bool(9.0 <= gd_med <= 10.6)}

    # ---- training distributions (MotionSense, UCI HAR) ----
    Xms, Mms, _ = AD.load_motionsense()
    Xuci, Muci, _ = AD.load_uci()
    Fms, Fuci = extract_features(Xms), extract_features(Xuci)
    cls = AD.CLASSES
    train_gyro = {}
    for nm, X, M in (("MotionSense", Xms, Mms), ("UCI_HAR", Xuci, Muci)):
        gm = np.linalg.norm(X[:, :, 3:6], axis=2).ravel()
        am_ = np.linalg.norm(X[:, :, 0:3], axis=2).ravel()
        train_gyro[nm] = {"gyro_sample_mag_rad_s_all": q(gm), "acc_sample_mag_g_all": q(am_)}
        for c in cls:
            mk = (M["class_name"] == c).to_numpy()
            train_gyro[nm][c] = {"gyro_sample_mag_rad_s": q(np.linalg.norm(X[mk][:, :, 3:6], axis=2).ravel()),
                                 "acc_sample_mag_g": q(np.linalg.norm(X[mk][:, :, 0:3], axis=2).ravel())}

    # gyro unit evidence: per-track median |gyro| (raw), by OS, vs training walking medians
    raw_g = {o: q(g["gyro_mag_median"]) for o, g in T.groupby("os")}
    dev_med = T.groupby("device")["gyro_mag_median"].median().sort_values()
    ms_walk_med = train_gyro["MotionSense"]["WALKING"]["gyro_sample_mag_rad_s"]["p50"]
    uci_walk_med = train_gyro["UCI_HAR"]["WALKING"]["gyro_sample_mag_rad_s"]["p50"]
    dryad_raw_med = float(np.median(GV))
    imu["gyro_unit_evidence"] = {
        "dryad_gyro_mag_raw_all_walk_samples": q(GV),
        "dryad_gyro_mag_if_deg_per_s_to_rad_s": q(GV * DEG2RAD),
        "per_os_track_median_raw": raw_g,
        "per_device_track_median_raw_sorted": {k: float(v) for k, v in dev_med.items()},
        "device_median_max_over_min": float(dev_med.max() / dev_med.min()),
        "training_walking_gyro_sample_mag_rad_s_median": {"MotionSense": ms_walk_med, "UCI_HAR": uci_walk_med},
        "ratio_dryad_raw_median_to_MotionSense_walking_median": dryad_raw_med / ms_walk_med,
        "ratio_dryad_raw_median_to_UCI_walking_median": dryad_raw_med / uci_walk_med,
        "ratio_dryad_deg2rad_median_to_MotionSense_walking_median": dryad_raw_med * DEG2RAD / ms_walk_med,
        "ratio_dryad_deg2rad_median_to_UCI_walking_median": dryad_raw_med * DEG2RAD / uci_walk_med,
        "interpretation_rule": "If the data were rad/s, the raw Dryad median would be of the same order as the training walking median (ratio ~1). A ratio near 57.3 "
                               "means the values are in deg/s. Per-device spread >> 1 would indicate mixed units across devices.",
    }

    # ---- build windows ----
    model = joblib.load(ROOT / "ml" / "models" / "activity_combined_xgboost.joblib")
    drops, rows, Ws = [], [], []
    for name, r, mo, ev in tracks:
        ms = mo["ms"].to_numpy(float)
        acc_g = mo[acc_cols].to_numpy(float) / G
        gy = mo[gy_cols].to_numpy(float) * DEG2RAD
        W, starts, d = resample_windows(ms, acc_g, gy, float(ev["testStart"].iloc[0]), float(ev["testEnd"].iloc[0]))
        d.update(track=name)
        drops.append(d)
        for i, s in enumerate(starts):
            rows.append({"track": name, "subject": int(r["subject"]), "os": os_of(r["device"]), "device": r["device"],
                         "speed_bin": speed_bin(float(r["average_walking_speed"])), "app": r["smartphone app"], "win_start_ms": s})
        if len(W):
            Ws.append(W)
    X = np.concatenate(Ws)
    Wdf = pd.DataFrame(rows)
    F = extract_features(X)
    P = model.predict_proba(F)
    for k, c in enumerate(cls):
        Wdf[f"p_{c}"] = P[:, k]
    Wdf["pred"] = [cls[i] for i in P.argmax(1)]
    # diagnostic only: gyro left in deg/s (NOT the pipeline)
    X_raw = X.copy(); X_raw[:, :, 3:6] /= DEG2RAD
    Wdf["pred_if_gyro_unconverted"] = [cls[i] for i in model.predict_proba(extract_features(X_raw)).argmax(1)]
    Wdf = Wdf.round({f"p_{c}": 6 for c in cls}).round({"win_start_ms": 3})
    Wdf.to_csv(ROOT / "results" / "metrics" / "phase4_dryad_modelB_windows.csv", index=False)

    D = pd.DataFrame(drops)
    tot = {k: int(D[k].sum()) for k in D.columns if k != "track"}
    tot["tracks_with_zero_windows"] = int((D["windows_kept"] == 0).sum())
    imu["pipeline"] = PIPELINE
    imu["pipeline_drop_counts_total"] = tot
    imu["pipeline_drop_counts_per_track"] = D.set_index("track").to_dict("index")
    imu["timestamp_issues"] = {**{k: int(v) for k, v in ts_issue.items()},
                               "sampling": {"median_dt_ms_per_track": q(T["median_dt_ms"]), "mean_rate_hz_per_track": q(T["mean_rate_hz"]),
                                            "max_gap_ms_per_track": q(T["max_gap_ms"]), "frac_dt_gt_100ms_per_track": q(T["frac_dt_gt_100ms"])},
                               "lowest_mean_rate_tracks": T.nsmallest(8, "mean_rate_hz")[["track", "device", "mean_rate_hz", "median_dt_ms"]].to_dict("records"),
                               "tracks_with_dropped_windows": int(((D["windows_dropped_gap"] + D["windows_dropped_undercoverage"]) > 0).sum())}
    imu["resolution_note"] = "Dryad values are rounded to 0.1 (see accel_resolution_step); training data are not. Quantisation effect on features is not measured here (Inferred small for walking, may matter for stationary)."

    # ---- feature distributions ----
    def fq(Fm):
        return {n: {"p10": float(np.quantile(Fm[:, i], .1)), "median": float(np.median(Fm[:, i])), "p90": float(np.quantile(Fm[:, i], .9))} for i, n in enumerate(FEATURE_NAMES)}
    Fd_raw = extract_features(X_raw)
    fd = {"Dryad_all_windows_(genuine walking)": fq(F), "Dryad_all_windows_gyro_NOT_converted_(diagnostic)": fq(Fd_raw)}
    for nm, Fm, M in (("MotionSense", Fms, Mms), ("UCI_HAR", Fuci, Muci)):
        for c in cls:
            fd[f"{nm}_{c}"] = fq(Fm[(M["class_name"] == c).to_numpy()])
    ratio = {}
    for i, n in enumerate(FEATURE_NAMES):
        dm = float(np.median(F[:, i]))
        ratio[n] = {"dryad_median": dm,
                    "ratio_to_MotionSense_WALKING_median": dm / fd["MotionSense_WALKING"][n]["median"] if fd["MotionSense_WALKING"][n]["median"] else None,
                    "ratio_to_UCI_WALKING_median": dm / fd["UCI_HAR_WALKING"][n]["median"] if fd["UCI_HAR_WALKING"][n]["median"] else None}
    imu["feature_distributions"] = fd
    imu["feature_median_ratios_dryad_to_training_walking"] = ratio
    imu["training_sample_magnitudes"] = train_gyro
    imu["dryad_sample_magnitudes"] = {"acc_linear_mag_g": q(A / G), "gyro_mag_rad_s_after_conversion": q(GV * DEG2RAD)}

    # ---- Model B predictions on genuine walking ----
    def dist(df):
        n = len(df)
        return {"n_windows": int(n), **{c: float((df["pred"] == c).mean()) for c in cls},
                "mean_p_WALKING": float(df["p_WALKING"].mean())} if n else {"n_windows": 0}
    pred = {"overall": dist(Wdf),
            "overall_if_gyro_unconverted_diagnostic": {c: float((Wdf["pred_if_gyro_unconverted"] == c).mean()) for c in cls},
            "by_subject": {str(s): dist(g) for s, g in Wdf.groupby("subject")},
            "by_os": {s: dist(g) for s, g in Wdf.groupby("os")},
            "by_device": {s: dist(g) for s, g in Wdf.groupby("device")},
            "by_speed_bin_mps": {s: dist(g) for s, g in Wdf.groupby("speed_bin")},
            "by_app": {s: dist(g) for s, g in Wdf.groupby("app")},
            "by_subject_os_speed_note": "smartphone_position is 'hand held' for all 151 motion tracks (Verified), so no placement split exists"}
    per_track = {n: dist(g) for n, g in Wdf.groupby("track")}
    pred["by_track"] = per_track
    pred["frac_of_tracks_with_WALKING_share_lt_0.5"] = float(np.mean([v["WALKING"] < 0.5 for v in per_track.values()]))
    pred["frac_of_subjects_with_WALKING_share_lt_0.5"] = float(np.mean([v["WALKING"] < 0.5 for v in pred["by_subject"].values()]))
    imu["modelB_predictions_on_dryad_genuine_walking"] = pred
    imu["per_track_summary"] = T.round(6).to_dict("records")

    overall_walk = pred["overall"]["WALKING"]
    imu["model_files_sha256"] = {"activity_combined_xgboost.joblib": sha(ROOT / "ml/models/activity_combined_xgboost.joblib"),
                                 "activity_combined_xgboost.json": sha(ROOT / "ml/models/activity_combined_xgboost.json")}
    imu["verdict_inputs"] = {"overall_WALKING_share": overall_walk, "gyro_ratio_after_conversion_to_MS_walking": imu["gyro_unit_evidence"]["ratio_dryad_deg2rad_median_to_MotionSense_walking_median"]}
    out = ROOT / "results" / "metrics" / "phase4_dryad_imu_check.json"
    out.write_text(json.dumps(imu, indent=1, default=float), encoding="utf-8")
    print("tracks", len(T), "subjects", len(subjects), "windows", len(Wdf))
    print("accelWithG med", ag_med, "diff med", gd_med, "accel med", am_med)
    print("gyro raw med", dryad_raw_med, "ratio MS", imu["gyro_unit_evidence"]["ratio_dryad_raw_median_to_MotionSense_walking_median"], "dev spread", imu["gyro_unit_evidence"]["device_median_max_over_min"])
    print("drops", tot)
    print("pred", {k: pred["overall"][k] for k in cls}, "unconverted", pred["overall_if_gyro_unconverted_diagnostic"])


if __name__ == "__main__":
    main()
