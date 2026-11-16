# Phase 4 report: GPS-motion consistency engine

Branch `phase4-fusion-engine` (from `cb1de1a`). The Phase 4 code, metrics, reports and the `results/phase3_report.md` correction are committed on this branch (see `git log`). Not committed: the appended Fusion Engine section in `docs/model_documentation.md` (tracked file, edit logged in the run log), the user's documents in `docs/`, `docs/Kinesis_Literature_Survey.pdf` and `.agents/`.
Labels: **Verified** = read from a file or JSON in this repository or from a run in this step. **Inferred** = reasoned or taken from a third-party convention, not tested here.
Every number below comes from `results/metrics/phase4_*.json` (or from `results/phase4_run_log.md` where it quotes those runs). No number was estimated for this report.

## 1. What was built, and what it is not

- **Model B is an activity classifier** (WALKING / STATIONARY / OTHER) trained on MotionSense and UCI HAR. It was never trained or evaluated on GPS spoofing. (Verified, Phase 3 report.)
- **The fusion layer is a consistency detector.** It checks whether GPS-reported movement agrees with phone motion evidence, using hand-set rules. **There is no learned spoofing classifier.** No ML model was trained for the fusion layer. (Verified, `docs/fusion_engine_spec.md`, `ml/fusion_engine/engine.py`.)
- Model A (GPS-only step estimator) is used for comparison only. No fusion rule reads it.
- Output wording is **movement accepted** / **movement flagged**.
- No synthetic GPS spoofing data or simulated attack perturbation was generated or used, by design.

## 2. Restore record (Verified, `results/phase4_run_log.md`, `results/metrics/phase4_preservation_check.json`)

Only the user-approved Phase 2 artefact paths were restored from HEAD, by exact path. Before the restore, `git status` listed eight modified tracked files (`ml/models/evaluation_metrics.json`, `ml/models/training_config.json`, `results/metrics/phase2_model_metrics.json`, four `results/plots/phase2_*.png`, and `docs/Kinesis_Literature_Survey.pdf`). After the restore, only `docs/Kinesis_Literature_Survey.pdf` remained modified among tracked files. `.agents/`, the user's `.pptx` files, the Logger Spec v0.1 and `Kinesis_Literature_Survey.pdf` were not touched.

Note: the original instruction text named four earlier artefacts and the Phase 4 approval named seven. The run log records the seven-path restore as the executed action.

## 3. Correction record (Verified)

`results/phase3_report.md` line 3 said "Nothing is committed". Phase 3 is committed as `cb1de1a` on `phase3-activity-classifier`. The sentence was replaced with the commit reference, plus a note that the Phase 2 artefacts and docs described as uncommitted were uncommitted when that report was written. No other line of the report changed (`git diff --stat`: 1 insertion, 1 deletion). The edit is committed on this branch.

## 4. IMU compatibility findings (Dryad against Model B)

Source: `results/metrics/phase4_dryad_imu_check.json`, `phase4_dryad_modelB_windows.csv`. Two runs gave identical SHA-256 for both files. (Verified.)

