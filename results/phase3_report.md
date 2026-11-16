# Phase 3 report: Model B activity classifier, plus Model A follow-ups

Branch `phase3-activity-classifier`. The Phase 3 work is committed as `cb1de1a` on this branch (correction made in Phase 4; the original text said "Nothing is committed"). The Phase 2 artefacts and docs noted below as uncommitted were still uncommitted when this report was written. Status labels: **Verified** means checked against code or the stored JSON files in this repository. **Inferred** means reasoned, documented by a third party, or not testable here.

**Scope statement.** Model B classifies physical activity (WALKING / STATIONARY / OTHER) from phone motion sensors. It was not trained or evaluated for GPS spoofing, and no result below says anything about spoofing detection. Spoofing detection is proposed for the later fusion stage (Section 14).

All numbers come from `results/metrics/activity_*.json`, `phase3_modelA_*.json`, `phase3_modified_files_inspection.json` and `phase3_verification.json`. `phase3_verification.json` records an automatic check that the figures quoted here match those files.

## 1. Dataset preparation (Verified for counts; Inferred for device facts)

| Item | MotionSense | UCI HAR |
|---|---|---|
| Stream / columns used | `A_DeviceMotion`: `userAcceleration.x/y/z`, `rotationRate.x/y/z` | `body_acc_x/y/z`, `body_gyro_x/y/z` from Inertial Signals |
| Recordings / rows | 360 recordings, 1,412,865 rows | 10,299 rows (windows) as provided |
| Windowing | 128 samples, stride 64, by sample count within one recording; trailing partial window dropped | Provided 128-sample windows used as is (no resampling) |
| Rows dropped | 11,329 trailing rows (1,401,536 rows in windows; reconciles; 0 recordings shorter than a window) | none |
| Windows | 21,539 | 10,299 |
| Subjects | 24 | 30 |

Excluded as inputs: `total_acc`, gravity and attitude streams, the `B_`/`C_` MotionSense streams, UCI's 561 engineered features, GPS and step data. The Dryad `motion.csv` was not used.

UCI overlap check (Verified): of 9,899 consecutive same-subject, same-activity row pairs, 9,442 match the 50% overlap exactly. Windows overlap 50% in both datasets, so window counts overstate the number of independent samples.

Class balance after label mapping (windows, WALKING / STATIONARY / OTHER):

| Set | MotionSense | UCI HAR |
|---|---|---|
| Train | 3505 / 6556 / 4178 (16 subjects) | 888 / 3122 / 1541 (16 subjects) |
| Validation | 894 / 1703 / 1116 (4 subjects) | 338 / 945 / 518 (5 subjects) |
| Test | 876 / 1678 / 1033 (4 subjects) | 496 / 1560 / 891 (9 subjects) |

Test subjects: MotionSense 7, 11, 15, 20; UCI 2, 4, 9, 10, 12, 13, 18, 20, 24. UCI validation subjects are 5 seeded subjects taken from the 21 provided train subjects. LAYING exists only in UCI. There are no exclusions of subjects or recordings in Model B.

Model A data (Dryad, for Section 9; Verified, from the Phase 2 JSON): 198 tracks, 18 subjects, 14,480 windows generated, 13,466 kept. 688 windows dropped for long-gap overlap, 221 for no fix, 105 for no valid speed.

## 2. Label mapping (Verified)

| Source label | Class |
|---|---|
| MotionSense `wlk`; UCI WALKING | WALKING |
| MotionSense `sit`, `std`; UCI SITTING, STANDING, LAYING | STATIONARY |
| MotionSense `jog`, `ups`, `dws`; UCI WALKING_UPSTAIRS, WALKING_DOWNSTAIRS | OTHER |

Jogging and stairs are never mapped to STATIONARY. The mapping is asserted in the pipeline and re-checked in `phase3_verification.json`.

## 3. Processing differences between the datasets (Verified from READMEs and code; Inferred where noted)

- MotionSense `userAcceleration`: gravity removed by iOS Core Motion sensor fusion, in g. The algorithm is not inspectable (Inferred whether it smooths the signal).
- UCI `body_acc`: gravity separated with a 0.3 Hz Butterworth low-pass, after a median filter and a 20 Hz 3rd-order Butterworth filter (Verified in README and `features_info.txt`). MotionSense has no documented equivalent filter.
- Device and placement: iPhone 6s in a front trouser pocket (MotionSense, documented, not re-verifiable from the files) versus Samsung Galaxy S II at the waist (UCI, documented).
- Sampling: 50 Hz is documented for both. MotionSense has no timestamp column, so 50 Hz is assumed and not measurable.
- Axis conventions are not verified between the datasets. The features are magnitudes, so axis conventions and orientation do not enter the model.

