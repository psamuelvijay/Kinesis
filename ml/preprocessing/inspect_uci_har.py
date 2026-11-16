"""Inspect UCI HAR (read-only; reads nested zip in memory, writes results/metrics/inspect_uci_har.json)."""
import io, json, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "datasets" / "uci_har" / "raw" / "human_activity_recognition_using_smartphones.zip"
OUT = ROOT / "results" / "metrics" / "inspect_uci_har.json"
outer = zipfile.ZipFile(RAW)
inner = zipfile.ZipFile(io.BytesIO(outer.read("UCI HAR Dataset.zip")))
names = inner.namelist()
def rd(n):
    return pd.read_csv(io.BytesIO(inner.read(n)), sep=r"\s+", header=None, engine="c")
base = [n for n in names if n.endswith("activity_labels.txt")][0].rsplit("/", 1)[0]
labels = pd.read_csv(io.BytesIO(inner.read(f"{base}/activity_labels.txt")), sep=r"\s+", header=None)
lab = {int(a): b for a, b in zip(labels[0], labels[1])}
res = {"dataset": "UCI HAR", "activity_labels": lab, "splits": {}}
signals = ["body_acc", "body_gyro", "total_acc"]
for sp in ["train", "test"]:
    y = rd(f"{base}/{sp}/y_{sp}.txt")[0]; s = rd(f"{base}/{sp}/subject_{sp}.txt")[0]
    X = rd(f"{base}/{sp}/X_{sp}.txt")
    d = {"n_windows": len(y), "subjects": sorted(map(int, s.unique())), "n_subjects": int(s.nunique()),
         "label_counts": {lab[int(k)]: int(v) for k, v in y.value_counts().sort_index().items()},
         "X_shape": list(X.shape), "X_missing": int(X.isna().sum().sum()), "signals": {}}
    for sig in signals:
        for ax in "xyz":
            n = f"{base}/{sp}/Inertial Signals/{sig}_{ax}_{sp}.txt"
            a = rd(n)
            d["signals"][f"{sig}_{ax}"] = {"shape": list(a.shape), "missing": int(a.isna().sum().sum()),
                "min": float(a.values.min()), "max": float(a.values.max())}
    res["splits"][sp] = d
tr, te = res["splits"]["train"], res["splits"]["test"]
res["n_windows_total"] = tr["n_windows"] + te["n_windows"]
res["n_subjects_total"] = len(set(tr["subjects"]) | set(te["subjects"]))
res["subject_overlap_train_test"] = sorted(set(tr["subjects"]) & set(te["subjects"]))
res["window"] = {"samples": 128, "seconds": 2.56, "overlap": "50% (per documentation)"}
res["sampling_rate"] = {"measured_from_timestamps": None, "documented_hz": 50,
    "note": "No timestamps; 128 samples per 2.56 s window implies 50 Hz per documentation. Not independently measurable."}
feat = rd(f"{base}/features.txt") if False else None
res["units_note"] = "total_acc in g (includes gravity); body_acc in g (gravity removed by low-pass filter); body_gyro in rad/s. Per dataset README."
res["required_features"] = {"accel_xyz": True, "gyro_xyz": True, "labels": True, "subject_ids": True, "timestamps": False,
    "raw_signal_files": [f"{s}_{a}" for s in signals for a in "xyz"]}
res["note_windows_overlap"] = "Inertial Signals windows overlap 50%; raw continuous recordings are not provided. Subject-level splitting is required."
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(res, indent=2))
print(json.dumps({k: v for k, v in res.items() if k != "splits"}, indent=1))
for sp, d in res["splits"].items(): print(sp, d["n_windows"], d["n_subjects"], d["label_counts"], d["X_missing"])
