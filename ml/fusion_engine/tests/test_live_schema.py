"""Schema/parser tests on the hand-written FORMAT-TEST-ONLY fixture. Not data; no metric comes from here."""
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "ml" / "fusion_engine"))
import ingest_live_logs as ING  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "FORMAT_TEST_ONLY_session"


def test_fixture_parses_and_builds_one_decision_window():
    S = ING.parse_session(FIX, "format_test")
    df, info = ING.build_session_signals(S, ING.load_model_b())
    assert len(df) == 1 and info["model_b_drops"]["windows_kept"] >= 2
    r = df.iloc[0]
    assert r.imu_n_windows == 2 and r.gps_present and r.physical_steps == 6
    assert abs(r.p_stationary + r.p_walking + r.p_other - 1) < 1e-6
    assert r.gps_path_m > 0 and r.gps_covered_s == pytest.approx(4.0)


def test_fixture_is_refused_for_real_splits():
    for split in ("calibration", "evaluation"):
        with pytest.raises(ING.SessionError):
            ING.parse_session(FIX, split)


def test_g_conversion_and_no_bridging_of_gaps():
    ms = np.arange(0, 6000, 20.0)
    acc = np.full((len(ms), 3), 9.80665) / ING.G
    assert np.allclose(acc, 1.0)
    W, starts, d = ING.imu_windows(ms, acc, ms, np.zeros((len(ms), 3)), 0.0, 6000.0)
    assert d["windows_kept"] == len(W) == 3
    keep = (ms < 1500) | (ms > 3500)   # 2 s hole in both streams
    W2, _, d2 = ING.imu_windows(ms[keep], acc[keep], ms[keep], np.zeros((keep.sum(), 3)), 0.0, 6000.0)
    assert d2["windows_dropped_gap"] >= 1 and len(W2) == 0


def test_gravity_included_accel_is_rejected(tmp_path):
    d = tmp_path / "s"
    shutil.copytree(FIX, d)
    a = pd.read_csv(d / "linear_accel.csv")
    a["z"] = a["z"] + 9.8
    a.to_csv(d / "linear_accel.csv", index=False)
    with pytest.raises(ING.SessionError, match="gravity"):
        ING.parse_session(d, "format_test")

