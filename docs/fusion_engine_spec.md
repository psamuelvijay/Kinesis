# Fusion engine specification (Phase 4)

Reference implementation: `ml/fusion_engine/engine.py` (Python standard library only). Thresholds: `ml/fusion_engine/thresholds.json`
(frozen, SHA-256 in `results/metrics/phase4_thresholds_hash.json`). Test vectors: `ml/fusion_engine/golden_vectors.json`.
A Kotlin port must reproduce `golden_vectors.json` exactly (states and reasons; floating-point fields to 1e-9).

## 1. What the engine is

- A **consistency detector**. It checks whether GPS-reported movement agrees with phone motion evidence. It is **not** a spoofing classifier and has never been trained or evaluated on spoofing data.
- **Model B** is an **activity classifier** (WALKING / STATIONARY / OTHER) trained on MotionSense and UCI HAR. It was not trained on GPS spoofing.
- **Model A** (GPS-only step estimator) is used for comparison and analysis only. No rule reads it. App A uses GPS only (Model A); App B uses the sensor-fusion logic with physical steps.
- Product wording: **movement accepted** / **movement flagged**.
- No fusion-layer training. Every threshold is a quantile of genuine Dryad walking measured on calibration subjects, or a labelled design constant.
- The engine never forces a decision. Missing, poor or conflicting evidence yields `INSUFFICIENT_DATA` or `UNCERTAIN`.

## 2. Inputs per decision window

A decision window is 5 s, non-overlapping, aligned to the GPS fixes (same windows as Model A). Window k covers `[t0 + 5k, t0 + 5(k+1))` seconds.

| Field | Definition | Unit | Dryad source | Android source |
|---|---|---|---|---|
| `gps_speed_mps` | median of valid reported speeds of kept fixes in the window; speed is valid only if finite and >= 0 | m/s | `positions.speed` | `Location.getSpeed()` when `hasSpeed()` |
| `gps_displacement_m` | haversine distance first to last kept fix; missing if fewer than 2 fixes | m | `positions` lat/lon | `Location` lat/lon |
| `gps_covered_s` | time between first and last kept fix | s | `positions.ms` | `Location.elapsedRealtimeNanos` |
| `gps_coverage_frac` | `gps_covered_s / 5` | - | derived | derived |
| `gps_path_m` | summed haversine distance of consecutive kept fixes (used only for the explanation trend) | m | derived | derived |
| `gps_conf_m` | mean horizontal accuracy of kept fixes | m | `positions.confInterval` | `Location.getAccuracy()` |
| `imu_n_windows` | Model B windows (128 samples, 50 Hz, stride 64) lying completely inside the decision window: `start >= a` and `start + 127 * 20 ms <= b` | count | `phase4_dryad_modelB_windows.csv` | on-device Model B |
| `p_stationary`, `p_walking`, `p_other` | **mean** of the Model B class probabilities over those windows | 0..1 | same | same |
| `physical_steps` | increase of the step counter within the window (running-maximum increments; never negative) | steps | **stand-in:** Dryad `steps.csv` running-max increment (the phone pedometer) | `TYPE_STEP_COUNTER` increment (or counted `TYPE_STEP_DETECTOR` events) |
| `model_a_steps` | optional, comparison only | steps | `best_model.joblib` | not used |

GPS cleaning before the window (Phase 2 rules): sort by time, drop exact duplicates, drop fixes with accuracy > 50 m or invalid, drop teleports (> 10 m/s to both neighbours), no interpolation over gaps > 10 s. A window with a gap > 10 s, no kept fix, or no valid speed has no GPS record and is `INSUFFICIENT_DATA`.

## 3. Aggregation of Model B

Probability mean over the Model B windows in the decision window (not a majority vote): `p_c = (1/n) * sum_i p_c(i)`.
`imu_class = argmax(p_stationary, p_walking, p_other)`; ties resolved in the order STATIONARY, WALKING, OTHER.
The mean keeps the class margin available to the rules.

## 4. Thresholds (frozen values in `thresholds.json`)