| Item | Finding | Label |
|---|---|---|
| Tracks used | 146 tracks, 14 subjects with motion and GNSS; all hand held; 121 Android, 25 iOS | Verified |
| Acceleration units | `accel*` is gravity removed, `accelWithG*` includes gravity, both m/s². Median `accelWithG` magnitude 10.24 m/s²; median difference between the two 9.81 m/s². Conversion: divide by 9.80665 to get g. | Verified from data; the m/s² unit label itself is Inferred (Dryad gives no unit text, column names follow the W3C DeviceMotionEvent convention) |
| Gyro units | deg/s, converted by pi/180. Median raw magnitude 53.0. Ratio to MotionSense walking is 0.49 after conversion. Leaving it unconverted gives 0% WALKING. No sign of mixed units across devices (per-device medians span 7.4x, not 57x). | Inferred (unit rests on data scale and API convention, not Dryad text) |
| Timestamps | Median interval 17 ms in every track; mean rate per track median 59.8 Hz, minimum 6.3 Hz. 4 tracks non-monotonic, 31 with duplicate ms; handled by stable sort and dropping duplicates. | Verified |
| Resampling | 50 Hz grid, linear interpolation only between samples at most 100 ms apart, 128-sample windows, stride 64. Of 42,428 possible windows, 1,512 dropped for gaps, 40,916 kept. | Verified |
| Anti-alias effect | 60 Hz to 50 Hz linear interpolation has no anti-alias filter; the effect on features was not measured. | Inferred |
| Feature scale | Dryad median acc magnitude 0.33 g: 0.48x MotionSense, 1.16x UCI. Gyro magnitude 1.04 rad/s: 0.48x MotionSense, 1.55x UCI. Hand-held Dryad lies between pocket (MotionSense) and waist (UCI) training scales. | Verified |

Gate result: unit and gravity compatibility holds; no rescaling applied; Model B stays frozen.

**Model B on genuine Dryad walking** (every window is genuine walking; 40,916 windows). Predicted WALKING 51.2%, OTHER 40.5%, STATIONARY 8.2%. By OS: Android 0.51 / 0.42 / 0.07 (WALKING / OTHER / STATIONARY), iOS 0.52 / 0.31 / 0.17. By speed bin, STATIONARY share is 26% below 1.0 m/s and 0% at 1.6 m/s and above. 44% of tracks and 36% of subjects have a WALKING share below 0.5. (Verified.)
This is a domain gap (hand held against pocket and waist training; Phase 3 cross-dataset macro-F1 was 0.55 to 0.59), not a unit offset. (The reason is Inferred; the gap itself is Verified.) Consequence: WALKING share is not usable as a positive walking test, and false STATIONARY is the main false-flag source.
Not tested: Model B on Dryad stationary data (Dryad has none).

## 5. Fusion design and decision table

Per 5 s non-overlapping window the engine takes: GPS speed (median of valid reported speeds), GPS displacement, coverage, accuracy, mean Model B probabilities over the 128-sample windows lying inside it, and the phone step-counter increase (running maximum, never negative). Full definitions: `docs/fusion_engine_spec.md`. The first matching row decides.

| # | Condition | State | movement |
|---|---|---|---|
| 1 | a required input missing or no Model B window | INSUFFICIENT_DATA | none |
| 2 | mean GPS accuracy above `ACC_MAX_M` | INSUFFICIENT_DATA | none |
| 3 | GPS coverage below `COV_MIN` | INSUFFICIENT_DATA | none |
| 4 | GPS moving and speed above `V_WALK_MAX_MPS` | UNCERTAIN | none |
| 5 | GPS moving, Model B WALKING, steps >= `STEP_MIN` | GENUINE_WALKING | accepted |
| 6 | GPS moving, Model B STATIONARY with P(STATIONARY) >= `P_STAT_SUSPICIOUS`, steps <= `STEP_ZERO_MAX` | SUSPICIOUS_GPS_MOVEMENT | flagged |
| 7 | GPS moving, Model B STATIONARY, other cases | UNCERTAIN | none |
| 8 | GPS moving, Model B WALKING, steps not increasing | UNCERTAIN | none |
| 9 | GPS moving, Model B OTHER | UNCERTAIN | none |
| 10 | GPS still, Model B STATIONARY (P >= `P_STAT_STATIONARY`), steps <= `STEP_ZERO_MAX` | STATIONARY | none |
| 11 | GPS still, anything else | UNCERTAIN | none |
| 12 | speed and displacement disagree (exactly one above its threshold) | UNCERTAIN | none |

