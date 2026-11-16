"""Shared read-only loaders for the Dryad walking dataset (Phase 2). Never writes to datasets/."""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "datasets" / "dryad" / "extracted" / "data"
SEED = 42


def read_csv(p):
    """DataFrame or None for absent/empty files (empty files contain only '""')."""
    if not p.exists() or p.stat().st_size <= 8:
        return None
    df = pd.read_csv(p)
    df = df.drop(columns=[c for c in df.columns if str(c).startswith("Unnamed")])
    return df if len(df) else None


def metadata():
    return pd.read_csv(DATA / "metadata_tracks.csv")


def load_track(name):
    """Return dict with events/positions/steps (raw row order preserved) for track folder name like '3_0'."""
    subj = name.split("_")[0]
    p = DATA / f"subject_{subj}" / name
    return {"events": read_csv(p / "events.csv"), "positions": read_csv(p / "positions.csv"),
            "steps": read_csv(p / "steps.csv")}


def model_a_tracks():
    """Tracks with metadata row, hasGNSS, non-empty positions and steps. Returns list of (name, meta_row)."""
    md = metadata()
    out = []
    for _, r in md.iterrows():
        if not bool(r["hasGNSS"]):
            continue
        name = str(r["testName"])
        t = load_track(name)
        if t["positions"] is None or t["steps"] is None or t["events"] is None:
            continue
        out.append((name, r))
    return out


def haversine_m(lat, lon):
    r = 6371000.0
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    dla, dlo = np.diff(la), np.diff(lo)
    a = np.sin(dla / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(dlo / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))