| Name | Value | Source | Status |
|---|---|---|---|
| `ACC_MAX_M` | 16.37879 m | p99 of window mean accuracy, calibration walking | calibrated |
| `COV_MIN` | 0.7924 | p10 of GPS coverage fraction | calibrated |
| `V_MOVE_MPS` | 0.3207219 m/s | p05 of window median GPS speed | calibrated (moving side); still side provisional |
| `V_MOVE_DISP_MPS` | 0.5454660 m/s | p05 of displacement / covered seconds | calibrated (moving side); still side provisional |
| `V_WALK_MAX_MPS` | 1.845615 m/s | p99 of window median GPS speed | calibrated |
| `STEP_MIN` | 2 steps per 5 s | p05 of physical step increase | calibrated |
| `STEP_ZERO_MAX` | 1 step per 5 s | design constant (one spurious pedometer step) | provisional (no live stationary calibration data) |
| `P_STAT_STATIONARY` | 0.5 | design constant | provisional (no live stationary calibration data) |
| `P_STAT_SUSPICIOUS` | 0.999866 | max(0.5, p99 of mean P(STATIONARY) on genuine walking) | calibrated |
| `MIN_IMU_WINDOWS` | 1 | design constant | design constant |
| `PERSISTENCE_N` | 2 | smallest N >= 2 with false SUSPICIOUS episodes <= 1 per walking hour on calibration data | calibrated (in-sample) |

Calibration data: Dryad subjects 4, 5, 6, 7, 8, 13, 14, 16, 17, 18 (94 genuine hand-held walking tracks). Dryad contains no stationary phone data. Pre-test GNSS warm-up fixes carry no stationarity label and were not used. So the "GPS still" boundary is **provisional (no live stationary calibration data)**: GPS stationary jitter has not been measured. The live stationary-on-table recordings must recalibrate `V_MOVE_*`, `STEP_ZERO_MAX`, `P_STAT_STATIONARY` before any live claim.

## 5. Decision table

Evaluate in order; the first matching row decides. Let
`disp_speed = gps_displacement_m / gps_covered_s`,
`speed_move = gps_speed_mps >= V_MOVE_MPS`, `disp_move = disp_speed >= V_MOVE_DISP_MPS`,
`steps_up = physical_steps >= STEP_MIN`, `steps_zero = physical_steps <= STEP_ZERO_MAX`.

| # | Condition | State | Reason code | movement_accepted |
|---|---|---|---|---|
| 1 | any of `gps_speed_mps, gps_displacement_m, gps_covered_s, gps_coverage_frac, gps_conf_m, p_*, physical_steps` missing or not finite, or `imu_n_windows < MIN_IMU_WINDOWS` | INSUFFICIENT_DATA | `missing:<fields>` or `imu_windows_below_minimum` | null |
| 2 | `gps_conf_m > ACC_MAX_M` | INSUFFICIENT_DATA | `gps_accuracy_poor` | null |
| 3 | `gps_coverage_frac < COV_MIN` or `gps_covered_s <= 0` | INSUFFICIENT_DATA | `gps_coverage_low` | null |
| 4 | `speed_move and disp_move` and `gps_speed_mps > V_WALK_MAX_MPS` | UNCERTAIN | `gps_speed_above_walking_envelope` | null |
| 5 | moving, `imu_class = WALKING`, `steps_up` | GENUINE_WALKING | `gps_moving_imu_walking_steps_increase` | true |
| 6 | moving, `imu_class = STATIONARY`, `p_stationary >= P_STAT_SUSPICIOUS`, `steps_zero` | SUSPICIOUS_GPS_MOVEMENT | `gps_moving_imu_stationary_no_steps` | false |
| 7 | moving, `imu_class = STATIONARY`, other cases | UNCERTAIN | `imu_stationary_but_steps_present` (steps not zero) or `imu_stationary_weak_probability` | null |
| 8 | moving, `imu_class = WALKING`, not `steps_up` | UNCERTAIN | `imu_walking_but_steps_not_increasing` | null |
| 9 | moving, `imu_class = OTHER` | UNCERTAIN | `imu_other_activity` | null |
| 10 | not `speed_move` and not `disp_move`, `imu_class = STATIONARY`, `p_stationary >= P_STAT_STATIONARY`, `steps_zero` | STATIONARY | `gps_still_imu_stationary_steps_unchanged` | null |
| 11 | not `speed_move` and not `disp_move`, otherwise | UNCERTAIN | `gps_still_but_imu_or_steps_active` | null |
| 12 | exactly one of `speed_move`, `disp_move` | UNCERTAIN | `gps_speed_displacement_disagree` | null |