"GPS moving" = reported speed >= `V_MOVE_MPS` and displacement speed >= `V_MOVE_DISP_MPS`. Persistence: a decisive state is reported only after `PERSISTENCE_N = 2` identical consecutive windows (latency floor 10 s); UNCERTAIN and INSUFFICIENT_DATA are never held. `movement_flagged` is true only for a reported SUSPICIOUS_GPS_MOVEMENT. The only flag rule is "GPS says moving, phone says still and has no steps". Every flag carries an explanation record (spec section 7). The engine is pure Python and deterministic; 56 tests pass (`python -m pytest ml/fusion_engine -q`, run in this step). `ml/fusion_engine/golden_vectors.json` is the parity target for a Kotlin port. (Verified.)

## 6. Thresholds and provenance

Frozen in `ml/fusion_engine/thresholds.json`. SHA-256 `5184189b...b639725` (`phase4_thresholds_hash.json`). Calibration subjects (Dryad genuine walking, 94 tracks, 7,828 windows): 4, 5, 6, 7, 8, 13, 14, 16, 17, 18. (Verified.)

| Threshold | Value | Source | Status |
|---|---|---|---|
| `ACC_MAX_M` | 16.38 m | p99 window mean accuracy | calibrated |
| `COV_MIN` | 0.792 | p10 coverage fraction | calibrated |
| `V_MOVE_MPS` | 0.321 m/s | p05 window median speed | calibrated on the moving side; **provisional** as the still boundary (no live stationary calibration data) |
| `V_MOVE_DISP_MPS` | 0.545 m/s | p05 displacement speed | same as above, **provisional** |
| `V_WALK_MAX_MPS` | 1.846 m/s | p99 window median speed | calibrated |
| `STEP_MIN` | 2 steps / 5 s | p05 step increase | calibrated |
| `STEP_ZERO_MAX` | 1 step / 5 s | design constant | **provisional (no live stationary calibration data)** |
| `P_STAT_STATIONARY` | 0.5 | design constant | **provisional (no live stationary calibration data)** |
| `P_STAT_SUSPICIOUS` | about 0.99987 | max(0.5, p99 mean P(STATIONARY) on genuine walking) | calibrated |
| `PERSISTENCE_N` | 2 | smallest N >= 2 with under 1 false SUSPICIOUS episode per hour | calibrated, in sample |

Spread between subjects is large (per-subject quantiles in `phase4_calibration.json`, for example `V_MOVE_MPS` from 0.05 to 0.99 m/s and `P_STAT_SUSPICIOUS` from 0.003 to 0.9999), so single pooled values hide real subject differences. (Verified.)
Stationary search: Dryad `events.csv` has no standing periods. 300 pre-walk fixes exist in calibration tracks, but they are GNSS warm-up with no stationarity label, so they were not used. `datasets/live_recordings/*` contained no recordings. No stationary jitter was measured or invented. (Verified.)
In-sample calibration false SUSPICIOUS episodes per walking hour: N=1 0.18, N=2 0.09, N=3 and N=4 0.0. These are optimistic because the thresholds came from the same windows.

## 7. Dryad genuine-walking evaluation (held-out)

Source: `results/metrics/phase4_dryad_eval.json`. Held-out subjects 3, 10, 11, 12 (52 tracks, 2,950 windows, 4.10 walking hours). Calibration and held-out sets share no subject (asserted in code). Thresholds were verified by hash before evaluation and never recomputed there. All windows are genuine walking, so any SUSPICIOUS window is a false positive. **Dryad has no spoofing, so no detection rate is reported and none can be.** (Verified.)

| State | Raw windows | Share of all windows | Share of evaluable windows (1,740) |
|---|---|---|---|
| GENUINE_WALKING | 962 | 32.6% | 55.3% |
| UNCERTAIN | 708 | 24.0% | 40.7% |
| STATIONARY | 65 | 2.2% | 3.7% |
| SUSPICIOUS_GPS_MOVEMENT | 5 | 0.17% | 0.29% |
| INSUFFICIENT_DATA | 1,210 | 41.0% | n/a |

