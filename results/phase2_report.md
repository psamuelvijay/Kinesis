# Phase 2 Report: Dryad Preparation and GPS-only Step Estimator (Model A)

Branch `phase2-gps-step-estimator`. Phase 3 has not been started.

**Convention.** Every number is copied from the JSON files in `results/metrics/` and `ml/models/`. Each section ends with **Verified** (computed from data, with the source file) and **Inferred** (interpretation, not directly tested).

---

## 1. Dataset preparation report

**Input.** Dryad Walking Activity Dataset, 198 tracks, 18 subjects (`phase2_windows_summary.json`). Excluded before Phase 2: `15_0` to `15_4` (subject 15 has no GNSS) and `8_10` (no metadata row). Raw files are unmodified. MotionSense and UCI HAR are not used in Phase 2.

**Windowing.** Non-overlapping 5 s windows from max(testStart, 0) to min(testEnd, last steps timestamp). 14,480 windows generated, 13,466 kept (`phase2_exclusions.json`).

| Window exclusion reason | Count |
|---|---|
| Overlaps a gap > 10 s between kept fixes (includes GPS stopping early or starting late) | 688 |
| No kept fix in window | 221 |
| No fix with valid speed (-1 or NaN) | 105 |
| Total excluded | 1,014 |

No whole track was excluded (`track_level_exclusions` is empty).

**Target.** Steps in the window: running-maximum cumulative counter at window end minus at window start.

| Target statistic (13,466 windows) | Value |
|---|---|
| Mean | 8.625 |
| Median | 9.0 |
| Std | 2.678 |
| Min / Max | 0 / 27 |
| 5th / 95th percentile | 2 / 12 |

Windows per subject range from 311 (subject 17) to 2,406 (subject 14).

**Kept steps vs metadata.** Kept windows hold 116,145 of 124,652 total steps (`phase2_reconciliation.json`). Per-track kept fraction: mean 0.923, median 0.9831, min 0.0231. Summing all windows plus the steps before the first window and after the last full window reproduces the final counter in all 198 tracks within 1 step, and exactly equals `totSteps` in 196. The two 1-step exceptions are `5_7` and `14_7`.

**GPS cleaning** (`phase2_cleaning_report.json`). Parameters: gap threshold 10 s, confInterval limit 50 m, teleport limit 10 m/s.

| Row count | Value |
|---|---|
| Raw GPS rows | 60,468 |
| Non-finite rows dropped | 0 |
| Exact duplicates dropped | 44 |
| confInterval > 50 m dropped | 169 |
| Teleport (> 10 m/s) dropped | 73 |
| Kept rows | 60,182 |
| Kept rows with invalid speed (speed -1: 240, NaN: 899 in raw; 939 in kept fixes) | 939 |
| Tracks with non-monotonic `ms` | 16 |
| Tracks with exact duplicates | 38 |
| Tracks with long gaps (> 10 s) | 54 |
| Long gaps total | 140 |

The 10 s threshold is twice the window length. Dense tracks have median interval 1 s (p99.9 4.3 s) and sparse-fix tracks median 4 s (p95 7 s, p99 13 s). Shorter gaps are handled using observed fixes only, with `coverage_frac` as a feature. Longer gaps are excluded. Nothing is interpolated.

**Splits** (`phase2_splits.json`, seed 42, best of 20,000 seeded draws minimising imbalance).

| Set | Subjects | Tracks | Windows | Mean target |
|---|---|---|---|---|
| Train | 0, 2, 4, 5, 6, 7, 8, 13, 14, 16, 17, 18 | 119 | 9,148 | 8.588 |
| Validation | 3, 10, 11 | 44 | 2,201 | 8.411 |
| Test | 1, 9, 12 | 35 | 2,117 | 9.007 |

Stored checks: `zero_subject_overlap`, `all_subjects_assigned`, `no_track_in_two_sets` are all true.

**Verified:** counts above from the cited files. **Inferred:** that 10 s is an appropriate gap threshold (justified from the interval distribution, not tuned against model performance).

---

## 2. Alignment findings (`phase2_alignment_check.json`)

Question: do `positions.ms` and `steps.ms` share one clock (H0: signalStart) or is positions relative to testStart (H1)?

