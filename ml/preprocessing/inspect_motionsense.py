"""Inspect MotionSense (read-only; reads zips in memory, writes results/metrics/inspect_motionsense.json)."""
import io, json, re, zipfile
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "datasets" / "motionsense" / "raw"
OUT = ROOT / "results" / "metrics" / "inspect_motionsense.json"
ZIPS = {"A_DeviceMotion": "A_DeviceMotion_data.zip", "B_Accelerometer": "B_Accelerometer_data.zip", "C_Gyroscope": "C_Gyroscope_data.zip"}
pat = re.compile(r"^(?:[^/]+/)?([a-z]{3})_(\d+)/sub_(\d+)\.csv$")

res = {"dataset": "MotionSense", "streams": {}}
trials = {}  # (stream) -> {(act,trial,sub): rows}
for key, fn in ZIPS.items():
    z = zipfile.ZipFile(RAW / fn)
    rows = {}; cols = None; dtypes = None; nan = {}; n_files = 0; total = 0; extra = 0
    for name in z.namelist():
        if name.startswith("__MACOSX") or not name.endswith(".csv"):
            continue
        m = pat.match(name)
        if not m:
            extra += 1; continue
        df = pd.read_csv(io.BytesIO(z.read(name)))
        act, tr, sub = m.group(1), int(m.group(2)), int(m.group(3))
        rows[(act, tr, sub)] = len(df)
        if cols is None:
            cols = list(df.columns); dtypes = {c: str(t) for c, t in df.dtypes.items()}
            nan = {c: 0 for c in cols}
        for c in cols:
            nan[c] += int(df[c].isna().sum())
        n_files += 1; total += len(df)
    trials[key] = rows
    res["streams"][key] = {"zip": fn, "csv_files": n_files, "unmatched_csv": extra, "total_rows": total,
        "columns": cols, "dtypes": dtypes, "missing_per_column": nan,
        "has_timestamp_column": any("time" in str(c).lower() for c in cols),
        "first_column_is_unnamed_index": str(cols[0]).startswith("Unnamed")}
keysets = [set(v) for v in trials.values()]
common = set.intersection(*keysets)
res["recordings_in_all_three_streams"] = len(common)
res["recordings_not_in_all_streams"] = sorted(map(list, set.union(*keysets) - common))
mism = [{"activity": k[0], "trial": k[1], "subject": k[2], "rows": {s: trials[s][k] for s in trials}} for k in sorted(common) if len({trials[s][k] for s in trials}) > 1]
res["recordings_with_row_count_mismatch_between_streams"] = mism
res["n_row_count_mismatch"] = len(mism)
res["max_abs_row_diff_A_vs_B_C"] = max([max(abs(m["rows"]["A_DeviceMotion"]-m["rows"][s]) for s in ("B_Accelerometer","C_Gyroscope")) for m in mism], default=0)
A = trials["A_DeviceMotion"]
res["activity_codes"] = sorted({k[0] for k in common})
res["subjects"] = sorted({k[2] for k in common})
res["n_subjects"] = len(res["subjects"])
res["trials_per_activity"] = {a: sorted({k[1] for k in common if k[0] == a}) for a in res["activity_codes"]}
res["recordings_per_activity"] = {a: sum(1 for k in common if k[0] == a) for a in res["activity_codes"]}
lens = pd.Series([A[k] for k in common])
res["rows_per_recording"] = {"min": int(lens.min()), "median": float(lens.median()), "max": int(lens.max())}
res["sampling_rate"] = {"measured_from_timestamps": None,
    "note": "No timestamp column in any file. 50 Hz is the documented rate (README) and cannot be verified from the data; only row counts are known.",
    "documented_hz": 50}
sub = pd.read_csv(RAW / "data_subjects_info.csv")
res["subjects_info"] = {"columns": list(sub.columns), "rows": len(sub), "missing": {c: int(sub[c].isna().sum()) for c in sub.columns},
    "gender_counts": {str(k): int(v) for k, v in sub["gender"].value_counts().items()}}
res["subjects_info_codes_match_recordings"] = sorted(sub["code"].tolist()) == res["subjects"]
res["required_features"] = {"accel_xyz": True, "accel_stream": "B_Accelerometer (x,y,z; per docs, total acceleration incl. gravity)",
    "gyro_xyz": True, "labels": True, "subject_ids": True, "timestamps": False}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(res, indent=2))
print(json.dumps({k: v for k, v in res.items() if k not in ("streams","recordings_with_row_count_mismatch_between_streams")}, indent=1))
for k, v in res["streams"].items(): print(k, v["csv_files"], v["total_rows"], v["columns"], v["missing_per_column"])


