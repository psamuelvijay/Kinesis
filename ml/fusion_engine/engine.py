"""Phase 4 fusion engine: GPS-motion CONSISTENCY detector. Pure Python (stdlib only), deterministic, no training, no randomness.

IMPORTANT (scope, repeated in docs/fusion_engine_spec.md):
 * This is a consistency detector, NOT a spoofing classifier. It checks whether GPS-reported movement agrees with phone
   motion evidence (Model B activity class + probabilities, physical step counter). It was never trained or evaluated on spoofing data.
 * Model B is an ACTIVITY classifier (WALKING / STATIONARY / OTHER). It was not trained on GPS spoofing.
 * Model A (GPS-only step estimator) is NOT used in any decision. Its output can be carried in the input dict for comparison only.
 * The engine never forces a decision: missing/poor/conflicting evidence gives INSUFFICIENT_DATA or UNCERTAIN.
 * Output vocabulary for the product: "movement accepted" / "movement flagged".

Window input dict (one 5 s fusion decision window aligned to the GPS fixes, same windows as Model A). None = unavailable:
  gps_speed_mps        median of valid reported GPS speeds in the window (invalid speeds -1/NaN already removed upstream)
  gps_displacement_m   haversine distance first->last kept fix in the window
  gps_covered_s        time between first and last kept fix
  gps_coverage_frac    gps_covered_s / 5 s
  gps_path_m           summed distance of consecutive kept fixes (used only for the distance trend in explanations)
  gps_conf_m           mean confInterval (horizontal accuracy, m) of kept fixes
  imu_n_windows        number of Model B windows (128 samples at 50 Hz) fully inside the decision window
  p_stationary, p_walking, p_other   probability MEAN over those Model B windows
  physical_steps       increase of the phone step counter inside the window (running-max increments; for Dryad steps.csv is the
                       stand-in for Android TYPE_STEP_COUNTER / TYPE_STEP_DETECTOR increments)
  model_a_steps        optional, comparison only
"""
import json
import math

STATES = ("GENUINE_WALKING", "STATIONARY", "SUSPICIOUS_GPS_MOVEMENT", "UNCERTAIN", "INSUFFICIENT_DATA")
DECISIVE = ("GENUINE_WALKING", "STATIONARY", "SUSPICIOUS_GPS_MOVEMENT")
CLASS_ORDER = ("STATIONARY", "WALKING", "OTHER")  # tie-break order for argmax (first wins)
RULE_SUSPICIOUS = "S1_GPS_MOVING_IMU_STATIONARY_NO_STEPS"
THRESHOLD_KEYS = ("ACC_MAX_M", "COV_MIN", "V_MOVE_MPS", "V_MOVE_DISP_MPS", "V_WALK_MAX_MPS", "STEP_MIN", "STEP_ZERO_MAX",
                  "P_STAT_STATIONARY", "P_STAT_SUSPICIOUS", "MIN_IMU_WINDOWS")


def load_thresholds(path):
    """Return (values dict name->number, full document). Only values are used by the decision logic."""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    vals = {k: doc["thresholds"][k]["value"] for k in THRESHOLD_KEYS}
    vals["PERSISTENCE_N"] = doc["persistence"]["N"]
    return vals, doc