## 4. Features (Verified)

Eleven features, identical code on both datasets, no per-axis features, no GPS or step inputs:
acceleration-magnitude mean, std, RMS, variance and energy; gyro-magnitude mean and variance; acceleration peak count (`find_peaks`, prominence 0.1 g, distance 10 samples); dominant frequency, spectral energy and normalised spectral entropy from the rFFT of the mean-removed magnitude. The list is in `ml/models/activity_feature_list.json`. Deviation from `results/phase3_plan.md`: output names use `activity_*` in the existing folders instead of `ml/models/model_b/` and `phase3_*`, and features are magnitude-only rather than per-channel.

## 5. Evaluation methodology (Verified)

- Subject-independent splits, zero overlap asserted (seed 42): MotionSense 16/4/4 subjects, UCI 16/5/9.
- Models: majority baseline, logistic regression, Random Forest, XGBoost. Hyperparameters and model selection use validation macro-F1 only. Final models are fit on train subjects only. Each model is scored once on the test set for the headline.
- Metrics: accuracy, per-class precision, recall and F1, macro-F1, weighted-F1, confusion matrices (counts and row-normalised, in `results/confusion_matrices/`).
- Within-dataset subject-independent test results are the headline. Cross-dataset results are a separate generalisation experiment (`activity_generalisation_metrics.json`, `headline: false`).
- Supplementary grouped cross-validation is labelled supplementary. The MotionSense leave-one-subject-out run uses all 24 subjects, including the test subjects, so it is not a test-set number.
- The combined model is scored on the test sets in two places of `run_pipeline.py` with identical configuration and identical results. No selection effect.

## 6. Headline within-dataset results (Verified)

Test set, subject-independent:

| Dataset | Model | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| MotionSense (3,587 windows, 4 subjects) | majority | 0.4678 | 0.2125 | 0.2982 |
| | logistic regression | 0.8798 | 0.8488 | 0.8799 |
| | Random Forest | 0.9328 | 0.9139 | 0.9320 |
| | **XGBoost (selected on validation)** | 0.9378 | 0.9207 | 0.9373 |
| UCI HAR (2,947 windows, 9 subjects) | majority | 0.5294 | 0.2308 | 0.3664 |
| | logistic regression | 0.8802 | 0.8305 | 0.8826 |
| | Random Forest | 0.9135 | 0.8719 | 0.9148 |
| | **XGBoost (selected on validation)** | 0.9206 | 0.8835 | 0.9220 |

Selected XGBoost per-class (WALKING / STATIONARY / OTHER):

| Dataset | Precision | Recall | F1 |
|---|---|---|---|
| MotionSense | 0.923 / 0.999 / 0.857 | 0.813 / 1.000 / 0.943 | 0.865 / 1.000 / 0.898 |
| UCI HAR | 0.719 / 0.999 / 0.921 | 0.877 / 0.997 / 0.810 | 0.790 / 0.998 / 0.862 |

Confusion counts (rows true, columns predicted W/S/O): MotionSense [[712,1,163],[0,1678,0],[59,0,974]]; UCI [[435,0,61],[3,1556,1],[167,2,722]]. WALKING and OTHER confuse with each other. STATIONARY is separated almost perfectly.

Per-subject accuracy ranges from 0.906 to 0.975 (MotionSense) and 0.826 to 0.974 (UCI; subjects 9 and 10 are lowest). The Random Forest versus XGBoost gap is small relative to this subject variation on 4 and 9 test subjects, so the model ranking is weakly supported.

Class weighting changed validation macro-F1 by about ±0.02 with inconsistent sign (details in the JSON).

## 7. Supplementary and cross-dataset results (reported separately; Verified)

**Supplementary grouped CV (selected XGBoost, tuned parameters fixed):** MotionSense leave-one-subject-out, 24 subjects: accuracy 0.9202, macro-F1 0.9005 (includes the test subjects). UCI 5-fold grouped CV over the 21 train subjects: accuracy 0.9127, macro-F1 0.8598.

**Cross-dataset generalisation (not headline):**

| Experiment | Accuracy | Macro-F1 |
|---|---|---|
| MotionSense train, UCI test subjects | 0.8056 | 0.5805 |
| MotionSense train, all UCI | 0.8122 | 0.5922 |
| UCI train, MotionSense test subjects | 0.7254 | 0.5539 |
| UCI train, all MotionSense | 0.7244 | 0.5579 |
| Combined train (MotionSense + UCI), MotionSense test | 0.9465 | 0.9319 |
| Combined train, UCI test | 0.9213 | 0.8832 |