| Measure | Result |
|---|---|
| Tracks checked | 198 |
| Tracks with testStart > 5 s | 15 |
| Tracks with `ms` < 0 in positions | 180 (819 rows) |
| Median (last position ms - last steps ms) | 181 ms (p25 -679.5, p75 1456.5) |
| Tracks with abs(last position - last steps) <= 5 s | 175 of 198 |
| Tracks with that difference > 10 s | 8 (`3_8`, `5_4`, `8_6`, `10_2`, `11_11`, `13_11`, `11_15`, `18_1`) |
| End-of-recording residual smaller under H0 than H1, all tracks | 142 |
| Same, tracks with testStart > 5 s | 13 of 15 (median residual H0 1,747 ms vs H1 6,686 ms) |
| Speed vs step-rate cross-correlation: median lag | -2 s, std 41.0 s |
| Cross-correlation tracks with peak >= 0.5 | 72, of which 15 within +/-2 s and 39 within +/-5 s |
| Median peak correlation / median correlation at lag 0 | 0.4268 / 0.179 |
| Cumulative-distance fit RMS, median H0 vs H1 | 0.0204 vs 0.0195 (not separable) |
| steps `ms` - `endDate`, median per track | 538.5 ms (min 24, max 3,136) |
| Observed GNSS and steps sampling rate vs metadata | ratio 1.0 in all tracks |
| Last step value equals `totSteps` | 197 of 198 tracks |
| GPS path / distanceReference | median 1.0308; 25 tracks outside 0.8-1.25 |

**Decision recorded in the file:** adopt H0, apply no lag shift, no testStart re-basing. Stated confidence: moderate. Reason for no shift: estimated lags are wide and sign-mixed, so shifting would inject noise.

**What is verified:** both streams end at about the same time in most tracks and the end-of-recording residual favours H0, including in the tracks where H0 and H1 differ by more than 5 s. **What is not verified:** exact alignment. The cross-correlation has low power, the cumulative-distance test cannot separate H0 from H1, and offsets of a few seconds cannot be excluded. The README of the dataset is self-contradictory about the zero point. Per-track "alignment verified" is therefore **not** claimed; only the clock-identity hypothesis is supported. Eight tracks show one stream stopping early, and their affected windows are lost through the gap rules above.

**Sensitivity (`phase2_model_metrics.json`, supplementary).** Pairing window i features with window i+k targets (test set, Random Forest): k=-1 R2 0.268 (MAE 1.48); k=0 R2 0.347 (MAE 1.406); k=+1 R2 0.309 (MAE 1.335). The shifts tested are coarse (5 s); the testStart re-basing and sub-window shifts were not tested. Note k=+1 has lower MAE but k=0 has higher R2, so the data do not clearly single out a shift.

---

## 3. Step-counter decrease findings (`phase2_step_monotonicity_analysis.json`)

| Finding | Value |
|---|---|
| Tracks with decreases | 40 of 198 (subjects 3, 10, 11, 12, 14, 18) |
| Decrease events | 135 |
| Event size | 1: 110, 2: 17, 3: 5, 4: 1, 6: 1, 10: 1 |
| Events inside one `endDate` batch | 135 of 135 (0 cross a batch boundary) |
| Events where ms gap between the pair is 0 to 12 ms | median 1 ms, max 12 ms |
| Rows until counter recovers | 2 rows: 122, 3: 10, 4: 1, 11: 1; never recovered: 1 |
| Decrease tracks with duplicate `ms` | all 40 (median 105 duplicate rows, other tracks median 0) |
| Still decreasing after stable sort by `ms` | 40 tracks, 135 events |
| After sort by (`endDate`, steps) | 1 event remains |
| Decrease tracks whose final value equals `totSteps` | 40 of 40 (39 of 40 final equals max) |

**Handling rule adopted.** The counter is treated as cumulative with rows delivered out of order inside a reporting batch. Cumulative value at time T is the running maximum of steps over rows with `ms` <= T. The window target is the difference between window ends. Individual differences are not clipped. The window-rule comparison on 14,589 windows found 0 negative windows under any rule, but clipping differs from running-max in 138 windows, and clipped full-track sums overcount `totSteps` in all 40 decrease tracks (up to 14 steps in one track).

**Known limitation (from the file).** A window boundary inside a batch can credit up to the batch's maximum decrease (at most 4 steps) to one window and take it back in the next. The net over the track is exact. Two tracks are special: `14_4` has one row with steps 0 inside a batch (-6) and `14_9` has a -10 jump inside a batch, both recovering within the batch.