"Moving" means `speed_move and disp_move`. Rows 1 to 3 are the data-quality gates, row 4 limits the engine to the pedestrian speed envelope.

### Edge cases

| Situation | What the engine does |
|---|---|
| GPS jitter while stationary | Reported speed with no displacement, or displacement below the threshold: row 12 or 11, never SUSPICIOUS. Jitter that exceeds both `V_MOVE_*` while Model B is strongly stationary and steps are zero would be flagged. Provisional until stationary GPS is measured. |
| Slow drift | Row 12 (speed and displacement disagree) or row 11. UNCERTAIN. |
| Phone in a vehicle | Speed above `V_WALK_MAX_MPS`: row 4, UNCERTAIN, never SUSPICIOUS. A spoofed route above walking speed is therefore not detected (scope limit). Vehicle vibration with low speeds can reach rows 5 to 9 and is not distinguished. |
| Running or jogging | Speed above the envelope (row 4) or Model B OTHER (row 9): UNCERTAIN. |
| Stairs | Model B OTHER (row 9), or WALKING with low GPS displacement (row 11/12): UNCERTAIN. |
| Hand motion or shake with phone otherwise still | Model B OTHER or WALKING with steps possible. Rows 7 to 9: UNCERTAIN. A physical fake of steps defeats the step test (known limitation). |
| Pedometer latency | Walking with a step counter that lags: row 8, UNCERTAIN. |
| Poor accuracy, short coverage, no Model B window, no steps | Rows 1 to 3: INSUFFICIENT_DATA. |
| Model B domain gap | Model B labels only about half of genuine hand-held Dryad walking as WALKING (Phase 4 IMU check), so many genuine windows are UNCERTAIN (row 9). This costs coverage, not false flags. |

## 6. Persistence and hysteresis

`PERSISTENCE_N = 2`. Per session, in time order, keep `run` = number of consecutive identical raw states ending at the current window.

```
reported = UNCERTAIN
for each window i with raw state s_i:
    run = run + 1 if s_i == s_{i-1} else 1
    if s_i is UNCERTAIN or INSUFFICIENT_DATA: reported = s_i          # no hold across missing or conflicting evidence
    elif run >= N:                         reported = s_i
    elif reported is not decisive:         reported = UNCERTAIN       # decisive = GENUINE_WALKING, STATIONARY, SUSPICIOUS_GPS_MOVEMENT
    (otherwise keep the previous reported decisive state)
movement_flagged = (reported == SUSPICIOUS_GPS_MOVEMENT)
```

Decision latency floor is `N x 5 s` (10 s). The raw state is also reported. N was chosen on calibration data only (see `thresholds.json`, `persistence.selection`).

## 7. Explanation for every SUSPICIOUS raw result

```
{ gps_speed_mps, gps_displacement_m, gps_distance_trend_m, gps_distance_trend_windows, gps_accuracy_m,
  imu_activity, p_stationary, p_walking, physical_steps,
  rule_triggered: "S1_GPS_MOVING_IMU_STATIONARY_NO_STEPS",
  thresholds: { V_MOVE_MPS, V_MOVE_DISP_MPS, V_WALK_MAX_MPS, P_STAT_SUSPICIOUS, STEP_ZERO_MAX },
  movement_accepted: false }
```

`gps_distance_trend_m` = sum of `gps_path_m` over the current window and the previous `N - 1` windows of the session (`gps_distance_trend_windows` windows).

## 8. Determinism

No randomness, no clocks, no model calls inside the engine. Same inputs and thresholds give the same outputs. `run_sequence` is a pure function of the ordered window list. The pipeline (`make_split.py`, `build_signals.py`, `calibrate.py`, `evaluate.py`, `make_golden_vectors.py`) reproduces bit-identical output files.

## 9. Order of work and freeze

1. `make_split.py` writes `split.json` (no residual information used).
2. `build_signals.py` builds window inputs for all 146 tracks (no thresholds).
3. `calibrate.py` reads calibration subjects only, writes `thresholds.json` and `phase4_thresholds_hash.json`.
4. `evaluate.py` verifies the hashes, then evaluates held-out subjects (3, 10, 11, 12). It computes no threshold.

Dryad has no spoofing. Held-out results are false-flag and coverage figures on genuine walking. No detection rate exists until live mock-location recordings are made.