Cross-dataset macro-F1 (0.55 to 0.59) is far below within-dataset (0.88 to 0.92). Likely causes, not isolated by any experiment (Inferred): device, placement (pocket vs waist), gravity-removal method, prefiltering, and UCI having no jogging. The combined model matches within-dataset performance only because it saw both domains. It says nothing about a third device, and it has not been evaluated on Android data.

## 8. Jog / stairs / stationary error analysis (Verified)

Selected XGBoost, within-dataset test windows:

| Original activity | MotionSense: predicted W / S / O | UCI HAR: predicted W / S / O |
|---|---|---|
| walking | 712 / 1 / 163 (n=876) | 435 / 0 / 61 (n=496) |
| jogging | 3 / 0 / 312 (n=315) | not in UCI |
| upstairs | 35 / 0 / 370 (n=405) | 132 / 2 / 337 (n=471) |
| downstairs | 21 / 0 / 292 (n=313) | 35 / 0 / 385 (n=420) |
| sitting | 0 / 896 / 0 (n=896) | 1 / 490 / 0 (n=491) |
| standing | 0 / 782 / 0 (n=782) | 2 / 530 / 0 (n=532) |
| laying | not in MotionSense | 0 / 536 / 1 (n=537) |

- Jog and stairs windows predicted STATIONARY: MotionSense 0 of 1,033; UCI 2 of 891 (0.22%).
- Stationary windows predicted WALKING: MotionSense 0 of 1,678; UCI 3 of 1,560 (0.19%).
- The main confusion is walking vs upstairs: 28% of UCI upstairs windows are called WALKING. Walking is called OTHER in 18.6% (MotionSense) and 12.3% (UCI) of windows.
- Cross-dataset (Verified, not headline): on UCI test subjects the MotionSense-trained model calls 47 of 891 jog/stairs windows (5.3%) STATIONARY. On all UCI windows it calls 82 of 1,544 upstairs and 301 of 1,722 walking windows (17.5%) STATIONARY. The UCI-trained model predicts 14 of 1,678 MotionSense stationary test windows (0.8%) as WALKING. Cross-device use of Model B for the stationary decision is therefore not safe without in-domain data.

## 9. Model A follow-ups (Verified)

Model A is the Phase 2 GPS-only step estimator. The Phase 2 headline is unchanged: the reruns use the fixed Phase 2 hyperparameters and split in `.venv` (scikit-learn 1.9.1, xgboost 3.4.1). The H0 rerun reproduces the committed headline with an absolute difference of 0.0.

**Alignment sensitivity** (test set, subjects 1, 9, 12; MAE / R2). H0 is the headline assumption that `positions.ms` and `steps.ms` share a clock; H1 uses position timestamps relative to `testStart`; lags shift the GPS clock.

| Condition | n test | Random Forest | XGBoost |
|---|---|---|---|
| H0 headline | 2117 | 1.4028 / 0.347 | 1.3989 / 0.365 |
| H1 (testStart) | 2115 | 1.3814 / 0.352 | 1.3819 / 0.362 |
| +1 s | 2112 | 1.3792 / 0.354 | 1.3875 / 0.363 |
| -1 s | 2122 | 1.3943 / 0.359 | 1.4083 / 0.357 |
| +2 s | 2116 | 1.3487 / 0.377 | 1.3659 / 0.371 |
| -2 s | 2132 | 1.3957 / 0.362 | 1.3852 / 0.374 |
| +5 s | 2099 | 1.3565 / 0.360 | 1.3685 / 0.356 |
| -5 s | 2127 | 1.4481 / 0.346 | 1.4657 / 0.345 |

Test MAE moves within about 1.35 to 1.47 across all shifts. Seed-to-seed std on H0 is 0.0017 (RF) and 0.0041 (XGBoost) test MAE, and each sensitivity condition used one fit. Several shifts differ from H0 by more than that noise in both directions: H1, +2 s and +5 s lower test MAE by about 0.02 to 0.05, and −5 s raises it by about 0.05 to 0.07. These differences rest on only 3 test subjects, and validation does not consistently prefer any shift, so test and validation disagree. The data do not show that H0 is wrong and do not prove it right; the alignment stays "moderate confidence".

**Anomaly-track exclusion** (25 flagged tracks, raw GPS path / reference distance outside 0.8 to 1.25; 678 train, 562 validation, 47 test windows). The headline keeps these tracks. Test MAE (RF / XGBoost):

| Setting | Test MAE RF / XGBoost |
|---|---|
| All tracks (headline) | 1.4028 / 1.3989 |
| Exclude from evaluation only (n=2070) | 1.3822 / 1.3849 |
| Exclude from training and evaluation | 1.3787 / 1.3985 |