**Verified:** all counts above. **Inferred:** that decreases are out-of-order delivery rather than corrections. The pattern fits (all inside one `endDate` batch, recover within 2 to 4 rows, final values match `totSteps`) but the pedometer's internal behaviour was not observed.

---

## 4. Preprocessing and exclusion decisions

1. Pre-Phase 2: subject 15 (no GNSS) and `8_10` (no metadata) excluded.
2. GPS rows sorted by `ms`; 44 exact duplicates dropped; 1 same-`ms` row with differing values kept.
3. Fixes with confInterval > 50 m (169) and fixes implying > 10 m/s (73) dropped.
4. Speed -1 or NaN is treated as invalid and not used as a speed value. Windows with no valid speed are excluded (105).
5. Gaps > 10 s excluded with no interpolation (688 windows). Windows with no fix excluded (221).
6. Only windows from max(testStart, 0) to the end of the shorter stream are generated.
7. No H0/H1 lag shift; no per-track alignment correction.
8. Step target: running-max rule (Section 3).
9. 25 tracks with GPS path / distanceReference outside 0.8-1.25 are **kept and flagged** (`distance_anomaly`). After cleaning, 20 are still outside that range. They contribute 1,287 windows (678 train, 562 validation, 47 test). Reason recorded: window-level cleaning removes corrupted fixes, targets come from `steps.csv` independent of reference distance, and the ratio is also affected by `distanceReference`. Metrics are reported with and without them (Section 5).
10. Absolute lat/lon (anonymised), heading and altitude are not model inputs.
11. NaN features (single-fix windows, first window of a track for `lag_*`) are passed natively to Random Forest and XGBoost.
12. Hyperparameters tuned on validation subjects only; the final models are fit on train subjects only.

---

## 5. Model results

Test subjects 1, 9, 12; 2,117 windows; steps per 5 s window (`phase2_model_metrics.json`).

### 5.1 Test set, headline

| Model | MAE | RMSE | R2 |
|---|---|---|---|
| Train-mean baseline | 1.791 | 2.595 | -0.027 |
| Linear distance baseline | 1.911 | 2.727 | -0.134 |
| Random Forest (selected on validation) | 1.403 | 2.069 | 0.347 |
| XGBoost | 1.399 | 2.041 | 0.365 |

### 5.2 Validation set (2,201 windows; used for tuning and selection)

| Model | MAE | RMSE | R2 |
|---|---|---|---|
| Train-mean baseline | 2.285 | 3.305 | -0.003 |
| Linear distance baseline | 2.862 | 4.001 | -0.470 |
| Random Forest | 2.016 | 2.893 | 0.231 |
| XGBoost | 2.032 | 2.894 | 0.231 |

Selection rule: lowest validation MAE (`selected_model` = random_forest). Random Forest best parameters: max_depth 8, min_samples_leaf 5, max_features 1.0. XGBoost: max_depth 5, learning_rate 0.03, n_estimators 300, min_child_weight 1. Random Forest grid had 18 configurations, XGBoost 8.

### 5.3 Test performance by walking-speed range (GPS window speed)

Bins in m/s. Bins with n < 30 are flagged too few (`speed_bin_min_n_flag` = 30).

| Bin | n | Train-mean MAE | Linear MAE | RF MAE | RF R2 | XGB MAE | XGB R2 |
|---|---|---|---|---|---|---|---|
| <0.5 | 81 | 4.970 | 3.569 | 2.196 | 0.510 | 2.156 | 0.554 |
| 0.5-1.0 | 398 | 1.122 | 3.116 | 1.315 | 0.118 | 1.306 | 0.162 |
| 1.0-1.5 | 1,057 | 1.360 | 1.399 | 1.232 | 0.079 | 1.238 | 0.097 |
| 1.5-2.0 | 578 | 2.582 | 1.729 | 1.658 | 0.034 | 1.642 | 0.043 |
| >2.0 (too few) | 3 | 4.196 | 12.394 | 2.719 | 0.409 | 3.243 | 0.294 |

In the 0.5-1.0 bin the train-mean baseline (MAE 1.122) beats both models (1.315, 1.306). By the reference walking speed from metadata (`by_speed_bin_ref`), test bins are 0.5-1.0 (n=72), 1.0-1.5 (n=1,554), 1.5-2.0 (n=491); there are no test windows <0.5 or >2.0. RF MAE there: 1.808, 1.291, 1.698; XGBoost: 1.667, 1.296, 1.687. Validation bins are in `phase2_model_metrics.json`.

