"""Phase 3 Model B: window MotionSense and UCI HAR into 128-sample x 6-channel windows (read-only on raw data).

Channels (both datasets): linear acceleration x,y,z (g, gravity removed) then gyro x,y,z (rad/s).
 - MotionSense: A_DeviceMotion userAcceleration.x/y/z, rotationRate.x/y/z. Windowed by sample count, stride 64,
   within a recording only. 50 Hz is the documented rate; the files have no timestamp column, so it is assumed.
 - UCI HAR: Inertial Signals body_acc_x/y/z, body_gyro_x/y/z rows used directly (128 samples each, no resampling).
No total_acc, gravity.*, attitude.*, B_/C_ streams or 561-feature vectors are read as model inputs.
"""
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MS_ZIP = ROOT / "datasets" / "motionsense" / "raw" / "A_DeviceMotion_data.zip"
UCI_ZIP = ROOT / "datasets" / "uci_har" / "raw" / "human_activity_recognition_using_smartphones.zip"

WIN, STRIDE, FS_HZ = 128, 64, 50
CLASSES = ["WALKING", "STATIONARY", "OTHER"]  # integer code = index
MS_COLS = ["userAcceleration.x", "userAcceleration.y", "userAcceleration.z",
           "rotationRate.x", "rotationRate.y", "rotationRate.z"]
UCI_FILES = ["body_acc_x", "body_acc_y", "body_acc_z", "body_gyro_x", "body_gyro_y", "body_gyro_z"]
CHANNELS = ["acc_x_g", "acc_y_g", "acc_z_g", "gyro_x_rads", "gyro_y_rads", "gyro_z_rads"]

# original activity -> class name. Jogging and stairs are OTHER, never STATIONARY.
MS_LABEL_MAP = {"wlk": "WALKING", "sit": "STATIONARY", "std": "STATIONARY",
                "jog": "OTHER", "ups": "OTHER", "dws": "OTHER"}
UCI_ACTIVITIES = {1: "WALKING", 2: "WALKING_UPSTAIRS", 3: "WALKING_DOWNSTAIRS", 4: "SITTING", 5: "STANDING", 6: "LAYING"}
UCI_LABEL_MAP = {"WALKING": "WALKING", "SITTING": "STATIONARY", "STANDING": "STATIONARY", "LAYING": "STATIONARY",
                 "WALKING_UPSTAIRS": "OTHER", "WALKING_DOWNSTAIRS": "OTHER"}
# short names used for the original-activity diagnostic (both datasets)
ORIG_SHORT = {"wlk": "wlk", "sit": "sit", "std": "std", "jog": "jog", "ups": "ups", "dws": "dws",
              "WALKING": "wlk", "SITTING": "sit", "STANDING": "std", "LAYING": "lay",
              "WALKING_UPSTAIRS": "ups", "WALKING_DOWNSTAIRS": "dws"}
_PAT = re.compile(r"^(?:[^/]+/)?([a-z]{3})_(\d+)/sub_(\d+)\.csv$")


def class_code(name):
    return CLASSES.index(name)