Only 47 test windows are in flagged tracks (one track, 12_12), so the test comparison is weak. Validation (562 flagged windows) shows a larger effect: MAE 2.0158 / 2.0318 for all tracks versus 1.944 / 1.961 with evaluation-only exclusion.

## 10. Modified-file inspection and recommendation (Verified inspection; approval needed)

When the inspection ran, 13 tracked files were modified in the working tree. Cause: Phase 2 scripts had been run with the system Python (scikit-learn 1.8.0, xgboost 3.2.0) instead of `.venv` (scikit-learn 1.9.1, xgboost 3.4.1, the versions recorded in the committed config). Seeds, split, features and hyperparameters are identical.

| File | Finding | Recommendation |
|---|---|---|
| `ml/models/random_forest.joblib`, `best_model.joblib` | same parameters, first tree identical, prediction difference about 1e-14 (serialization only) | restore |
| `ml/models/xgboost.json` | same parameters, 0 of 300 trees identical, predictions differ up to 1.71 steps; test MAE 1.4046 vs 1.3989 committed | restore |
| `results/metrics/phase2_test_predictions.csv` | same rows and targets; XGBoost column differs in every row | restore |
| `ml/models/evaluation_metrics.json`, `results/metrics/phase2_model_metrics.json`, `ml/models/training_config.json`, four `results/plots/phase2_*.png` | system-Python regenerations; XGBoost metrics shift by up to 0.0072 | restore (not regenerate) |
| `results/metrics/phase3_preservation_check.json` | Phase 3 hash tool output (committed 'before' snapshot, now with an 'after' section) | keep |
| `docs/Kinesis_Literature_Survey.pdf` | modified in the working tree before Phase 3, content not inspected | leave untouched, user decides |

Recommended action: restore the Phase 2 artefacts from HEAD, because the committed versions reproduce exactly when rerun in `.venv` and the committed reports quote the HEAD numbers. Regeneration is unnecessary. Keeping them mixes library versions with the committed documents.

**Status (Verified).** The restore was approved by the user in a chat message answering the modela-followups approval request (not in the original Phase 3 request; confirmed by the workflow orchestrator). The earlier Model A step's run log records that the first four files (`best_model.joblib`, `random_forest.joblib`, `xgboost.json`, `phase2_test_predictions.csv`) were restored from HEAD with `git restore`, as approved by the user (message after the modela-followups pause, source: workflow owner): "Restore only those four exact paths. Do not use git restore . or reset the entire working tree. Leave the other eight modified tracked files untouched. ... Yes, approve restoring only those four files from HEAD." This step restored nothing. The other seven Phase 2 artefacts (the three metrics/config files and four plots) are still in their system-Python state. The restore record in `phase3_modified_files_inspection.json` lists SHA-256 values for `xgboost.json` and the predictions CSV that do not match the HEAD values stored in the same file. I re-hashed all four files against `git show HEAD:` (`phase3_verification.json`): `best_model.joblib`, `random_forest.joblib` and `xgboost.json` are byte-identical to HEAD, and the predictions CSV equals HEAD once CRLF line endings (`core.autocrlf=true`) are normalised. The recorded hashes are therefore transcription errors, not evidence of a different file. The other modified tracked files stay uncommitted and unstaged, **pending your decision** (restore, keep or regenerate); none is restored.

## 11. Android compatibility summary (Verified for repository facts; Inferred for device behaviour)

Full text: `docs/android_sensor_compatibility.md`. Nothing has been run on a device.
- Android `TYPE_LINEAR_ACCELERATION` (m/s², gravity removed by the platform) is converted to g and `TYPE_GYROSCOPE` (rad/s) is used as is. Model B inputs are magnitudes, so device orientation does not matter (Inferred, from the feature design).
- Android sample timing is irregular, so a resampling step to 50 Hz and 128-sample windows is required (Inferred).
- The gravity-removal and prefilter differences in Section 3 mean an Android stream is a third domain. The cross-dataset drop in Section 7 is the evidence that this can matter.

## 12. Limitations (item labels inline)