### 5.4 Per-subject test results (MAE / R2)

| Subject | n | Train-mean | Linear | Random Forest | XGBoost |
|---|---|---|---|---|---|
| 1 | 643 | 1.182 / -0.005 | 1.525 / -0.516 | 1.090 / 0.068 | 1.105 / 0.088 |
| 9 | 758 | 2.629 / -0.581 | 1.701 / -0.252 | 1.729 / 0.079 | 1.711 / 0.094 |
| 12 | 716 | 1.451 / -0.036 | 2.478 / -0.350 | 1.338 / 0.404 | 1.333 / 0.429 |

Mean actual vs predicted steps per window (RF): subject 1 8.451 vs 9.007, subject 9 10.360 vs 9.800, subject 12 8.074 vs 7.892.

### 5.5 Full-track step totals (test, 35 tracks, kept windows only)

| Model | Mean abs error (steps) | Median abs % error | Pooled bias % |
|---|---|---|---|
| Train-mean | 55.839 | 5.701 | -4.650 |
| Linear distance | 67.242 | 9.837 | -1.125 |
| Random Forest | 36.953 | 6.608 | -1.035 |
| XGBoost | 35.105 | 5.725 | -1.436 |

Actual total 19,068 steps; predicted totals: Random Forest 18,870.708, XGBoost 18,794.195. Totals are summed over kept windows only, so they are not whole-track estimates.

### 5.6 Sensitivity and supplementary runs (not used for selection)

| Run | Model | n | MAE | RMSE | R2 |
|---|---|---|---|---|---|
| Test, flagged tracks removed from evaluation only | Random Forest | 2,070 | 1.382 | 2.033 | 0.264 |
| Test, flagged tracks removed from evaluation only | XGBoost | 2,070 | 1.385 | 2.019 | 0.274 |
| Test, flagged tracks removed from training and evaluation | Random Forest | 2,070 | 1.379 | 2.012 | 0.279 |
| Test, flagged tracks removed from training and evaluation | XGBoost | 2,070 | 1.399 | 2.013 | 0.278 |
| Leave-one-subject-out, all 18 subjects pooled | Train-mean | 13,466 | 1.799 | 2.701 | -0.017 |
| Leave-one-subject-out | Linear distance | 13,466 | 2.226 | 3.216 | -0.442 |
| Leave-one-subject-out | Random Forest | 13,466 | 1.467 | 2.230 | 0.307 |
| Leave-one-subject-out | XGBoost | 13,466 | 1.516 | 2.266 | 0.284 |

LOSO per-subject MAE (mean, std, min, max): Random Forest 1.551, 0.555, 0.817, 2.941; XGBoost 1.589, 0.536, 0.914, 2.912; train-mean 1.897, 0.682, 0.726, 3.290. In LOSO, subject 4 has train-mean MAE 0.726 against Random Forest 0.817 and XGBoost 0.914, and several subjects have negative Random Forest R2 (for example subjects 0, 4, 7, 8). The LOSO folds reuse hyperparameters tuned on validation subjects 3, 10, 11, so they are not fully independent of tuning.

### 5.7 Feature importance (validation permutation, MAE increase, Random Forest)

Largest: conf_mean 0.1558, lag_speed_mean 0.2363, derived_speed_mps 0.2200. Next: n_fixes 0.0220, displacement_m 0.0182. Random Forest native (impurity) importance: derived_speed_mps 0.3455, lag_speed_mean 0.2681, conf_mean 0.1202. Speed from raw GPS (`speed_mean`) has permutation importance 0.0050.

**Verified:** all values in this section. **Inferred:** that `conf_mean` ranking high reflects per-device or per-environment effects rather than walking physiology (see Limitations); this was not tested.

---

## 6. Evaluation methodology

- **Unit.** Non-overlapping 5 s window; target is steps in the window.
- **Splits.** By subject, fixed seed 42, no subject in more than one set. Tuning on train/validation only; test subjects were scored with the final fixed configuration (`protocol` field in `phase2_splits.json`).
- **Metrics.** MAE, RMSE, R2 on windows; speed-range tables by GPS window speed (primary) and by metadata reference speed; bins with n < 30 flagged; per-subject table; full-track totals on kept windows.
- **Baselines.** Train-mean predictor and linear model steps = 1.4385 x (speed_mean x 5 s), with the constant being the median ratio over train windows with distance >= 0.5 m.
- **Models.** Random Forest (300 trees) and XGBoost on 15 GPS-only features (`ml/models/feature_list.json`). Models fit on train subjects only; validation not merged into training.
- **Supplementary.** Flagged-track ablation, window-shift sensitivity, leave-one-subject-out. These are labelled supplementary and not used to choose the model.

