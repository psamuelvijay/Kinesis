# Phase 4 plan: GPS-motion consistency engine (fusion)

Branch `phase4-fusion-engine` (from `cb1de1a`). Written before any Phase 4 code. Labels: **Verified** = checked against a file in this repository; **Inferred** = reasoned, not tested. Anything marked "to be computed" is not a result yet.

## 0. What this is and is not

- The fusion engine is a **research-informed consistency detector**. It flags windows where GPS-reported movement disagrees with phone-motion evidence. It is **not** a supervised spoofing classifier and was not trained on spoofing data.
- **Model B** (`ml/models/activity_combined_xgboost.joblib`) is an activity classifier (WALKING / STATIONARY / OTHER) trained on MotionSense and UCI HAR. It has never seen GPS spoofing (Verified, Phase 3 report). **Model A** (`ml/models/best_model.joblib`) is the GPS-only step estimator from Phase 2. Both are used **frozen, as inputs only**. No fusion-layer ML training, no retraining or tuning of A or B.
- Fusion rules are hand-set. Their thresholds are quantiles of residuals measured on genuine walking data. Any score is a deterministic, documented function of measured quantities. No random values anywhere.
- Real data only. No synthetic GPS spoofing datasets, offsets, speed scaling, replayed or jittered tracks, or fabricated attack labels.

## 1. What will be implemented (`ml/fusion/`, new)

1. **`dryad_imu.py`: Dryad IMU compatibility gate (first, before any inference).**
   - Dryad `motion.csv`: `accelX/Y/Z` (gravity removed) and `accelWithGX/Y/Z` in m/s² (Verified, Dryad README). `rotRateAlpha/Beta/Gamma` has **no stated unit** (Verified: README gives none); rad/s is Inferred.
   - Checks: (a) `accel*` magnitude is near 0 at rest and `accelWithG*` magnitude is near 9.8 (confirms the gravity-removed column); (b) gyro magnitude distribution against MotionSense `rotationRate` (rad/s) and UCI `body_gyro`, to detect a deg/s mismatch (factor 57.3); (c) feature distributions of Dryad windows against both training sets, in the style of `activity_feature_scale_comparison.json`.
   - Conversion if checks pass: `a_g = accel / 9.80665`; gyro unchanged. If the gyro check indicates deg/s, the conversion is documented and applied only if the evidence is unambiguous. If it is ambiguous, stop and ask the user. Model B is not run on Dryad until this gate has a written result.
   - Resample to 50 Hz and 128-sample windows (stride 64). Dryad motion is irregular (median interval about 17 ms; mean rate per track from 6.3 to 60 Hz, Verified, `dataset_inventory.md`). Linear interpolation only across gaps up to 0.1 s. Windows containing a longer gap are dropped, not filled (same principle as Phase 2). The same function is used for live Android data.
2. **`signals.py`: per-window measured quantities.** Fusion window = 5 s, non-overlapping, same convention as Model A. Per window:
   - From GPS (cleaned with the Phase 2 rules: sort by `ms`, drop duplicates, invalid speed −1/NaN, `confInterval` > 50 m, teleports > 10 m/s, no interpolation across gaps > 10 s): `gps_speed_mps` (median valid reported speed), `gps_path_speed_mps` (haversine path length of kept fixes / elapsed time), `coverage_frac`.
   - From Model B: P(STATIONARY), P(WALKING), P(OTHER) averaged over the Model B windows lying fully inside the fusion window, and the count of those windows.
   - From Model A: predicted steps in the window from GPS features (Phase 2 feature function reused unchanged).
   - From the phone step counter: observed steps in the window (running-maximum cumulative counter difference, as in Phase 2).