- After persistence (N=2): 0 reported SUSPICIOUS windows and 0 episodes (0.0 per walking hour). The 5 raw SUSPICIOUS windows were: subject 11: 2, subject 12: 3, subjects 3 and 10: 0.
- Excluding the Phase 2 distance-anomaly tracks (46 tracks, 2,409 windows): 4 raw SUSPICIOUS windows, 0 reported. The headline above keeps the anomalous tracks.
- Time to first reported GENUINE_WALKING: median 50 s, p90 113 s; 17 of 52 tracks never reach it.
- Android: 1,997 windows (35 tracks), 16.5% INSUFFICIENT_DATA. iOS: 953 windows (17 tracks), 92.4% INSUFFICIENT_DATA (sparse GPS fixes, low coverage). Dryad figures on iOS say little about the engine.
- By speed range (track average): below 1.0 m/s, STATIONARY 50 of 280 windows and 2 raw SUSPICIOUS; 1.0 to 1.3 m/s, 3 raw SUSPICIOUS of 2,172; 1.3 to 1.6 m/s, none.
- Main UNCERTAIN reasons: `imu_other_activity` 473, `gps_speed_displacement_disagree` 151, `imu_walking_but_steps_not_increasing` 27, `imu_stationary_but_steps_present` 23, `imu_stationary_weak_probability` 21.
- Model A comparison only (indicative; saved model pickled under scikit-learn 1.9.1, run under 1.8.0): MAE 1.89 steps per 5 s on all held-out windows, 1.34 on subject 12 (out of sample for Model A).

Reading: on genuine hand-held walking the engine raised no sustained flag, but it accepted movement in only about a third of all windows. The cost of the Model B domain gap is lost coverage (UNCERTAIN), not false flags. Four held-out subjects limit how far this generalises.

## 8. Live evaluation: PENDING USER DATA

Verified: `datasets/live_recordings/calibration/` and `evaluation/` contained no recordings. `phase4_live_calibration.json` and `phase4_live_eval.json` both have status `PENDING USER DATA`. No log was fabricated. The only test input is a placeholder fixture marked "format test only" that the parser refuses for calibration and evaluation.
There is therefore **no** live detection rate, latency, false-positive rate or accepted-distance figure. Tooling exists and is tested only for file format (`ingest_live_logs.py`, `calibrate_live.py`, `evaluate_live.py`, `docs/recording_protocol.md`). The S5 branch of `evaluate_live.py` and the calibrated branch of `calibrate_live.py` were never run on real data. (Verified.)
Split rule fixed before any data (`docs/recording_protocol.md` section 3): calibration = S2 and S3 real-GPS stationary sessions; S1 and S4 to S7 are evaluation only; different sessions and days; the calibration step never reads the evaluation folder.
Mock apps that report no accuracy field lose every fix to the accuracy filter and yield INSUFFICIENT_DATA; this is reported, not patched.

## 9. Stationary-on-table scenario (separate section)

Status: **PENDING USER DATA.** No stationary-on-table recording exists, so nothing is measured for it. Model B's behaviour on a phone resting on a surface is untested (Phase 3 limitation; Dryad has no stationary data). Three things stay unknown until the S2 and S3 recordings exist: GPS jitter speed and displacement of a still phone, step-counter noise at rest, and Model B's P(STATIONARY) on a table. The stationary-side thresholds (`V_MOVE_MPS`, `V_MOVE_DISP_MPS`, `STEP_ZERO_MAX`, `P_STAT_STATIONARY`) remain provisional until then. This scenario is reported on its own, apart from walking sessions, and with calibration sessions kept apart from evaluation sessions.

## 10. Limitations

