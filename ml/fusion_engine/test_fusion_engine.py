"""pytest for the Phase 4 fusion engine: golden vectors (real windows), decision-table edge cases (literal logic inputs built from the
frozen thresholds, NOT data and NOT an attack dataset), persistence, determinism, freeze hashes, and repository rules.
Run: python -m pytest ml/fusion_engine/test_fusion_engine.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import engine  # noqa: E402

TH, TDOC = engine.load_thresholds(HERE / "thresholds.json")
GOLD = json.loads((HERE / "golden_vectors.json").read_text())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def base(**kw):
    """A clean 'genuine walking' input derived from the thresholds; kw overrides."""
    d = {"gps_speed_mps": TH["V_MOVE_MPS"] * 3, "gps_displacement_m": TH["V_MOVE_DISP_MPS"] * 3 * 5.0, "gps_covered_s": 5.0, "gps_coverage_frac": 1.0,
         "gps_path_m": 5.0, "gps_conf_m": 4.0, "imu_n_windows": 2, "p_stationary": 0.01, "p_walking": 0.98, "p_other": 0.01, "physical_steps": 9}
    d.update(kw)
    return d


@pytest.mark.parametrize("v", GOLD["single_window_vectors"], ids=lambda v: v["id"])
def test_golden_single(v):
    r = engine.decide_window(v["input"], TH)
    assert r["state"] == v["expected"]["state"]
    assert r["reason"] == v["expected"]["reason"]
    assert r["movement_accepted"] == v["expected"]["movement_accepted"]
    assert r.get("explanation") == v["expected"]["explanation"]


def test_golden_sequence():
    for s in GOLD["sequence_vectors"]:
        res = engine.run_sequence(s["inputs"], TH, s["persistence_N"])
        assert [r["state"] for r in res] == s["expected_raw_states"]
        assert [r["reported_state"] for r in res] == s["expected_reported_states"]
        assert [r["movement_flagged"] for r in res] == s["expected_movement_flagged"]


def test_golden_covers_every_state():
    states = {v["expected"]["state"] for v in GOLD["single_window_vectors"]}
    assert states == set(engine.STATES)


def test_deterministic():
    seq = GOLD["sequence_vectors"][0]["inputs"]
    assert engine.run_sequence(seq, TH) == engine.run_sequence(seq, TH)


# ---- decision table edge cases ----
def test_genuine_walking():
    assert engine.decide_window(base(), TH)["state"] == "GENUINE_WALKING"


def test_suspicious_has_full_explanation():
    r = engine.decide_window(base(p_stationary=0.99999, p_walking=0.000005, p_other=0.000005, physical_steps=0), TH, recent_path_m=(4.0,))
    assert r["state"] == "SUSPICIOUS_GPS_MOVEMENT" and r["movement_accepted"] is False
    e = r["explanation"]
    for k in ("gps_speed_mps", "gps_distance_trend_m", "imu_activity", "physical_steps", "rule_triggered", "thresholds", "movement_accepted"):
        assert k in e
    assert e["movement_accepted"] is False and e["gps_distance_trend_m"] == pytest.approx(9.0)


def test_stationary_jitter_below_thresholds_is_not_suspicious():
    r = engine.decide_window(base(gps_speed_mps=0.0, gps_displacement_m=0.0, p_stationary=0.99999, p_walking=0.000005, p_other=0.000005, physical_steps=0), TH)
    assert r["state"] == "STATIONARY" and r["movement_accepted"] is None


def test_speed_without_displacement_is_uncertain_drift():
    r = engine.decide_window(base(gps_displacement_m=0.0, p_stationary=0.99999, p_walking=0.000005, p_other=0.000005, physical_steps=0), TH)
    assert r["state"] == "UNCERTAIN" and r["reason"] == "gps_speed_displacement_disagree"


def test_vehicle_speed_never_suspicious():
    sp = TH["V_WALK_MAX_MPS"] * 5
    r = engine.decide_window(base(gps_speed_mps=sp, gps_displacement_m=sp * 5, p_stationary=0.99999, p_walking=0.000005, p_other=0.000005, physical_steps=0), TH)
    assert r["state"] == "UNCERTAIN" and r["reason"] == "gps_speed_above_walking_envelope"


@pytest.mark.parametrize("probs", [(0.1, 0.1, 0.8)])
def test_other_activity_stairs_jog_hand_is_uncertain(probs):
    r = engine.decide_window(base(p_stationary=probs[0], p_walking=probs[1], p_other=probs[2]), TH)
    assert r["state"] == "UNCERTAIN" and r["reason"] == "imu_other_activity"


def test_gps_moving_steps_present_imu_stationary_disagree():
    r = engine.decide_window(base(p_stationary=0.99999, p_walking=0.000005, p_other=0.000005, physical_steps=9), TH)
    assert r["state"] == "UNCERTAIN"


def test_walking_without_steps_is_uncertain():
    assert engine.decide_window(base(physical_steps=0), TH)["state"] == "UNCERTAIN"


def test_poor_accuracy_gap_and_missing_are_insufficient():
    assert engine.decide_window(base(gps_conf_m=TH["ACC_MAX_M"] + 1), TH)["state"] == "INSUFFICIENT_DATA"
    assert engine.decide_window(base(gps_coverage_frac=0.0, gps_covered_s=0.0), TH)["state"] == "INSUFFICIENT_DATA"
    assert engine.decide_window(base(p_walking=None), TH)["state"] == "INSUFFICIENT_DATA"
    assert engine.decide_window(base(imu_n_windows=0), TH)["state"] == "INSUFFICIENT_DATA"
    assert engine.decide_window(base(physical_steps=None), TH)["state"] == "INSUFFICIENT_DATA"


def test_persistence():
    S, G, U = "SUSPICIOUS_GPS_MOVEMENT", "GENUINE_WALKING", "UNCERTAIN"
    assert engine.apply_persistence([S, S, S], 2) == [U, S, S]
    assert engine.apply_persistence([G, G, S, G, G], 2) == [U, G, G, G, G]
    assert engine.apply_persistence([G, G, S, S, G], 2) == [U, G, G, S, S]
    assert engine.apply_persistence([S, S, U, S], 2) == [U, S, U, U]
    assert engine.apply_persistence([S, S, "INSUFFICIENT_DATA"], 2)[-1] == "INSUFFICIENT_DATA"


def test_aggregate_mean():
    a = engine.aggregate_model_b([(0.2, 0.7, 0.1), (0.4, 0.5, 0.1)])
    assert a["imu_n_windows"] == 2 and a["p_stationary"] == pytest.approx(0.3) and a["p_walking"] == pytest.approx(0.6)
    assert engine.aggregate_model_b([])["p_walking"] is None


# ---- freeze and repository rules ----
def test_thresholds_frozen_hash():
    h = json.loads((ROOT / "results/metrics/phase4_thresholds_hash.json").read_text())
    assert sha(HERE / "thresholds.json") == h["thresholds_json_sha256"]
    assert sha(HERE / "split.json") == h["split_json_sha256"]
    assert sha(HERE / "engine.py") == h["engine_py_sha256"]


def test_split_zero_overlap():
    s = json.loads((HERE / "split.json").read_text())
    assert not set(s["calibration_subjects"]) & set(s["heldout_subjects"]) and s["overlap"] == []


def test_thresholds_have_provenance():
    for k in engine.THRESHOLD_KEYS:
        t = TDOC["thresholds"][k]
        assert "provenance" in t and "status" in t
    assert TDOC["provisional_thresholds"], "stationary-side thresholds must be marked provisional while no live stationary data exist"


def test_no_training_no_randomness_no_banned_wording():
    fit_call = re.compile(r"\." + "fit" + r"\(")
    banned = "re" + "ward"
    files = [p for p in HERE.glob("*.py")] + [ROOT / "docs/fusion_engine_spec.md"]
    for p in files:
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        assert not fit_call.search(txt), f"{p.name} calls fit"
        assert banned not in txt.lower(), f"{p.name} uses banned wording"
        if p.name != "test_fusion_engine.py" and p.suffix == ".py":
            assert not re.search(r"^\s*(import|from)\s+(random|secrets)\b", txt, re.M) and "np.random" not in txt, f"{p.name} uses randomness"
