# Phase 3 Model B run log (activity classifier)

Branch `phase3-activity-classifier`. Nothing committed. Model B classifies physical activity (WALKING / STATIONARY / OTHER). It was not trained or evaluated on GPS spoofing, and no result here says anything about spoofing detection.

## What was run
- `python ml/activity_classifier/run_pipeline.py` (single entry; loads raw zips read-only, windows, features, tuning, evaluation, plots, models). Run twice. SHA-256 of `activity_within_dataset_metrics.json`, `activity_generalisation_metrics.json`, `activity_test_predictions.csv`, `activity_splits.json`, `activity_preparation_report.json` were identical between the two runs (reproducible).
- `python ml/evaluation/preservation_hash.py compare` -> IDENTICAL (preserved files unchanged by this step; the pre-existing Phase 2 modifications were not touched).
- Not run: Dryad `motion.csv` scale comparison (optional; not used). Feature-scale comparison between the two datasets only is in `results/metrics/activity_feature_scale_comparison.json`.
- Versions: Python 3.14.3, numpy 2.4.3, pandas 3.0.1, scipy 1.17.1, scikit-learn 1.8.0, xgboost 3.2.0 (also in `ml/models/activity_training_config.json`). `ml/requirements.txt` is unmodified and already lists all needed packages (its pinned versions differ from the installed ones); it was left unchanged and no `requirements_phase3.txt` was written.
- Seed 42 everywhere. No unit-test file was written; label-mapping and subject-overlap checks are `assert`s in the pipeline.

## Inputs and verification against dataset docs
| Item | MotionSense | UCI HAR |
|---|---|---|
| Device / placement | iPhone 6s, front trouser pocket (from dataset documentation; not re-verifiable from the files) | Samsung Galaxy S II, waist (UCI README, verified) |
| Acceleration used | `A_DeviceMotion` `userAcceleration.x/y/z`, g, gravity removed by Core Motion sensor fusion (documented; algorithm not inspectable) | `body_acc_x/y/z`, g. README: gravity separated with a Butterworth low-pass at 0.3 Hz (verified in README and features_info.txt) |
| Gyro used | `rotationRate.x/y/z`, rad/s | `body_gyro_x/y/z`, rad/s (README, verified). features_info.txt: signals were median-filtered and 3rd-order Butterworth 20 Hz low-passed (verified in features_info.txt, not README.txt) |
| Prefilter | none known | median + 3rd-order Butterworth 20 Hz; MotionSense files have no such documented filter, UNVERIFIED whether Core Motion smooths |
| Axes | iPhone device frame (Core Motion) | Samsung device frame; axis sign conventions between the two not verified. Features are magnitudes, so axis conventions and orientation do not enter the model |
| Sampling | 50 Hz documented; no timestamp column, assumed (not measurable) | 50 Hz per README; no timestamps |
| Windows | 128 samples, stride 64, by sample count within a recording, `A_DeviceMotion` only, trailing partial dropped | rows of Inertial Signals used directly (128 samples). README says 50% overlap; I checked 9,899 consecutive same-subject/same-activity row pairs and 9,442 match exactly (second half of row i = first half of row i+1); the rest are at group boundaries or activity transitions |
Excluded as inputs: total_acc, gravity.*, attitude.*, B_/C_ streams, the 561 features, GPS, steps.

MotionSense windowing: 360 recordings, 1,412,865 rows; 1,401,536 rows in windows; 11,329 trailing rows dropped (reconciles); 21,539 windows. UCI: 10,299 windows as provided. No resampling or interpolation.

## Features (11, identical code on both datasets)
Acceleration-magnitude mean, std, RMS, variance, energy (sum of squares); gyro-magnitude mean and variance; peak count (`find_peaks`, prominence 0.1 g, distance 10 samples); dominant frequency, spectral energy, normalised spectral entropy from rFFT at 50 Hz of the mean-removed acceleration magnitude. No per-axis features.

## Splits (zero subject overlap asserted)
- MotionSense, seed 42 permutation, 16/4/4: train {see `activity_splits.json`}; subject lists are stored there. Test subjects: 7, 11, 15, 20.
- UCI: provided 21 train / 9 test; 5 validation subjects carved from the 21 train subjects (seed 42). Test subjects: 2, 4, 9, 10, 12, 13, 18, 20, 24.
- Model selection and hyperparameters on validation macro-F1 only. Final models are fit on train subjects only (validation subjects not added back). Each model scored once on test.

## Class balance after mapping (windows: WALKING / STATIONARY / OTHER)
- MotionSense train 3505/6556/4178; val 894/1703/1116; test 876/1678/1033.
- UCI train 888/3122/1541; val 338/945/518; test 496/1560/891.
Laying exists only in UCI. Overlapping windows mean window counts overstate independent samples.