**Not done in this step.** I did not re-run the scripts from raw data in this step, and did not re-check the SHA256 hashes in `.agents/tasks/phase2/hashes_before.json`. Plan item 9 covers those checks; if an earlier step did them, their output is the evidence, not this report.

---

## 7. Limitations

1. **Alignment is adopted, not proven.** Moderate confidence (Section 2). Sub-window offsets cannot be excluded, and the window-shift sensitivity moves test R2 from 0.347 to 0.268 or 0.309.
2. **Small test set.** Three subjects, 2,117 windows. Differences between Random Forest and XGBoost on test (MAE 1.403 vs 1.399, R2 0.347 vs 0.365) are small compared with the per-subject spread (RF MAE 1.090 to 1.729), so no winner is claimed. Validation selected Random Forest by 0.016 MAE.
3. **Modest R2.** Test R2 0.347 / 0.365. Within-bin R2 for the 1.0-1.5 and 1.5-2.0 m/s bins is below 0.1 for both models. The models beat the train-mean baseline in MAE overall (1.403 vs 1.791) but not in the 0.5-1.0 m/s bin or for some LOSO subjects.
4. **Weak cadence signal in GPS speed (inferred).** Target std is 2.678 steps while the median is 9; most windows are near steady cadence. The modest R2 is consistent with GPS speed carrying limited information about cadence, but stride length and cadence trade-offs were not analysed.
5. **GPS speed range.** Only 62 windows overall are > 2.0 m/s (3 in test), so fast walking and running are not evaluated. 945 windows are < 0.5 m/s.
6. **Distance-anomalous tracks kept.** 25 tracks (1,287 windows) kept; 20 still anomalous after cleaning. Removing them lowers test R2 (RF 0.347 to 0.264), so headline R2 is partly driven by them.
7. **Kept-window coverage.** Kept windows cover 92.3% of steps on average per track but as little as 2.3% in one track; 1,014 windows lost to gaps, no fix or invalid speed.
8. **Decrease handling edge effect.** Up to 4 steps can move between adjacent windows when a boundary falls inside a batch.
9. **Population and device.** Dryad is hand-held phone data with many phone models, UK and Swedish subjects (patients and non-patients). Generalisation to Android pocket/waist use is untested. Subjects 16, 17, 18 share the same mean reference speed (1.1701) in `phase2_splits.json`; I have not checked why.
10. **`conf_mean` as a feature.** It has high permutation importance but is a receiver attribute, not a gait property. It may not transfer to other phones.
11. **No step data as input**, by design. This model estimates steps from GPS alone, so it is a fallback or cross-check, not a replacement for a step counter.

---

## 8. Proposed Phase 3 plan (not started)

Goal: prepare MotionSense and UCI HAR for the activity classifier (Model B), then train and evaluate it. Subject-independent splits throughout.