def _ok(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def aggregate_model_b(rows):
    """Probability-mean aggregation of Model B windows inside a decision window.
    rows: list of (p_stationary, p_walking, p_other). Returns dict(imu_n_windows, p_stationary, p_walking, p_other); None probs if empty."""
    n = len(rows)
    if n == 0:
        return {"imu_n_windows": 0, "p_stationary": None, "p_walking": None, "p_other": None}
    s = [sum(r[i] for r in rows) / n for i in range(3)]
    return {"imu_n_windows": n, "p_stationary": s[0], "p_walking": s[1], "p_other": s[2]}


def imu_class(inp):
    """argmax of the mean probabilities, ties resolved in CLASS_ORDER."""
    p = {"STATIONARY": inp["p_stationary"], "WALKING": inp["p_walking"], "OTHER": inp["p_other"]}
    best = CLASS_ORDER[0]
    for c in CLASS_ORDER[1:]:
        if p[c] > p[best]:
            best = c
    return best


def _result(state, reason, inp, th, facts, extra=None):
    accepted = True if state == "GENUINE_WALKING" else False if state == "SUSPICIOUS_GPS_MOVEMENT" else None
    r = {"state": state, "reason": reason, "movement_accepted": accepted, "facts": facts}
    if extra:
        r["explanation"] = extra
    return r


def decide_window(inp, th, recent_path_m=()):
    """Decision table for one window. Priority order (first match wins). Returns dict(state, reason, movement_accepted, facts[, explanation]).
    recent_path_m: GPS path lengths (m) of the immediately preceding windows of this session (oldest first), used only for the
    'gps_distance_trend_m' field of the explanation."""
    g = inp
    # ---- D1 required inputs present and finite -------------------------------------------------------------
    need = ("gps_speed_mps", "gps_displacement_m", "gps_covered_s", "gps_coverage_frac", "gps_conf_m",
            "p_stationary", "p_walking", "p_other", "physical_steps")
    missing = [k for k in need if not _ok(g.get(k))]
    if missing or not _ok(g.get("imu_n_windows")) or g["imu_n_windows"] < th["MIN_IMU_WINDOWS"]:
        why = "missing:" + ",".join(missing) if missing else "imu_windows_below_minimum"
        return _result("INSUFFICIENT_DATA", why, inp, th, {})
    # ---- D2 GPS quality gates -----------------------------------------------------------------------------------
    if g["gps_conf_m"] > th["ACC_MAX_M"]:
        return _result("INSUFFICIENT_DATA", "gps_accuracy_poor", inp, th, {})
    if g["gps_coverage_frac"] < th["COV_MIN"] or g["gps_covered_s"] <= 0:
        return _result("INSUFFICIENT_DATA", "gps_coverage_low", inp, th, {})
    # ---- derived facts ---------------------------------------------------------------------------------------
    disp_speed = g["gps_displacement_m"] / g["gps_covered_s"]
    speed_move = g["gps_speed_mps"] >= th["V_MOVE_MPS"]
    disp_move = disp_speed >= th["V_MOVE_DISP_MPS"]
    cls = imu_class(g)
    steps = g["physical_steps"]
    facts = {"gps_disp_speed_mps": disp_speed, "imu_class": cls, "speed_move": speed_move, "displacement_move": disp_move}
    steps_up = steps >= th["STEP_MIN"]
    steps_zero = steps <= th["STEP_ZERO_MAX"]
    # ---- D3 GPS movement class --------------------------------------------------------------------------------
    if speed_move and disp_move:
        if g["gps_speed_mps"] > th["V_WALK_MAX_MPS"]:
            return _result("UNCERTAIN", "gps_speed_above_walking_envelope", inp, th, facts)   # running, jog, cycling, vehicle
        if cls == "WALKING" and steps_up:
            return _result("GENUINE_WALKING", "gps_moving_imu_walking_steps_increase", inp, th, facts)
        if cls == "STATIONARY" and g["p_stationary"] >= th["P_STAT_SUSPICIOUS"] and steps_zero:
            trend = float(sum(recent_path_m)) + (g["gps_path_m"] if _ok(g.get("gps_path_m")) else 0.0)
            expl = {"gps_speed_mps": g["gps_speed_mps"], "gps_displacement_m": g["gps_displacement_m"],
                    "gps_distance_trend_m": trend, "gps_distance_trend_windows": len(recent_path_m) + 1,
                    "gps_accuracy_m": g["gps_conf_m"], "imu_activity": cls, "p_stationary": g["p_stationary"],
                    "p_walking": g["p_walking"], "physical_steps": steps, "rule_triggered": RULE_SUSPICIOUS,
                    "thresholds": {k: th[k] for k in ("V_MOVE_MPS", "V_MOVE_DISP_MPS", "V_WALK_MAX_MPS", "P_STAT_SUSPICIOUS", "STEP_ZERO_MAX")},
                    "movement_accepted": False}
            return _result("SUSPICIOUS_GPS_MOVEMENT", "gps_moving_imu_stationary_no_steps", inp, th, facts, expl)
        if cls == "STATIONARY":
            return _result("UNCERTAIN", "imu_stationary_but_steps_present" if not steps_zero else "imu_stationary_weak_probability", inp, th, facts)
        if cls == "WALKING":
            return _result("UNCERTAIN", "imu_walking_but_steps_not_increasing", inp, th, facts)   # pedometer latency
        return _result("UNCERTAIN", "imu_other_activity", inp, th, facts)   # hand motion, vehicle, stairs, jog, ambiguous
    if (not speed_move) and (not disp_move):
        if cls == "STATIONARY" and g["p_stationary"] >= th["P_STAT_STATIONARY"] and steps_zero:
            return _result("STATIONARY", "gps_still_imu_stationary_steps_unchanged", inp, th, facts)
        return _result("UNCERTAIN", "gps_still_but_imu_or_steps_active", inp, th, facts)   # indoor walking, GPS under-report
    return _result("UNCERTAIN", "gps_speed_displacement_disagree", inp, th, facts)   # slow drift, jitter, speed without displacement


def apply_persistence(raw_states, n):
    """Hysteresis. The reported state changes to a DECISIVE state only after n consecutive identical raw states.
    UNCERTAIN / INSUFFICIENT_DATA raw states are reported immediately (no hold across missing or conflicting evidence).
    A decisive raw state that has not yet persisted keeps the previously reported decisive state, or UNCERTAIN if there is none.
    Returns list of reported states (same length)."""
    out, cur, run, prev = [], "UNCERTAIN", 0, None
    for s in raw_states:
        run = run + 1 if s == prev else 1
        prev = s
        if s not in DECISIVE:
            cur = s
        elif run >= n:
            cur = s
        elif cur not in DECISIVE:
            cur = "UNCERTAIN"
        out.append(cur)
    return out


def run_sequence(windows, th, n=None):
    """windows: list of input dicts of ONE session in time order. Returns list of per-window dicts with raw result and reported state.
    n defaults to th['PERSISTENCE_N']."""
    n = th["PERSISTENCE_N"] if n is None else n
    results, recent = [], []
    for w in windows:
        r = decide_window(w, th, recent_path_m=tuple(recent[-(n - 1):]) if n > 1 else ())
        results.append(r)
        recent.append(w.get("gps_path_m") if _ok(w.get("gps_path_m")) else 0.0)
    reported = apply_persistence([r["state"] for r in results], n)
    for r, s in zip(results, reported):
        r["reported_state"] = s
        r["movement_flagged"] = s == "SUSPICIOUS_GPS_MOVEMENT"
        r["movement_accepted_reported"] = True if s == "GENUINE_WALKING" else False if s == "SUSPICIOUS_GPS_MOVEMENT" else None
    return results