3. **`rules.py`: transparent consistency rules, each a deterministic function of the signals.** Each rule yields a ratio `r_i = value_i / threshold_i`; the rule fires when `r_i >= 1`.
   - **R1 stationary-motion conflict:** GPS speed is at or above a walking-speed floor while Model B's P(STATIONARY) is high. Value: `gps_speed_mps` where P(STATIONARY) >= its calibrated quantile.
   - **R2 speed above activity bound:** `gps_speed_mps` exceeds the upper quantile of genuine walking speed while Model B says WALKING. Vehicles also exceed this, so this rule is a plausibility flag, not proof of spoofing.
   - **R3 step residual:** `|Model A steps − observed phone steps|`. A phone that reports GPS walking but no steps gives a large residual. Limitation: a physical fake (hand shake) raises phone steps and defeats R3 (see Section 6).
   - **R4 GPS self-consistency:** reported speed against path speed from successive fixes (calibrated ratio quantile).
   - **Consistency score** (reported per window) = `max_i r_i`. **Flag** = score >= 1 in at least `K` consecutive windows. `K` = 3 (15 s) is fixed a priori to limit one-off GPS noise, justified in the plan, and not tuned on held-out data. The calibration step reports the false-flag rate for `K` = 1, 2, 3 on calibration data only, as documentation.
   - Rules that cannot be computed in a window (for example Model B windows missing because of a gap) are recorded as "not evaluable", never imputed.
   - The mock-location flag (`is_mock`), available only in live Android logs, is **not** an input to the rules. It is reported as a separate baseline.
4. **`calibrate.py`:** computes thresholds, writes `results/metrics/phase4_thresholds.json` (values, quantile used, source subjects, n windows, SHA-256 of the input files) and a human-readable table. Runs on calibration data only. Quantile levels (for example 99th for the upper-tail rules) are fixed in advance in this plan and reported with the resulting per-subject spread. Per-subject distributions are reported so that between-subject variation is visible.
5. **`evaluate.py`:** loads `phase4_thresholds.json` read-only and applies it to held-out data. It contains no code that recomputes thresholds. The thresholds file hash is recorded in each evaluation output.
6. **`live_ingest.py`:** adapter that reads Android logs in the Kinesis logger format (`accel.csv.gz`, `gyro.csv.gz`, `location.csv` with `is_mock`, `step_counter.csv`, `events.csv`, `session.json`; `docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md`, read-only) and produces the same signals as Dryad.

## 2. Data and recordings

**Dryad (genuine, real; Verified from `dataset_inventory.md`).** 146 tracks, 14 subjects with GPS + motion + steps: subjects 3 to 8, 10 to 14, 16 to 18. Subject 15 has no GNSS. Subjects 0, 1, 2 and most of 9 have no motion. Dryad has **no spoofing labels and no spoofed tracks**, so it provides genuine-behaviour statistics and false-flag rates only. Dryad cannot measure detection rate.

**Live controlled Android recordings (recorded by the user; none exist yet).** `datasets/live_recordings/calibration/` and `datasets/live_recordings/evaluation/` are empty directories (Verified). Scenarios, each with a task-card label and operator-entered start and end times (the label never comes from sensors):

| ID | Scenario | Genuine / mock | Purpose | Set |
|---|---|---|---|---|
| L1 | Phone stationary on a table, real GPS (no mock) | genuine | false-flag rate; Model B behaviour on this surface (gap noted in Phase 3, limitation 5) | calibration and evaluation (separate sessions) |
| L2 | Walking, phone in pocket or hand, real GPS | genuine | false-flag rate on the target device (third domain for Model B) | calibration and evaluation (separate sessions) |
| L3 | Other benign: sitting or standing with the phone in hand or pocket, stairs | genuine | OTHER / STATIONARY behaviour on-device | calibration (optional evaluation) |
| L4 | Phone stationary on a table, mock-location app feeding a walking route | mock | the controlled spoofing demonstration; detection rate | evaluation only |
| L5 (optional) | Mock route while the user walks genuinely | mock + real motion | boundary case; the engine is expected not to detect it, reported honestly | evaluation only |
| L6 (optional) | Mock route plus a hand shake | mock + physical fake | known limitation scenario (R3 defeated) | evaluation only |