### 8.1 Phase 1 issues that shape the plan
| Issue | Source | Consequence |
|---|---|---|
| MotionSense has no timestamps in any of the 3 streams; 50 Hz is documented, not verified | `inspect_motionsense.json` (`sampling_rate.measured_from_timestamps` is null) | Treat rows as 50 Hz by assumption; window by sample count; cannot resample or check drift |
| Stream row counts differ: A_DeviceMotion 1,412,865 rows, B_Accelerometer 1,433,825, C_Gyroscope 1,413,262 over 360 recordings each. All 360 recordings are flagged as having a row-count mismatch, maximum absolute difference 198 rows (for example subject 1, dws trial 1: A 1,751, B 1,781, C 1,751) | `n_row_count_mismatch` 360, `max_abs_row_diff_A_vs_B_C` 198 | Decide a single alignment rule (for example truncate to the common length from the start) and record rows dropped per recording; do not assume row i in A matches row i in B. Whether truncation from the start is correct is unknown because there are no timestamps |
| UCI HAR is pre-cut: 128-sample windows (2.56 s), 50% overlap per documentation (not checked against data here) | `inspect_uci_har.json` | Window length fixed; cannot re-window to 5 s. Overlapping windows from the same subject must stay in the same split |
| UCI `body_acc` is gravity-separated; `total_acc` includes gravity | docs/dataset_documentation.md | Use `total_acc` (g, with gravity) as the raw-accelerometer analogue, or apply the same filter to both datasets; do not mix |
| MotionSense has two accelerometer sources: A_DeviceMotion (`userAcceleration` and `gravity` columns, a fused device-motion output) and B_Accelerometer (x, y, z) | `inspect_motionsense.json` columns | Android offers a raw accelerometer (`TYPE_ACCELEROMETER`) and a fused linear acceleration (`TYPE_LINEAR_ACCELERATION`). Map explicitly: B_Accelerometer to raw accelerometer and `userAcceleration` to linear acceleration. Whether B_Accelerometer includes gravity and its units (g or m/s^2) are not stated in the inspection file and must be checked from values. Android reports m/s^2 |
| Different devices and placements: iPhone pocket (MotionSense), Samsung waist (UCI) | docs/dataset_documentation.md | Expect cross-dataset shift; report within-dataset and cross-dataset results separately |
| Label mapping differs | docs/dataset_documentation.md | Map to WALKING / STATIONARY / OTHER as documented; check class balance after mapping |

### 8.2 Proposed steps
1. **Android sensor mapping decision (needs user sign-off).** Choose the input signal: raw accelerometer with gravity (MotionSense B_Accelerometer if it includes gravity, UCI `total_acc`) versus gravity-removed (MotionSense `userAcceleration`, UCI `body_acc`). The first is closer to what an Android app can obtain without a fusion filter; the second removes orientation dependence. Decide units (g vs m/s^2) and axis conventions (iOS and Android axis signs differ).
2. **MotionSense preparation.** Align streams by a documented rule; log per-recording row-count differences; derive windows by sample count (for example 128 samples to match UCI, or 2.5 s at assumed 50 Hz); split by subject (24 subjects).
3. **UCI HAR preparation.** Use the provided subject-disjoint 21/9 train/test split; carve a validation set from the train subjects; use the 128-sample windows directly; do not use the 561 engineered features if the Android app computes its own features.
4. **Common feature set.** Magnitude and per-axis statistics, and gyroscope features where available, computed identically on both datasets; no features that depend on gravity separation unless applied to both.
5. **Evaluation.** Subject-independent splits; macro-F1 and per-class recall; confusion matrix; within-dataset and cross-dataset (train on one, test on the other) tables; report that labels contain no GPS-spoofing information (limitation 5 in `dataset_documentation.md`).
6. **Outputs.** Preparation report, exclusion counts, metrics JSON, saved model, figures. Same convention as Phase 2: no numbers outside the metric files.

### 8.3 Open questions for the reviewer
- Which Android sensor type and units should the classifier target?
- Window length: 128 samples to match UCI, or longer?
- Should cross-dataset testing be the headline result?
- For Model A: keep distance-anomalous tracks in the headline, and should a second alignment convention be explored before Phase 3?

---

## 9. Verified versus inferred

**Verified from data (metric files):** all counts, metrics, split compositions and checks, exclusion counts, step-decrease statistics, cleaning counts, reconciliation values, feature importance values, and the Phase 1 facts quoted in Section 8.1 from `inspect_motionsense.json` and `inspect_uci_har.json`.

**Inferred or adopted, not proven:** alignment of GPS and step clocks (moderate confidence); decreases being out-of-order delivery; 10 s as the gap threshold; interpretation of weak GPS-cadence signal; why `conf_mean` is important; the Android mapping advice in Section 8 (including whether B_Accelerometer contains gravity); why subjects 16 to 18 share a mean reference speed.

**Not done in this step:** re-running scripts, hash checks, and Phase 3.

## 10. Files

- Scripts: `ml/preprocessing/` and training/evaluation scripts in `ml/`
- Metrics: `results/metrics/phase2_*.json`, `results/metrics/phase2_test_predictions.csv`
- Plots: `results/plots/phase2_*.png`
- Models: `ml/models/` (`random_forest.joblib`, `xgboost.json`, `best_model.joblib`, `baselines.joblib`, `training_config.json`, `feature_list.json`, `evaluation_metrics.json`)
- Plan: `results/phase2_plan.md`
- Documentation: `docs/model_documentation.md`