## Headline: within-dataset subject-independent, test set
| Dataset | Model | Accuracy | Macro-F1 | Weighted-F1 |
|---|---|---|---|---|
| MotionSense (3,587 windows, 4 subjects) | majority | 0.4678 | 0.2125 | 0.2982 |
| | logistic regression (baseline) | 0.8798 | 0.8488 | 0.8799 |
| | Random Forest | 0.9328 | 0.9139 | 0.9320 |
| | **XGBoost (selected on validation)** | 0.9378 | 0.9207 | 0.9373 |
| UCI HAR (2,947 windows, 9 subjects) | majority | 0.5294 | 0.2308 | 0.3664 |
| | logistic regression (baseline) | 0.8802 | 0.8305 | 0.8826 |
| | Random Forest | 0.9135 | 0.8719 | 0.9148 |
| | **XGBoost (selected on validation)** | 0.9206 | 0.8835 | 0.9220 |

XGBoost per-class F1 (WALKING / STATIONARY / OTHER): MotionSense 0.865 / 1.000 / 0.898; UCI 0.790 / 0.998 / 0.862. Confusion counts (rows true, cols predicted W/S/O): MotionSense [[712,1,163],[0,1678,0],[59,0,974]]; UCI [[435,0,61],[3,1556,1],[167,2,722]]. WALKING and OTHER confuse with each other; STATIONARY is almost perfectly separated. Per-subject accuracy: MotionSense 0.906 to 0.975; UCI 0.826 to 0.974 (subjects 9 and 10 lowest). Differences between RF and XGBoost are small relative to this subject variation on 4 and 9 test subjects.

Diagnostic (selected XGBoost, test): jog/stairs predicted STATIONARY: MotionSense 0 of 1,033; UCI 2 of 891 (0.22%). Stationary activities predicted WALKING: MotionSense 0 of 1,678; UCI 3 of 1,560 (0.19%). UCI upstairs predicted WALKING 132 of 471; MotionSense upstairs predicted WALKING 35 of 405.

Class weighting effect (validation macro-F1, weighted vs unweighted, tuned params): MotionSense XGB 0.8380 vs 0.8427, RF 0.8025 vs 0.8010, LR 0.8194 vs 0.8104; UCI XGB 0.8506 vs 0.8467, RF 0.8474 vs 0.8480, LR 0.8004 vs 0.8216. The effect is within about +-0.02 and not consistent in sign.

Supplementary (labelled) grouped CV with the selected model: MotionSense leave-one-subject-out over 24 subjects accuracy 0.9202, macro-F1 0.9005; UCI 5-fold grouped CV over the 21 train subjects accuracy 0.9127, macro-F1 0.8598.

## Generalisation experiment (not headline), macro-F1
| Experiment | Accuracy | Macro-F1 |
|---|---|---|
| MotionSense train -> UCI test | 0.8056 | 0.5805 |
| MotionSense train -> all UCI | 0.8122 | 0.5922 |
| UCI train -> MotionSense test | 0.7254 | 0.5539 |
| UCI train -> all MotionSense | 0.7244 | 0.5579 |
| Combined (XGBoost, depth 3, lr 0.05, 300 trees) -> MotionSense test | 0.9465 | 0.9319 |
| Combined -> UCI test | 0.9213 | 0.8832 |

Cross-dataset results are far below within-dataset results (macro-F1 about 0.55 to 0.59 vs 0.88 to 0.92). MotionSense-trained model predicts 47 of 891 UCI jog/stairs windows (5.3%) as STATIONARY; UCI-trained model predicts 14 of 1,678 MotionSense stationary windows (0.8%) as WALKING. Likely reasons (not isolated by experiment): different device, placement (pocket vs waist), gravity-removal method, prefiltering, and UCI's absence of jogging. The combined model matches within-dataset performance on each dataset's test subjects, because it saw both domains; this says nothing about a third device. Combined model is the candidate deployed model, but it has never been evaluated on Android data.

## Limitations
- 4 and 9 test subjects; all windows overlap 50%. MotionSense 50 Hz is documented, not measured.
- STATIONARY merges sit/stand/lay; STATIONARY F1 near 1.0 largely reflects the easy separation of low-motion windows.
- No Android data, no spoofing labels.

## Files
Models `ml/models/activity_{motionsense,uci,combined}_xgboost.{joblib,json}`; `ml/models/activity_feature_list.json`, `activity_training_config.json`. Metrics `results/metrics/activity_*.json`, predictions `activity_test_predictions.csv`. Confusion matrices `results/confusion_matrices/`. Plots `results/plots/activity_*.png`. Code `ml/preprocessing/activity_data.py`, `ml/feature_extraction/activity_features.py`, `ml/evaluation/activity_metrics.py`, `ml/activity_classifier/run_pipeline.py`.