def load_motionsense():
    """Return X (n,128,6) float32, meta DataFrame, and a preparation report dict."""
    z = zipfile.ZipFile(MS_ZIP)
    names = sorted(n for n in z.namelist() if not n.startswith("__MACOSX") and n.endswith(".csv") and _PAT.match(n))
    X, meta = [], []
    total_rows = used_rows = dropped_rows = short_recordings = 0
    for n in names:
        act, trial, sub = _PAT.match(n).group(1), int(_PAT.match(n).group(2)), int(_PAT.match(n).group(3))
        df = pd.read_csv(io.BytesIO(z.read(n)))
        assert (np.diff(df["Unnamed: 0"].to_numpy()) == 1).all(), f"non-consecutive row index in {n}"
        assert not df[MS_COLS].isna().any().any(), f"missing values in {n}"
        a = df[MS_COLS].to_numpy(dtype=np.float32)
        L = len(a)
        total_rows += L
        nw = (L - WIN) // STRIDE + 1 if L >= WIN else 0
        if nw == 0:
            short_recordings += 1
        used = (nw - 1) * STRIDE + WIN if nw else 0
        used_rows += used
        dropped_rows += L - used
        for k in range(nw):
            X.append(a[k * STRIDE:k * STRIDE + WIN])
            meta.append((act, trial, sub, k, k * STRIDE, f"ms_{act}_{trial}_{sub}"))
    X = np.stack(X)
    m = pd.DataFrame(meta, columns=["orig_activity", "trial", "subject", "win_idx", "start_row", "recording"])
    m["dataset"] = "MotionSense"
    m["class_name"] = m["orig_activity"].map(MS_LABEL_MAP)
    m["orig_short"] = m["orig_activity"].map(ORIG_SHORT)
    m["y"] = m["class_name"].map(class_code)
    rep = {"n_recordings": len(names), "rows_total": int(total_rows), "rows_in_windows_first_to_last_sample": int(used_rows),
           "rows_dropped_trailing_partial": int(dropped_rows), "recordings_shorter_than_window": int(short_recordings),
           "rows_reconcile": bool(used_rows + dropped_rows == total_rows), "n_windows": int(len(m)),
           "windowing": f"{WIN} samples, stride {STRIDE} (50% overlap), by sample count within one recording; trailing partial dropped",
           "streams_used": ["A_DeviceMotion"], "columns_used": MS_COLS,
           "sampling_rate_hz": FS_HZ, "sampling_rate_status": "documented, assumed; not measurable (no timestamp column)"}
    return X, m, rep


def _rd(zf, name):
    return pd.read_csv(io.BytesIO(zf.read(name)), sep=r"\s+", header=None, engine="c").to_numpy(dtype=np.float32)


def load_uci():
    """Return X (n,128,6), meta DataFrame (with 'split' = provided train/test), report dict."""
    o = zipfile.ZipFile(UCI_ZIP)
    zf = zipfile.ZipFile(io.BytesIO(o.read("UCI HAR Dataset.zip")))
    base = "UCI HAR Dataset"
    Xs, ms = [], []
    overlap_checks = overlap_ok = 0
    for sp in ["train", "test"]:
        chans = [_rd(zf, f"{base}/{sp}/Inertial Signals/{f}_{sp}.txt") for f in UCI_FILES]
        x = np.stack(chans, axis=2)  # (n,128,6)
        assert x.shape[1] == WIN and not np.isnan(x).any()
        y = _rd(zf, f"{base}/{sp}/y_{sp}.txt")[:, 0].astype(int)
        s = _rd(zf, f"{base}/{sp}/subject_{sp}.txt")[:, 0].astype(int)
        assert len(y) == len(s) == len(x)
        # verify the documented 50% overlap on consecutive rows of the same subject+activity (read-only check)
        for i in range(len(x) - 1):
            if s[i] == s[i + 1] and y[i] == y[i + 1]:
                overlap_checks += 1
                if np.array_equal(x[i, 64:, :], x[i + 1, :64, :]):
                    overlap_ok += 1
        m = pd.DataFrame({"subject": s, "orig_activity": [UCI_ACTIVITIES[v] for v in y], "split_provided": sp,
                          "row_in_split": np.arange(len(y))})
        Xs.append(x); ms.append(m)
    X = np.concatenate(Xs)
    m = pd.concat(ms, ignore_index=True)
    m["dataset"] = "UCI_HAR"
    m["class_name"] = m["orig_activity"].map(UCI_LABEL_MAP)
    m["orig_short"] = m["orig_activity"].map(ORIG_SHORT)
    m["y"] = m["class_name"].map(class_code)
    m["recording"] = "uci_" + m["split_provided"] + "_" + m["subject"].astype(str)
    rep = {"n_windows": int(len(m)), "windows_used_as_provided": True, "resampled": False,
           "columns_used": UCI_FILES, "sampling_rate_hz": FS_HZ,
           "sampling_rate_status": "documented 50 Hz per README; windows have no timestamps",
           "consecutive_same_subject_activity_row_pairs_checked": int(overlap_checks),
           "pairs_with_exact_50pct_overlap_second_half_equals_next_first_half": int(overlap_ok),
           "note": "Only the pairs where the exact overlap holds are verified overlapping; windows from the original ordering "
                   "are otherwise treated as overlapping within subject, so window counts overstate independent samples."}
    return X, m, rep