1. **Dryad has no spoofing.** It supports false-flag and coverage figures only. No detection rate exists. (Verified)
2. **No synthetic attacks were used, by design.** The engine has therefore never been scored on any attack. (Verified)
3. **Stationary data availability.** No stationary GPS, pedometer or Model B data exist yet; four thresholds are provisional. (Verified)
4. **Model B domain shift.** Only about half of genuine hand-held Dryad walking is predicted WALKING; Phase 3 cross-dataset macro-F1 was 0.55 to 0.59. Rule 6 relies on Model B's STATIONARY output. (Verified)
5. **Step-counter dependence.** The rules need `physical_steps`. Dryad's pedometer is a stand-in for Android `TYPE_STEP_COUNTER`; the two are not shown to behave the same. A physical fake such as shaking the phone raises steps and defeats the step test. (Stand-in is Verified; the shake claim is Inferred.)
6. **Few subjects and sessions.** 10 calibration subjects, 4 held-out subjects; the 4 held-out subjects include 3 Model A validation subjects. Persistence N=2 is chosen in sample. (Verified)
7. **Mock-location detection scope.** The engine detects GPS/motion inconsistency (GPS moving, phone still, no steps). It does not detect all spoofing. It cannot detect spoofing while the user genuinely walks a similar route, and a spoofed speed above 1.846 m/s lands in UNCERTAIN (row 4) rather than flagged. Vehicles also land in UNCERTAIN. (Verified by design; real-world behaviour Inferred)
8. **Coverage.** 41% of held-out windows are INSUFFICIENT_DATA (92% on iOS) and 17 of 52 tracks never reach a reported GENUINE_WALKING. (Verified)
9. **Resampling.** 60 Hz to 50 Hz without an anti-alias filter; effect unmeasured. Gyro unit is Inferred. (Inferred)
10. Dryad GPS coordinates for many tracks are anonymised, so no map-based check is used (Phase 4 plan, Inferred from Dryad documentation).

## 11. Verified / Inferred summary

- **Verified:** restore and correction records; IMU check numbers; Model B class shares on Dryad; thresholds and hashes; held-out state counts; live status PENDING; 56 tests passing; no stationary data found.
- **Inferred:** Dryad unit text (m/s², deg/s); effect of resampling on features; that the Model B gap is caused by placement and hardware; behaviour of Android `TYPE_STEP_COUNTER` relative to Dryad's pedometer; behaviour in vehicles; the hand-shake attack.

## 12. PROPOSED ANDROID DEVELOPMENT PLAN (not started)

No Android code exists and none was written. This is a proposal for review. The apps are evaluator-facing samples, not the final DApp.

