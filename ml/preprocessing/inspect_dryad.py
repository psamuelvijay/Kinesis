"""Inspect the Dryad walking dataset (read-only). Reads extracted CSVs from datasets/dryad/extracted/data
(extracted from the untouched raw/Data.zip). Writes results/metrics/inspect_dryad.json.
Layout: data/metadata_tracks.csv, data/subject_<S>/<S>_<N>/{events,positions,motion,orientation,steps}.csv
(+ reference_cont_distance.csv for 'continuous' ground truth tracks). All times are ms relative to a per-track signalStart (no absolute clock).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets" / "dryad" / "extracted" / "data"
OUT = ROOT / "results" / "metrics" / "inspect_dryad.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

if not (DATA / "metadata_tracks.csv").exists():
    OUT.write_text(json.dumps({"dataset": "Dryad walking activity dataset", "status": "unavailable",
        "reason": "datasets/dryad/extracted/data not found; extract raw/Data.zip first", "n_tracks": None}, indent=2))
    raise SystemExit("extracted data not found")

def read(p):
    """Return DataFrame or None for absent/empty files (empty files contain only '""')."""
    if not p.exists() or p.stat().st_size <= 8:
        return None
    df = pd.read_csv(p)
    df = df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed")])
    return df if len(df) else None

def rate(ms):
    ms = np.sort(ms.dropna().values.astype(float))
    if len(ms) < 3: return None
    d = np.diff(ms)
    pos = d[d > 0]
    return {"n": int(len(ms)), "duplicates": int((d == 0).sum()), "median_dt_ms": float(np.median(pos)),
            "median_hz": float(1000 / np.median(pos)), "mean_hz": float((len(ms) - 1) / ((ms[-1] - ms[0]) / 1000)) if ms[-1] > ms[0] else None,
            "max_gap_s": float(d.max() / 1000), "span_s": float((ms[-1] - ms[0]) / 1000)}

def hav(lat, lon):
    r = 6371000.0
    la, lo = np.radians(lat), np.radians(lon)
    dla, dlo = np.diff(la), np.diff(lo)
    a = np.sin(dla / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(dlo / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))

md = pd.read_csv(DATA / "metadata_tracks.csv")
res = {"dataset": "Dryad walking activity dataset", "status": "available"}
res["metadata_tracks"] = {"rows": len(md), "columns": list(md.columns), "dtypes": {c: str(t) for c, t in md.dtypes.items()},
    "missing_per_column": {c: int(md[c].isna().sum()) for c in md.columns},
    "n_subjects": int(md["subject"].nunique()), "tracks_per_subject": {str(k): int(v) for k, v in md.groupby("subject").size().items()},
    "hasMotion": {str(k): int(v) for k, v in md["hasMotion"].value_counts().items()},
    "hasGNSS": {str(k): int(v) for k, v in md["hasGNSS"].value_counts().items()},
    "has_motion_x_has_gnss": {f"motion={a},gnss={b}": int(((md.hasMotion == a) & (md.hasGNSS == b)).sum()) for a in (True, False) for b in (True, False)},
    "gt_type": md["gt_type"].value_counts().to_dict(), "country": md["country"].value_counts().to_dict(),
    "gnss_anonimized": {str(k): int(v) for k, v in md["gnss_anonimized"].value_counts().items()},
    "smartphone_app": md["smartphone app"].value_counts().to_dict(), "devices": md["device"].value_counts().to_dict(),
    "isPatient": {str(k): int(v) for k, v in md["isPatient"].value_counts().items()},
    "numeric_summary": {c: {k: (None if pd.isna(v) else float(v)) for k, v in md[c].describe().items()} for c in
        ["distanceReference", "duration [s]", "fs_acc", "fs_gnss", "fs_steps", "average_walking_speed", "totSteps", "total_gaps_time_gnss", "total_gaps_time_inertial"]}}

folders = sorted(p for p in DATA.glob("subject_*/*_*") if p.is_dir())
meta_names = set(md["testName"].astype(str))
folder_names = {p.name for p in folders}
res["folders_total"] = len(folders)
res["folders_not_in_metadata"] = sorted(folder_names - meta_names)
res["metadata_tracks_without_folder"] = sorted(meta_names - folder_names)
res["column_schemas"] = {}
tracks = {}
for p in folders:
    name = p.name
    m = md[md["testName"].astype(str) == name]
    ev, pos, st, mo, ori = (read(p / f) for f in ["events.csv", "positions.csv", "steps.csv", "motion.csv", "orientation.csv"])
    refc = read(p / "reference_cont_distance.csv")
    for key, df in [("events", ev), ("positions", pos), ("steps", st), ("motion", mo), ("orientation", ori), ("reference_cont_distance", refc)]:
        if df is not None and key not in res["column_schemas"]:
            res["column_schemas"][key] = {"columns": list(df.columns), "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
    t = {"in_metadata": len(m) == 1}
    if len(m) == 1:
        r = m.iloc[0]
        t.update(subject=int(r["subject"]), hasMotion=bool(r["hasMotion"]), hasGNSS=bool(r["hasGNSS"]), distanceReference=float(r["distanceReference"]),
                 duration_s=float(r["duration [s]"]), totSteps_meta=None if pd.isna(r["totSteps"]) else float(r["totSteps"]), gt_type=r["gt_type"], gnss_anonimized=bool(r["gnss_anonimized"]))
    t["files"] = {"positions": None if pos is None else len(pos), "steps": None if st is None else len(st), "motion": None if mo is None else len(mo),
                  "orientation": None if ori is None else len(ori), "reference_cont_distance": None if refc is None else len(refc)}
    ts = te = None
    if ev is not None:
        ts, te = float(ev["testStart"].iloc[0]), float(ev["testEnd"].iloc[0]); t["events"] = {"testStart_ms": ts, "testEnd_ms": te}
    if pos is not None:
        valid = pos.dropna(subset=["latitude", "longitude"])
        sp = pos["speed"]
        t["positions"] = {"rows": len(pos), "rows_valid_latlon": len(valid), "speed_missing": int(sp.isna().sum()), "speed_negative": int((sp < 0).sum()),
                          "speed_valid": int((sp >= 0).sum()), "speed_valid_max": None if (sp >= 0).sum() == 0 else float(sp[sp >= 0].max()),
                          "missing": {c: int(pos[c].isna().sum()) for c in pos.columns}, "ms_min": float(pos["ms"].min()), "ms_max": float(pos["ms"].max()),
                          "ms_monotonic": bool(pos["ms"].is_monotonic_increasing), "rate": rate(pos["ms"]),
                          "rate_valid_speed_rows": rate(pos.loc[sp >= 0, "ms"]), "n_unique_latlon": int(valid[["latitude", "longitude"]].drop_duplicates().shape[0])}
        if ts is not None: t["positions"]["rows_before_testStart"] = int((pos["ms"] < ts).sum())
        if len(valid) > 1:
            v = valid[valid["ms"] >= (ts if ts is not None else -1e18)]
            if len(v) > 1:
                t["positions"]["haversine_path_m_after_testStart"] = float(hav(v["latitude"].values, v["longitude"].values).sum())
    if st is not None:
        s = st["steps"]
        d = {"rows": len(st), "missing": {c: int(st[c].isna().sum()) for c in st.columns}, "steps_min": float(s.min()), "steps_max": float(s.max()), "steps_sum": float(s.sum()),
             "steps_last": float(s.iloc[-1]), "steps_monotonic_nondecreasing": bool(s.is_monotonic_increasing or (s.diff().dropna() >= 0).all()),
             "startDate_unique": int(st["startDate"].nunique()), "endDate_monotonic": bool((st["endDate"].diff().dropna() >= 0).all()),
             "endDate_minus_startDate_ms_median": float((st["endDate"] - st["startDate"]).median()), "ms_min": float(st["ms"].min()), "ms_max": float(st["ms"].max()),
             "endDate_max": float(st["endDate"].max()), "rate": rate(st["ms"]),
             "ms_minus_endDate_median": float((st["ms"] - st["endDate"]).median())}
        if ts is not None: d["endDate_max_minus_testEnd_ms"] = float(st["endDate"].max() - te)
        t["steps"] = d
    if mo is not None:
        t["motion"] = {"rows": len(mo), "missing": {c: int(mo[c].isna().sum()) for c in mo.columns}, "rate": rate(mo["ms"]),
                       "interval_col_median_ms": float(mo["interval"].median()) if "interval" in mo else None, "ms_min": float(mo["ms"].min()), "ms_max": float(mo["ms"].max())}
    if refc is not None:
        t["reference_cont"] = {"rows": len(refc), "last_distance_m": float(refc["distance"].iloc[-1])}
    tracks[name] = t
res["tracks"] = tracks

# usability and exclusion reasons
usable_A, usable_fusion, excl = [], [], {}
for name, t in tracks.items():
    why = []
    if not t["in_metadata"]: why.append("folder has no row in metadata_tracks.csv")
    else:
        if not t["hasGNSS"]: why.append("metadata hasGNSS=False")
    pp = t.get("positions")
    if pp is None: why.append("positions.csv empty")
    elif pp["rows_valid_latlon"] < 2: why.append("fewer than 2 positions with valid lat/lon")
    elif pp["speed_valid"] == 0: why.append("no valid GPS speed (all missing or -1)")
    if t.get("steps") is None: why.append("steps.csv empty")
    gps_step_ok = not why
    if gps_step_ok: usable_A.append(name)
    why_f = list(why)
    if t["in_metadata"] and not t["hasMotion"]: why_f.append("metadata hasMotion=False")
    if t.get("motion") is None: why_f.append("motion.csv empty")
    if not why_f: usable_fusion.append(name)
    excl[name] = {"model_A_reasons": why, "fusion_reasons": why_f}
res["usable_tracks_model_A_gps_and_steps"] = usable_A
res["usable_tracks_gps_motion_steps"] = usable_fusion
res["n_usable_model_A"] = len(usable_A); res["n_usable_gps_motion_steps"] = len(usable_fusion)
res["n_subjects_usable_model_A"] = len({tracks[n]["subject"] for n in usable_A if "subject" in tracks[n]})
res["n_subjects_usable_gps_motion_steps"] = len({tracks[n]["subject"] for n in usable_fusion if "subject" in tracks[n]})
res["excluded_tracks_model_A"] = {n: e["model_A_reasons"] for n, e in excl.items() if e["model_A_reasons"]}
res["excluded_tracks_fusion"] = {n: e["fusion_reasons"] for n, e in excl.items() if e["fusion_reasons"]}

def agg(vals):
    v = np.array([x for x in vals if x is not None], float)
    return None if len(v) == 0 else {"n": int(len(v)), "min": float(v.min()), "p25": float(np.percentile(v, 25)), "median": float(np.median(v)), "p75": float(np.percentile(v, 75)), "max": float(v.max())}
def over(names, *path):
    out = []
    for n in names:
        x = tracks[n]
        for k in path:
            x = None if x is None else x.get(k)
        out.append(x)
    return out
res["sampling_rates_summary_hz"] = {
    "gps_median_hz_over_usable_A_tracks": agg(over(usable_A, "positions", "rate", "median_hz")),
    "gps_mean_hz_over_usable_A_tracks": agg(over(usable_A, "positions", "rate", "mean_hz")),
    "gps_valid_speed_mean_hz": agg(over(usable_A, "positions", "rate_valid_speed_rows", "mean_hz")),
    "gps_max_gap_s": agg(over(usable_A, "positions", "rate", "max_gap_s")),
    "motion_median_hz_over_tracks_with_motion": agg([tracks[n]["motion"]["rate"]["median_hz"] for n in tracks if tracks[n].get("motion") and tracks[n]["motion"]["rate"]]),
    "motion_mean_hz_over_tracks_with_motion": agg([tracks[n]["motion"]["rate"]["mean_hz"] for n in tracks if tracks[n].get("motion") and tracks[n]["motion"]["rate"]]),
    "steps_mean_hz_over_usable_A_tracks": agg(over(usable_A, "steps", "rate", "mean_hz")),
    "steps_max_gap_s": agg(over(usable_A, "steps", "rate", "max_gap_s"))}

# steps.csv semantics and alignment
cum = [n for n in usable_A if tracks[n]["steps"]["steps_monotonic_nondecreasing"] and tracks[n]["steps"]["startDate_unique"] == 1]
res["steps_semantics"] = {
    "tracks_checked": len(usable_A),
    "steps_monotonic_and_single_startDate (cumulative-from-start pattern)": len(cum),
    "steps_monotonic_nondecreasing": sum(tracks[n]["steps"]["steps_monotonic_nondecreasing"] for n in usable_A),
    "steps_last_equals_totSteps_meta": sum(tracks[n]["steps"]["steps_last"] == tracks[n]["totSteps_meta"] for n in usable_A),
    "steps_sum_equals_totSteps_meta": sum(tracks[n]["steps"]["steps_sum"] == tracks[n]["totSteps_meta"] for n in usable_A),
    "steps_last_minus_meta": agg([tracks[n]["steps"]["steps_last"] - tracks[n]["totSteps_meta"] for n in usable_A if tracks[n]["totSteps_meta"] is not None]),
    "steps_sum_over_meta": agg([tracks[n]["steps"]["steps_sum"] / tracks[n]["totSteps_meta"] for n in usable_A if tracks[n]["totSteps_meta"]]),
    "ms_equals_endDate_rows_fraction": None, "rows_per_track": agg(over(usable_A, "steps", "rows")),
    "startDate_unique_per_track": agg(over(usable_A, "steps", "startDate_unique"))}
res["alignment"] = {
    "note": "All timestamps are ms from a per-track signalStart; no absolute clock or time zone exists in the data, so time-zone errors cannot occur but cross-device wall-clock sync is impossible.",
    "positions_ms_min_minus_testStart": agg([tracks[n]["positions"]["ms_min"] - tracks[n]["events"]["testStart_ms"] for n in usable_A if "events" in tracks[n]]),
    "positions_rows_before_testStart": agg(over(usable_A, "positions", "rows_before_testStart")),
    "steps_ms_min_minus_testStart": agg([tracks[n]["steps"]["ms_min"] - tracks[n]["events"]["testStart_ms"] for n in usable_A if "events" in tracks[n]]),
    "steps_endDate_max_minus_testEnd": agg(over(usable_A, "steps", "endDate_max_minus_testEnd_ms")),
    "positions_ms_max_minus_testEnd": agg([tracks[n]["positions"]["ms_max"] - tracks[n]["events"]["testEnd_ms"] for n in usable_A if "events" in tracks[n]]),
    "positions_ms_not_monotonic_tracks": [n for n in usable_A if not tracks[n]["positions"]["ms_monotonic"]],
    "haversine_path_over_distanceReference": agg([tracks[n]["positions"]["haversine_path_m_after_testStart"] / tracks[n]["distanceReference"] for n in usable_A if "haversine_path_m_after_testStart" in tracks[n]["positions"]]),
    "haversine_path_over_distanceReference_by_anonymized": {str(a): agg([tracks[n]["positions"]["haversine_path_m_after_testStart"] / tracks[n]["distanceReference"] for n in usable_A if tracks[n]["gnss_anonimized"] == a and "haversine_path_m_after_testStart" in tracks[n]["positions"]]) for a in (True, False)},
    "tracks_with_continuous_reference": sum(1 for n in tracks if tracks[n].get("reference_cont")),
}
OUT.write_text(json.dumps(res, indent=2, default=str))
summ = {k: v for k, v in res.items() if k not in ("tracks", "usable_tracks_model_A_gps_and_steps", "usable_tracks_gps_motion_steps")}
print(json.dumps(summ, indent=1, default=str))