1. **MotionSense has no timestamps** and its 50 Hz rate is assumed from documentation (Verified: no timestamp column).
2. **Placement:** MotionSense is a trouser pocket, UCI a waist mount (Verified from documentation). Hand-held, bag, and arm-swing placements are not represented (Inferred).
3. **Labels are physical activities, not spoofing labels.** The classifier has never seen a GPS-spoofing attack (Verified).
4. **STATIONARY merges sitting, standing and laying.** Its near-perfect F1 mostly reflects how easy low-motion windows are. A phone in the hand while the user stands still, or a phone in a moving vehicle, is not represented (Inferred).
5. **A phone resting on a stationary surface (the Phase 2 demo scenario) is represented by neither dataset.** (Verified: neither dataset's README or label set contains it; Inferred: how Model B would behave.) This is a gap. Model B outputs for it are unknown, and no claim is made. Honest evaluation later: record live Android logs of that scenario (sensor stream plus an operator-entered label with start and end times), score the already-frozen combined model on them without tuning on those logs, and report per-session results and the fraction predicted STATIONARY, with the logs kept out of training unless a separate split is held out.
6. **Few subjects:** 4 MotionSense and 9 UCI test subjects. Overlapping windows overstate sample size. Per-subject accuracy varies from 0.826 to 0.975.
7. Cross-dataset results show a large domain shift; the combined model is not validated on a third device (Verified: cross-dataset macro-F1 0.55 to 0.59; Inferred: the causes).
8. Model A follow-ups use the fixed Phase 2 split of 3 test subjects (1, 9, 12). Alignment remains unproven (Verified: sensitivity results do not confirm or refute H0).
9. Environment: Model B was run with system Python (scikit-learn 1.8.0, xgboost 3.2.0), and Model A follow-ups with `.venv` (1.9.1 / 3.4.1). `ml/requirements.txt` pins differ from both. No unit-test file exists; checks are asserts in the pipeline and in `ml/evaluation/phase3_verify.py` (Verified).

## 13. Verification summary (Verified)

Details are in `results/metrics/phase3_verification.json` and `results/metrics/phase3_final_run_log.md`.

| Check | Result |
|---|---|
| Model B pipeline rerun twice from `run_pipeline.py`: metrics, predictions, splits, model JSONs identical between runs and to the stored outputs | PASS |
| Zero subject leakage (train/val/test, both datasets) | PASS |
| No jog/stairs mapped to STATIONARY (label map) | PASS |
| No GPS or step features in Model B (11 magnitude features) | PASS |
| Raw dataset zips unchanged vs 'before' snapshot | PASS |
| Report numbers match the JSON files | PASS |
| docs PDF/PPTX/MD files (7) and `.agents/` (6 files) byte-identical to 'before' | PASS |
| Four modified Phase 2 files | **PASS as approved exception**: they differ from the 'before' snapshot by design (strict `identical: false`) because of the user-approved restore (Section 10); they equal git HEAD |
| Preservation compare overall | **PASS with approved exception**: only the four approved files differ; the 8 added Model A sensitivity window CSVs are Phase 3 outputs |

**Edit to a committed doc.** A 21-line Model B section was appended to `docs/model_documentation.md`. The file was clean in git before (not an uncommitted user doc), and it is not in the preservation hash set. The user should confirm they accept this edit. The seven other system-Python Phase 2 artefacts (Section 10) remain modified and unstaged, pending the user's decision.

Model B code uses system Python 3.14.3. Verification script: `ml/evaluation/phase3_verify.py`.

## 14. Proposed Phase 4 plan (for review; Inferred, nothing started, no Android)

Goal: a GPS-motion consistency / fusion engine that flags when GPS movement disagrees with motion evidence. Model B and Model A are inputs, not spoofing detectors.

1. **Define the consistency signals.** Model B class and probability per window. GPS speed and displacement per matching window. Model A step estimate versus GPS-implied step count. Candidate rules: GPS says moving at walking speed while Model B says STATIONARY; GPS speed above the plausible speed for the Model B class; step estimate far from GPS-implied steps.
2. **Calibrate thresholds on Dryad genuine recordings** (real walking, 18 subjects). Report the distribution of each residual per subject. Choose thresholds from quantiles on the train subjects, validate on held-out subjects, with no spoofed data used in calibration.
3. **Spoofing evaluation data.** Dryad has no spoofing labels. Synthetic perturbations (offsets, speed scaling, replayed tracks) can show sensitivity but are not real attacks; label them as simulated and report them separately.
4. **Known issue to resolve first:** Model B takes IMU windows and Dryad `motion.csv` has not been scale-checked against Model B's inputs (`activity_feature_scale_comparison.json` compares only the two public datasets). Check units and gravity handling before feeding Dryad IMU to Model B.
5. **Open decisions for you:** restore of the remaining modified Phase 2 files (Section 10); confirmation of the earlier restore; whether to collect the stationary-surface logs (Section 12, item 5) before or after fusion work; fusion rule style (hand-set thresholds vs a small learned model).
6. **Out of scope until approved:** Android implementation, merging to `main`, committing.