### 12.1 Shared design and architecture
- Two apps, **App A (GPS-only)** and **App B (sensor fusion)**, built from one Gradle project with a shared Compose UI module and design system. Same screens, same layout and same components, so evaluators compare behaviour only. Differences are limited to the logic module behind a common `MovementEngine` interface, and the label text.
- Material 3, restrained palette (one primary hue, neutral surfaces, one amber and one red for status), standard typography, light and dark theme. No gradients, glows or futuristic styling.
- Screens: **Status card** (state word, "Movement accepted" / "Movement flagged" / "Checking", one-line reason), **live metrics** (session steps, session distance, GPS speed, GPS accuracy, and for App B step-counter increase and Model B activity), **explanation panel** (plain-language reason plus the numbers behind it, taken from the engine's explanation record), **Reset Steps** button, settings and export.
- Wording is strictly "Movement accepted / flagged". No rewards, crypto, tokens or points anywhere in UI, code or logs.

### 12.2 Background step counting
- Foreground service using `TYPE_STEP_COUNTER` (primary), with `TYPE_STEP_DETECTOR` as a fallback or cross-check.
- Persist the last cumulative counter value, the baseline and the session totals (DataStore or Room) so counts survive process death, app restart and reboot (the cumulative counter resets on reboot; detect a decrease and start a new baseline instead of subtracting).
- Permissions: `ACTIVITY_RECOGNITION` (runtime, API 29+), fine location, `FOREGROUND_SERVICE` plus the matching foreground service types (`health` and `location`; check manifest requirements for API 34), `POST_NOTIFICATIONS` on Android 13+ (the service notification is still shown if denied, but the user may not see it; the app explains this). Android 14 requires declared foreground service types and the matching runtime permissions before `startForeground`. Request background location only if testing proves it is needed.
- Battery: exclude from nothing by default; show a one-time hint about battery optimisation and keep sensor sampling at the minimum rate that Model B needs (App B only).

### 12.3 Reset Steps button
- Resets the displayed **session** steps and distance by moving a stored baseline to the current cumulative counter value and the current distance. It never deletes or alters the sensor's cumulative counter, and it never touches stored logs. A confirmation is not needed. The reset is written to the log as an event. Fusion state and persistence are cleared on reset.

### 12.4 App A: GPS-only
- Uses Model A on-device (exported model plus Kotlin feature function with golden-vector tests) to produce **GPS-ESTIMATED STEPS**, shown with that exact label.
- Must not read the accelerometer, gyroscope or step counter for any validation. Only location is requested; `ACTIVITY_RECOGNITION` is not requested.
- Cannot flag GPS/motion inconsistency, by construction. Its status card shows only what GPS supports (for example plausible speed) and says so in the explanation panel.

### 12.5 App B: sensor fusion
- Model B on-device from an exported model (XGBoost converted to a form that a Kotlin runtime can run, with exact parity targets), fed from `TYPE_LINEAR_ACCELERATION` and `TYPE_GYROSCOPE` at 50 Hz in 128-sample windows, with the same unit conversion and resampling rules as Section 4.
- Kotlin feature parity tests against golden vectors (`ml/fusion_engine/golden_vectors.json` for the engine; new golden vectors for the Model B feature extraction and model output, generated from the Python pipeline).
- Fusion state machine ported from `engine.py` and the decision table in Section 5, with persistence and the explanation record. Uses the step counter from 12.2.
- Explanation panel renders the explanation record for each flag.

### 12.6 Logging and export (shared)
- One logger module for both apps, writing the live-log schema in `docs/recording_protocol.md` and the Logger Spec v0.1 (`accel`, `gyro`, `location` with `is_mock`, `step_counter`, `events`, `session.json`). Export via the share sheet so files drop into `datasets/live_recordings/` unchanged. App A logs location only.

### 12.7 Mock-location test procedure
- Enable developer options and select a mock location app; run the S1 to S7 scenarios of `docs/recording_protocol.md` (including the stationary-on-table sessions) with the phone on a table and the mock app replaying a walking route. Calibration and evaluation sessions on separate days. The task-card label comes from the operator, not from sensors. Record `is_mock` as a baseline column, never as an engine input.
- Report per-session outcomes as counts, not percentages.

### 12.8 Risks
- Model B domain gap on device may leave many windows UNCERTAIN (Section 7).
- Step-counter latency and OEM differences in `TYPE_STEP_COUNTER`.
- Foreground service restrictions and OEM battery managers killing the service.
- XGBoost export parity (floating-point differences between Python and Kotlin).
- Stationary thresholds are provisional until recordings exist.
- Small number of devices and sessions for evaluation.

### 12.9 Milestones
1. User records calibration and evaluation sessions; `calibrate_live.py` and `evaluate_live.py` run; thresholds revised once and frozen (decision point before any app work).
2. Shared Compose module, design system, Reset Steps and step-counter service.
3. Logging and export module.
4. App A (Model A export, parity tests).
5. App B (Model B export, parity tests, fusion engine, explanation panel).
6. Mock-location evaluation on device; final report.

## 13. Files and reproducibility

Code: `ml/fusion_engine/`. Specs: `docs/fusion_engine_spec.md`, `docs/recording_protocol.md`. Metrics: `results/metrics/phase4_*.json` and CSVs. A full re-run of the five pipeline scripts gave identical SHA-256 for 8 output files (run log). Committed on `phase4-fusion-engine`.