Requirements: calibration and evaluation recordings come from separate sessions (ideally separate days), are never pooled, and are never used to adjust thresholds after the thresholds file is frozen. Minimum useful numbers (proposal, the user decides): at least 3 sessions of L1, L2 and L4 each in evaluation, at least 3 minutes each, at least 2 phones if available. Per-session results are reported, since the number of sessions is too small for confidence intervals to mean much.

**Dependency (needs the user).** No Android logger exists (Android development is not started in this phase). Live recordings must be made with an existing logging app that exports timestamped linear acceleration, gyroscope, location with an `is_mock` field, and the step counter, then converted by `live_ingest.py`. If the export has no `is_mock`, the mock/genuine label comes from the task card only. Until recordings exist, the live evaluation is reported as "no data", not estimated.

## 3. Outputs

- Code: `ml/fusion/*.py`; a verification script `ml/fusion/phase4_verify.py`.
- Metrics (JSON under `results/metrics/`): `phase4_dryad_imu_check.json`, `phase4_signals_*.json` summaries, `phase4_thresholds.json`, `phase4_split.json`, `phase4_dryad_heldout_eval.json`, `phase4_live_eval.json` (only if recordings exist), `phase4_verification.json`.
- Window-level CSVs (signals, rule ratios, score, flags) under `results/metrics/` for the evaluation sets.
- Figures under `results/plots/phase4_*.png` (residual distributions by subject, score timelines for each live session).
- Reports: `results/phase4_report.md`; `docs/fusion_engine.md` (new file; the committed `docs/model_documentation.md` is not touched). `results/phase4_run_log.md` is updated at every step.
- Android development plan (proposal only): section in `results/phase4_report.md`, covering the two evaluator-facing apps (identical frontend, background step counting, Reset Steps button, no rewards, crypto or tokens, GPS-only logic in App A, sensor-fusion logic in App B). No Android code is written.

## 4. Subject split (fixed here, before any residual is computed)

The split is written to `phase4_split.json` by code that uses no residual information. Rationale for the choice follows.

Constraint: Model A was **fit on Phase 2 train subjects** (0, 2, 4, 5, 6, 7, 8, 13, 14, 16, 17, 18), **tuned on validation subjects** (3, 10, 11) and **tested on** (1, 9, 12). A residual of Model A on its own train subjects is optimistically small (in-sample), so it must not set the R3 threshold. Model B has seen no Dryad subjects, so Model B signals are out-of-sample for every Dryad subject.

| Role | Subjects | Used for |
|---|---|---|
| **Calibration** | 3, 4, 5, 6, 7, 8, 10, 11 | R1, R2, R4 thresholds. All have motion. |
| Calibration, R3 only | 3, 10, 11 (Model A validation subjects) | R3 threshold. Validation subjects were used for Model A hyperparameter selection, a mild optimism that is stated, but they were not fit. |
| **Held-out evaluation** | 12, 13, 14, 16, 17, 18 | Never used to set or adjust any threshold, `K`, or quantile. |
| Held-out R3 (out-of-sample) | 12 | Model A test subject with motion. The only fully out-of-sample subject for R3. |
| Held-out R3 (in-sample for Model A, reported separately and labelled optimistic) | 13, 14, 16, 17, 18 | Shown only for completeness, not as a headline. |

Notes: subjects 12, 14 and 18 have non-monotonic step counters in some tracks (Verified; Phase 2 handled with a running maximum, reused here). Subject 8 has tracks with a very low motion rate (6.3 to 31 Hz); the window-drop rule removes the unusable windows and the dropped counts are reported. The split has 8 calibration and 6 held-out subjects, so held-out false-flag rates are subject-limited; they are reported per subject, not only pooled. If the Dryad IMU gate fails for some subjects, the split is not redone after seeing results; the affected subjects are reported as excluded.

Live data: calibration sessions (L1, L2, L3) may contribute to a **separate** on-device threshold check (reported as its own table). Dryad-calibrated thresholds are the headline thresholds. A comparison of "Dryad thresholds" against "Dryad + live calibration thresholds" is allowed, as long as the evaluation sessions stay untouched. If the live-calibration results show the Dryad thresholds fire on genuine on-device data, this is reported as a finding, and the thresholds are revised only through a documented step before the evaluation sessions are scored.

