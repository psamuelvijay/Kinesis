"""Phase 4 work item 4: parse live Android recording sessions (schema in docs/recording_protocol.md) and build the per-decision-window
input table of the frozen fusion engine. Real recordings only; this script never creates or perturbs data.

Session folder (same layout idea as docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md section 5; .csv or .csv.gz):
  session.json  linear_accel.csv  gyro.csv  step_counter.csv  location.csv  [step_detector.csv]  [events.csv]
Model B pipeline = the Dryad pipeline of ml/fusion_engine/dryad_imu_compat.py, applied to Android streams:
  TYPE_LINEAR_ACCELERATION m/s^2 -> g (/9.80665); TYPE_GYROSCOPE rad/s (no conversion, Android already reports rad/s);
  each stream is linearly interpolated onto one 50 Hz grid, a grid point is valid only if the two OBSERVED samples bracketing it are at most
  100 ms apart in BOTH streams (no interpolation across larger gaps); 128-sample windows, stride 64; a window with an invalid grid point or
  fewer than 64 observed samples per stream is dropped and counted; features = ml/feature_extraction/activity_features.extract_features;
  model = frozen ml/models/activity_combined_xgboost.joblib.
GPS cleaning = Phase 2 rules (finite, exact-duplicate drop, accuracy 0..50 m, teleport drop > 10 m/s, speed valid only if finite and >= 0,
  windows overlapping a gap > 10 s between kept fixes or without a fix / valid speed are absent -> engine reports INSUFFICIENT_DATA).
Decision windows: consecutive 5 s windows from the operator-entered start time to the operator-entered end time.
Ground truth comes from the experimenter's controlled setup (scenario code + ground_truth in session.json). Location.isMock is a SANITY
CHECK on the setup, never the label.

CLI:  python ml/fusion_engine/ingest_live_logs.py --check <session_dir>           parse one session, print summary, write nothing
      python ml/fusion_engine/ingest_live_logs.py --split calibration|evaluation  write results/metrics/phase4_live_signals_<split>.csv
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "feature_extraction"))
LIVE = ROOT / "datasets" / "live_recordings"

G = 9.80665
FS, WIN, STRIDE = 50, 128, 64
STEP_MS = 1000.0 / FS
MAX_GAP_MS = 100.0
MIN_OBS = 64
DECISION_MS = 5000.0
B_LAST_SAMPLE_MS = 127 * STEP_MS
GAP_MAX_S, CONF_MAX_M, TELEPORT_MPS = 10.0, 50.0, 10.0
CLASSES = ("WALKING", "STATIONARY", "OTHER")  # class codes 0,1,2 of the frozen Model B (ml/models/activity_training_config.json)
MIN_DURATION_S = 300.0

# scenario -> (name, ground_truth, mock location expected, expected engine state or None)
SCENARIOS = {
    "S1": ("genuine_walking_outdoor", "walking", False, "GENUINE_WALKING"),
    "S2": ("stationary_table_real_gps", "physically_stationary", False, "STATIONARY"),
    "S3": ("stationary_in_hand", "physically_stationary", False, "STATIONARY"),
    "S4": ("pocket_walking", "walking", False, "GENUINE_WALKING"),
    "S5": ("mock_location_phone_stationary", "physically_stationary", True, "SUSPICIOUS_GPS_MOVEMENT"),
    "S6": ("mock_location_while_walking_conflict", "walking", True, None),
    "S7": ("other_vehicle_stairs_jogging", "other", False, "UNCERTAIN"),
}
REQUIRED_META = ["session_id", "split", "scenario", "ground_truth", "subject_id", "device_model", "android_version", "boot_offset_ms",
                 "operator_start_utc_ms", "operator_end_utc_ms", "has_step_counter", "route_id", "placement"]
COLS = {"linear_accel": ["t_ns", "x", "y", "z"], "gyro": ["t_ns", "x", "y", "z"], "step_counter": ["t_ns", "cumulative"],
        "location": ["t_ns", "utc_ms", "provider", "lat", "lon", "accuracy", "speed", "is_mock"]}
SIGNAL_FIELDS = ["gps_speed_mps", "gps_displacement_m", "gps_covered_s", "gps_coverage_frac", "gps_path_m", "gps_conf_m",
                 "imu_n_windows", "p_stationary", "p_walking", "p_other", "physical_steps"]


class SessionError(Exception):
    """The session violates the schema or the setup sanity checks; it is rejected and reported, never repaired."""


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    la1, la2, lo1, lo2 = map(np.radians, (lat1, lat2, lon1, lon2))
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def read_stream(sdir, stem, required=True):
    for suf in (".csv", ".csv.gz"):
        p = Path(sdir) / (stem + suf)
        if p.exists():
            df = pd.read_csv(p)
            miss = [c for c in COLS.get(stem, ["t_ns"]) if c not in df.columns]
            if miss:
                raise SessionError(f"{p.name}: missing columns {miss}")
            return df, p
    if required:
        raise SessionError(f"missing {stem}.csv")
    return None, None


def _clean_time(df, tcol="t_ns"):
    df = df[np.isfinite(pd.to_numeric(df[tcol], errors="coerce"))].copy()
    df[tcol] = df[tcol].astype(float)
    df = df.sort_values(tcol, kind="stable")
    return df[~df[tcol].duplicated(keep="first")]


def parse_session(sdir, expected_split):
    """Parse and validate one session. Raises SessionError on any schema or sanity violation."""
    sdir = Path(sdir)
    mp = sdir / "session.json"
    if not mp.exists():
        raise SessionError("missing session.json")
    meta = json.loads(mp.read_text(encoding="utf-8"))
    if meta.get("format_test_only") and expected_split != "format_test":
        raise SessionError("format-test fixture: not data, never used for any metric")
    miss = [k for k in REQUIRED_META if k not in meta or meta[k] in (None, "")]
    if miss:
        raise SessionError(f"session.json missing {miss}")
    if meta["split"] != expected_split:
        raise SessionError(f"session.json split '{meta['split']}' != folder split '{expected_split}'")
    sc = SCENARIOS.get(meta["scenario"])
    if sc is None:
        raise SessionError(f"unknown scenario {meta['scenario']}")
    if meta["ground_truth"] != sc[1]:
        raise SessionError(f"ground_truth '{meta['ground_truth']}' does not match scenario {meta['scenario']} ({sc[1]})")
    if sc[2] and not meta.get("mock_app_name"):
        raise SessionError("mock scenario without mock_app_name")
    off = float(meta["boot_offset_ms"])
    a0, b0 = float(meta["operator_start_utc_ms"]) - off, float(meta["operator_end_utc_ms"]) - off  # elapsed-realtime ms
    if not (b0 - a0 >= DECISION_MS):
        raise SessionError("operator end time is less than one decision window after the start time")
    warnings = []
    if b0 - a0 < MIN_DURATION_S * 1000:
        warnings.append(f"duration {(b0 - a0) / 1000:.0f} s is below the protocol minimum {MIN_DURATION_S:.0f} s")

    acc, p_acc = read_stream(sdir, "linear_accel")
    gyr, p_gyr = read_stream(sdir, "gyro")
    stp, p_stp = read_stream(sdir, "step_counter", required=bool(meta["has_step_counter"]))
    loc, p_loc = read_stream(sdir, "location")
    _, p_det = read_stream(sdir, "step_detector", required=False)
    acc, gyr = _clean_time(acc), _clean_time(gyr)
    for nm, d in (("linear_accel", acc), ("gyro", gyr)):
        d[["x", "y", "z"]] = d[["x", "y", "z"]].apply(pd.to_numeric, errors="coerce")
        d.dropna(subset=["x", "y", "z"], inplace=True)
        if len(d) < 2:
            raise SessionError(f"{nm}: fewer than 2 valid rows")
    # unit sanity: TYPE_LINEAR_ACCELERATION has gravity removed (stationary ~0 m/s^2); TYPE_ACCELEROMETER would give ~9.8
    inb = (acc.t_ns / 1e6 >= a0) & (acc.t_ns / 1e6 <= b0)
    if inb.sum() < 2:
        raise SessionError("linear_accel has no rows inside the operator start/end interval (clock mismatch?)")
    am = float(np.median(np.linalg.norm(acc.loc[inb, ["x", "y", "z"]].to_numpy(float), axis=1)))
    if am > 5.0:
        raise SessionError(f"linear_accel median magnitude {am:.2f} m/s^2 > 5: gravity seems included (not TYPE_LINEAR_ACCELERATION)")
    gm = float(np.median(np.linalg.norm(gyr.loc[(gyr.t_ns / 1e6 >= a0) & (gyr.t_ns / 1e6 <= b0), ["x", "y", "z"]].to_numpy(float), axis=1)))
    if gm > 15.0:
        raise SessionError(f"gyro median magnitude {gm:.2f} > 15: not rad/s")

    # location: GPS provider rows only
    prov = str(meta.get("gps_provider", "gps")).lower()
    loc = loc[loc["provider"].astype(str).str.lower() == prov].copy()
    if loc.empty:
        raise SessionError(f"location.csv has no rows with provider '{prov}'")
    loc["t_ms"] = pd.to_numeric(loc["t_ns"], errors="coerce") / 1e6
    clock = "elapsed_ns"
    inwin = ((loc.t_ms >= a0 - 30000) & (loc.t_ms <= b0 + 30000)).mean()
    if inwin < 0.9:
        utc = pd.to_numeric(loc["utc_ms"], errors="coerce")
        if utc.notna().mean() < 0.9:
            raise SessionError("location t_ns is not on the sensor clock and utc_ms is unusable")
        loc["t_ms"] = utc - off
        clock = "utc_ms_minus_boot_offset (location t_ns not on the sensor clock)"
        warnings.append("location clock fallback used")
    mock = loc["is_mock"].astype(str).str.strip().str.lower().isin(("1", "true", "t", "yes"))
    lb = (loc.t_ms >= a0) & (loc.t_ms <= b0)
    mock_frac = float(mock[lb].mean()) if lb.any() else float("nan")
    if not np.isfinite(mock_frac):
        raise SessionError("no GPS-provider location rows inside the operator interval")
    if sc[2] and mock_frac < 0.9:
        raise SessionError(f"mock scenario but only {mock_frac:.2f} of fixes flagged mock: setup/log mismatch")
    if (not sc[2]) and mock_frac > 0.01:
        raise SessionError(f"non-mock scenario but {mock_frac:.2f} of fixes flagged mock: setup/log mismatch")

    steps = None
    if meta["has_step_counter"]:
        steps = _clean_time(stp)
        steps = steps.assign(cumulative=pd.to_numeric(steps["cumulative"], errors="coerce")).dropna(subset=["cumulative"])
    return {"meta": meta, "scenario": sc, "a0": a0, "b0": b0, "acc": acc, "gyr": gyr, "loc": loc, "steps": steps, "mock_frac": mock_frac,
            "location_clock": clock, "warnings": warnings,
            "files_sha256": {p.name: sha256_file(p) for p in (mp, p_acc, p_gyr, p_loc, p_stp, p_det) if p is not None}}


# ---------------------------------------------------------------- Model B windows (same logic as dryad_imu_compat.resample_windows)
def _interp(ms, sig, grid):
    i1 = np.clip(np.searchsorted(ms, grid, side="left"), 0, len(ms) - 1)
    exact = ms[i1] == grid
    i0 = np.where(exact, i1, np.maximum(i1 - 1, 0))
    valid = (ms[i1] - ms[i0]) <= MAX_GAP_MS
    return np.column_stack([np.interp(grid, ms, sig[:, c]) for c in range(sig.shape[1])]), valid


def imu_windows(ms_a, acc_g, ms_g, gyr_rads, t_start, t_end):
    """(n,128,6) windows [acc g, gyro rad/s], their start ms, drop counts. Observed-only interpolation, no bridging of gaps > 100 ms."""
    d = {"grid_points": 0, "grid_invalid_gap": 0, "windows_possible": 0, "windows_dropped_gap": 0, "windows_dropped_undercoverage": 0, "windows_kept": 0}
    t0, t1 = max(t_start, ms_a[0], ms_g[0]), min(t_end, ms_a[-1], ms_g[-1])
    if t1 <= t0:
        return np.zeros((0, WIN, 6)), [], d
    grid = t0 + STEP_MS * np.arange(int(np.floor((t1 - t0) / STEP_MS)) + 1)
    oa, va = _interp(ms_a, acc_g, grid)
    og, vg = _interp(ms_g, gyr_rads, grid)
    valid, out = va & vg, np.hstack([oa, og])
    d["grid_points"], d["grid_invalid_gap"] = int(len(grid)), int((~valid).sum())
    nwin = (len(grid) - WIN) // STRIDE + 1 if len(grid) >= WIN else 0
    d["windows_possible"] = int(nwin)
    W, starts = [], []
    for k in range(nwin):
        a, b = k * STRIDE, k * STRIDE + WIN
        if not valid[a:b].all():
            d["windows_dropped_gap"] += 1
            continue
        na = int(((ms_a >= grid[a]) & (ms_a <= grid[b - 1])).sum())
        ng = int(((ms_g >= grid[a]) & (ms_g <= grid[b - 1])).sum())
        if min(na, ng) < MIN_OBS:
            d["windows_dropped_undercoverage"] += 1
            continue
        W.append(out[a:b]); starts.append(float(grid[a]))
    d["windows_kept"] = len(W)
    return (np.stack(W) if W else np.zeros((0, WIN, 6))), starts, d


def load_model_b():
    import joblib
    return joblib.load(ROOT / "ml" / "models" / "activity_combined_xgboost.joblib")


def model_b_probs(S, model):
    """Returns DataFrame(win_start_ms, p_walking, p_stationary, p_other) and drop counts."""
    from activity_features import extract_features
    ms_a, ms_g = S["acc"].t_ns.to_numpy(float) / 1e6, S["gyr"].t_ns.to_numpy(float) / 1e6
    acc_g = S["acc"][["x", "y", "z"]].to_numpy(float) / G
    gyr = S["gyr"][["x", "y", "z"]].to_numpy(float)
    W, starts, d = imu_windows(ms_a, acc_g, ms_g, gyr, S["a0"], S["b0"])
    if len(W) == 0:
        return pd.DataFrame(columns=["win_start_ms", "p_walking", "p_stationary", "p_other"]), d
    P = model.predict_proba(extract_features(W))
    return pd.DataFrame({"win_start_ms": starts, "p_walking": P[:, 0], "p_stationary": P[:, 1], "p_other": P[:, 2]}), d


# ---------------------------------------------------------------- GPS cleaning (Phase 2 rules)
def teleport_drop(p):
    n0 = len(p)
    p = p.reset_index(drop=True)
    while len(p) > 2:
        dist = hav(p.lat.values[:-1], p.lon.values[:-1], p.lat.values[1:], p.lon.values[1:])
        v = dist / np.maximum(np.diff(p.t_ms.values) / 1000.0, 1.0)
        bad_link = v > TELEPORT_MPS
        bad = np.r_[True, bad_link] & np.r_[bad_link, True] & (np.r_[False, bad_link] | np.r_[bad_link, False])
        if not bad.any():
            break
        score = np.r_[0, v] + np.r_[v, 0]
        score[~bad] = -1
        p = p.drop(index=int(np.argmax(score))).reset_index(drop=True)
    return p, n0 - len(p)


def clean_gps(loc):
    c = {"rows": int(len(loc))}
    p = loc.copy()
    for col in ("lat", "lon", "accuracy", "speed"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
    p = p[np.isfinite(p[["t_ms", "lat", "lon"]].to_numpy(float)).all(axis=1)]
    c["c1_nonfinite"] = c["rows"] - len(p)
    p = p.sort_values("t_ms", kind="stable")
    n = len(p)
    p = p.drop_duplicates(subset=["t_ms", "lat", "lon", "accuracy", "speed"])
    c["c2_dup"] = n - len(p)
    ok = p.accuracy.notna() & (p.accuracy >= 0) & (p.accuracy <= CONF_MAX_M)
    c["c3_accuracy_missing_or_gt_50m"] = int((~ok).sum())
    p = p[ok]
    p, c["c4_teleport"] = teleport_drop(p)
    p = p.assign(speed_ok=(p.speed.notna() & (p.speed >= 0)).to_numpy())
    c["kept"] = int(len(p))
    c["kept_speed_invalid"] = int((~p.speed_ok).sum()) if len(p) else 0
    return p, c


def build_session_signals(S, model):
    """One row per 5 s decision window with the engine inputs plus bookkeeping columns."""
    a0, b0, meta = S["a0"], S["b0"], S["meta"]
    gps, gps_counts = clean_gps(S["loc"])
    B, imu_drops = model_b_probs(S, model)
    t = gps.t_ms.values.astype(float)
    gaps = [(t[i], t[i + 1]) for i in np.where(np.diff(t) / 1000.0 > GAP_MAX_S)[0]] if len(t) > 1 else []
    link = np.zeros(len(t))  # path of links ending at fix i (previous fix <= GAP_MAX_S away), attributed to the window of fix i
    if len(t) > 1:
        d = hav(gps.lat.values[:-1], gps.lon.values[:-1], gps.lat.values[1:], gps.lon.values[1:])
        link[1:] = np.where(np.diff(t) / 1000.0 <= GAP_MAX_S, d, 0.0)
    bs = B.win_start_ms.to_numpy(float)
    bp = B[["p_stationary", "p_walking", "p_other"]].to_numpy(float)
    if S["steps"] is not None and len(S["steps"]):
        sm, sv = S["steps"].t_ns.to_numpy(float) / 1e6, np.maximum.accumulate(S["steps"].cumulative.to_numpy(float))
        cum = lambda x: float(sv[0] if np.searchsorted(sm, x, side="right") == 0 else sv[np.searchsorted(sm, x, side="right") - 1])  # noqa: E731
    elif S["steps"] is not None:
        cum = lambda x: 0.0  # noqa: E731  has_step_counter true and no change event: counter never changed
    else:
        cum = None
    rows = []
    for k in range(int(np.floor((b0 - a0) / DECISION_MS))):
        a, b = a0 + k * DECISION_MS, a0 + (k + 1) * DECISION_MS
        sel = (bs >= a) & (bs + B_LAST_SAMPLE_MS <= b)
        n = int(sel.sum())
        pm = bp[sel].mean(axis=0) if n else (np.nan, np.nan, np.nan)
        r = dict(session_id=meta["session_id"], scenario=meta["scenario"], subject_id=meta["subject_id"], device_model=meta["device_model"],
                 win_idx=k, t_rel_s=k * 5.0, imu_n_windows=n, p_stationary=pm[0], p_walking=pm[1], p_other=pm[2],
                 physical_steps=(cum(b) - cum(a)) if cum else np.nan,
                 gps_speed_mps=np.nan, gps_displacement_m=np.nan, gps_covered_s=np.nan, gps_coverage_frac=np.nan, gps_path_m=np.nan,
                 gps_conf_m=np.nan, gps_present=False, gps_link_path_m=0.0)
        m = (t >= a) & (t < b)
        r["gps_link_path_m"] = float(link[m].sum()) if m.any() else 0.0
        if not any(g0 < b and g1 > a for g0, g1 in gaps) and m.any():
            w = gps[m]
            v = w.speed[w.speed_ok].to_numpy(float)
            if len(v):
                one = len(w) < 2
                cov = (w.t_ms.values[-1] - w.t_ms.values[0]) / 1000.0
                r.update(gps_present=True, gps_speed_mps=float(np.median(v)), gps_conf_m=float(w.accuracy.mean()),
                         gps_covered_s=cov, gps_coverage_frac=cov / (DECISION_MS / 1000.0),
                         gps_path_m=np.nan if one else float(hav(w.lat.values[:-1], w.lon.values[:-1], w.lat.values[1:], w.lon.values[1:]).sum()),
                         gps_displacement_m=np.nan if one else float(hav(w.lat.values[0], w.lon.values[0], w.lat.values[-1], w.lon.values[-1])))
        rows.append(r)
    info = {"session_id": meta["session_id"], "scenario": meta["scenario"], "subject_id": meta["subject_id"], "device_model": meta["device_model"],
            "android_version": meta["android_version"], "duration_s": (b0 - a0) / 1000.0, "n_decision_windows": len(rows),
            "gps_cleaning": gps_counts, "model_b_drops": imu_drops, "mock_fraction_of_fixes": S["mock_frac"],
            "location_clock": S["location_clock"], "warnings": S["warnings"], "files_sha256": S["files_sha256"]}
    return pd.DataFrame(rows), info


def engine_inputs(df):
    return [{k: (None if (isinstance(v, float) and math.isnan(v)) else v) for k, v in r.items()} for r in df[SIGNAL_FIELDS].to_dict("records")]


def scan_split(split):
    """Parse every session folder of datasets/live_recordings/<split>. Returns (signals DataFrame or None, infos, rejected)."""
    base = LIVE / split
    dirs = sorted(p for p in base.iterdir() if p.is_dir()) if base.exists() else []
    model, frames, infos, rejected = None, [], [], []
    for d in dirs:
        try:
            S = parse_session(d, split)
            model = model or load_model_b()
            df, info = build_session_signals(S, model)
            frames.append(df); infos.append(info)
        except SessionError as e:
            rejected.append({"session_dir": d.name, "reason": str(e)})
    return (pd.concat(frames, ignore_index=True) if frames else None), infos, rejected


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", help="parse one session folder and print a summary (writes nothing)")
    g.add_argument("--split", choices=["calibration", "evaluation"])
    ap.add_argument("--as-split", default=None, help="with --check: expected split value (default: value in session.json)")
    a = ap.parse_args()
    if a.check:
        meta = json.loads((Path(a.check) / "session.json").read_text(encoding="utf-8"))
        S = parse_session(a.check, a.as_split or meta["split"])
        df, info = build_session_signals(S, load_model_b())
        print(json.dumps(info, indent=1, default=float)); print(df.to_string())
        return
    df, infos, rejected = scan_split(a.split)
    if df is None:
        print(f"PENDING USER DATA: no valid sessions in datasets/live_recordings/{a.split}/ (rejected: {len(rejected)})")
        for r in rejected:
            print(" rejected", r)
        return
    out = ROOT / "results" / "metrics" / f"phase4_live_signals_{a.split}.csv"
    df.round(6).to_csv(out, index=False)
    (ROOT / "results" / "metrics" / f"phase4_live_ingest_{a.split}.json").write_text(json.dumps({"sessions": infos, "rejected": rejected}, indent=1, default=float), encoding="utf-8")
    print(f"{len(infos)} sessions, {len(df)} decision windows, {len(rejected)} rejected -> {out.name}")


if __name__ == "__main__":
    main()