## 5. Success evaluation

No pass/fail on "accuracy". Reported computed numbers only:

1. **Dryad IMU gate:** written result (compatible / not compatible / ambiguous) with the measured quantities.
2. **Genuine false flags (Dryad held-out):** flagged windows and flagged episodes per genuine walking hour, per subject and pooled, for held-out subjects, next to the calibration-subject rate (which is expected to be lower by construction). Per-rule contribution. Model B class distribution on Dryad walking windows (a domain check: the share predicted WALKING / OTHER / STATIONARY).
3. **Live genuine (L1, L2 evaluation sessions):** false flags per hour per session. L1 doubles as the stationary-on-table scenario, evaluated separately from the walking scenarios, with Model B's class output distribution on it.
4. **Live mock (L4; L5, L6 if recorded):** per session: fraction of windows flagged, whether the episode flag fired, time from session start to the first flag, which rules fired. Each of the three live scenario types is reported on its own. `is_mock` baseline and a GPS-speed-only baseline are reported on the same sessions. Detection rates are shown as counts (for example 3 of 3 sessions), not percentages with unwarranted precision.
5. **Controls:** a GPS-only rule ("speed above the walking bound") and "Model B alone" are computed on the same data to show what the fusion adds, if anything.
6. **Reproducibility:** the pipeline runs twice with bit-identical outputs; frozen Model A and Model B files have the same SHA-256 before and after; `Data.zip` and raw datasets unchanged; no subject overlap between calibration and held-out (asserted); thresholds file hash recorded in every evaluation output; report numbers match JSON (automatic check). Existing user docs, `Kinesis_Literature_Survey.pdf` and `.agents/` are hash-checked before and after.

A "success" statement is limited to: the engine runs deterministically, the false-flag rate is measured on genuine held-out data, and the live mock sessions' outcomes are reported as they are. If the live evaluation has too few sessions, the report says so and makes no general claim.

## 6. Known limitations to keep in the report (Inferred unless computed)

- Model B was trained on pocket (MotionSense) and waist (UCI) placements, and on iPhone / Galaxy S II hardware. Dryad and live Android data are further domains. Phase 3 showed cross-dataset macro-F1 of 0.55 to 0.59 (Verified), so Model B's STATIONARY output on new devices may be unreliable. Rule R1 depends on it.
- Model B outputs for a phone resting on a table are untested in the training data (Phase 3 limitation 5); L1 is the first measurement.
- R3 uses the phone's own pedometer, which a physical fake (hand shake, swinger) can drive. L6, if recorded, will show this. Vehicles raise R2 without spoofing.
- Dryad has no attacks, so no detection rate can come from Dryad. Detection evidence rests on a small number of user-recorded sessions on few devices.
- A subject-wise 8/6 split of 14 subjects gives wide uncertainty on held-out false-flag rates.
- Model A alignment (H0) is only moderate confidence (Phase 3, Section 9). R3 inherits that uncertainty.
- Dryad GPS coordinates for 106 tracks are anonymised (shape and distance preserved, absolute positions not real), so no map-based plausibility check is used.

## 7. Order of work and git

1. Dryad IMU gate, then signals extraction, then split file, then calibration (thresholds frozen and hashed), then Dryad held-out evaluation, then live ingest and live evaluation if recordings exist, then verification and report.
2. Each step is logged in `results/phase4_run_log.md`. Commits are made per completed step with specific file paths only (never `git add -A`, `.`, or `docs/`). No push, no merge, no force or destructive git commands. Unrelated uncommitted docs, `Kinesis_Literature_Survey.pdf` and `.agents/` stay untouched.
3. Stop after Phase 4; the Android development plan is a proposal, not a start.

## 8. Open items for the user

1. Which logging app and phone(s) will be used for L1 to L6, and the intended number of sessions (Section 2).
2. Confirmation of the 8 calibration / 6 held-out Dryad split (Section 4).
3. Whether `docs/fusion_engine.md` (new file) is acceptable instead of editing `docs/model_documentation.md`.
