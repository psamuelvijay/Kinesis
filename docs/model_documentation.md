# Model Documentation

## Model A: GPS-only step estimator (Phase 2)

All numbers below are copied from `results/metrics/phase2_model_metrics.json`, `phase2_splits.json`, `phase2_windows_summary.json`, `phase2_exclusions.json`, `phase2_cleaning_report.json`, `phase2_alignment_check.json`, `phase2_step_monotonicity_analysis.json` and `ml/models/training_config.json`. Details and tables are in `results/phase2_report.md`.

### Task
Predict the number of steps in a non-overlapping 5 s window from GPS data in that window only. No motion sensor data and no step data are inputs. Target: step-count increase in the window, from the cumulative step counter (`steps_target`).

### Data
Dryad walking dataset, 198 tracks, 18 subjects (subject 15 has no GPS; track `8_10` has no metadata row). 14,480 windows generated, 13,466 kept (mean target 8.625 steps, median 9, std 2.678, range 0 to 27).

### Methodology
- **Alignment.** `positions.ms` and `steps.ms` are treated as the same clock (hypothesis H0), no lag shift applied. Confidence is moderate, not proven (see Limitations).
- **Step counter.** Cumulative counter decreases occur in 40 of 198 tracks (135 events, 110 of size 1). All lie inside one `endDate` batch, so the counter is the running maximum over rows ordered by `ms`. Window target is the difference of that counter at the window ends. Individual differences are never clipped.
- **GPS cleaning.** Rows are sorted by `ms`. Dropped fixes: 44 exact duplicates, 169 with confInterval > 50 m, 73 implying > 10 m/s ("teleport"). Of 60,468 raw rows, 60,182 are kept. Invalid speeds (-1 or NaN) are not used as speed. Gaps between consecutive kept fixes > 10 s are long gaps, with no interpolation across them.
- **Window exclusions.** 688 long-gap overlap, 221 no fix, 105 no valid speed. No track was excluded entirely.
- **Features (15, GPS only).** n_fixes, n_speed_valid, displacement_m, path_m, speed_mean, speed_median, speed_max, speed_std, speed_delta, conf_mean, coverage_frac, covered_dur_s, derived_speed_mps, lag_speed_mean, lag_path_m. Absolute lat/lon, heading and altitude are not used.
- **Models.** Random Forest (300 trees; selected: max_depth 8, min_samples_leaf 5, max_features 1.0) and XGBoost (max_depth 5, learning_rate 0.03, 300 estimators, min_child_weight 1, subsample 0.8, colsample_bytree 0.8). Baselines: train-mean predictor (8.5882 steps) and linear distance (1.4385 steps/m x speed_mean x 5 s).
- **Selection.** Lowest validation window MAE, models fit on train subjects only. Random Forest was selected.

### Splits (subject-independent, seed 42)
| Set | Subjects | Tracks | Windows |
|---|---|---|---|
| Train | 0, 2, 4, 5, 6, 7, 8, 13, 14, 16, 17, 18 | 119 | 9,148 |
| Validation | 3, 10, 11 | 44 | 2,201 |
| Test | 1, 9, 12 | 35 | 2,117 |

Checks stored in `phase2_splits.json`: zero subject overlap, all subjects assigned, no track in two sets.

### Results (held-out test subjects, steps per 5 s window)
| Model | MAE | RMSE | R2 |
|---|---|---|---|
| Train-mean baseline | 1.791 | 2.595 | -0.027 |
| Linear distance baseline | 1.911 | 2.727 | -0.134 |
| Random Forest (selected) | 1.403 | 2.069 | 0.347 |
| XGBoost | 1.399 | 2.041 | 0.365 |

On the test set XGBoost is marginally better than Random Forest. The choice was made on validation (RF MAE 2.016 vs XGBoost 2.032), and the test set was not used to change it.

Test MAE by GPS speed range (Random Forest / XGBoost): <0.5 m/s 2.196 / 2.156 (n=81); 0.5-1.0 1.315 / 1.306 (n=398); 1.0-1.5 1.232 / 1.238 (n=1057); 1.5-2.0 1.658 / 1.642 (n=578); >2.0 2.719 / 3.243 (n=3, too few to interpret).

### Limitations
- The test set has 3 subjects. Per-subject test MAE for Random Forest ranges 1.090 (subject 1) to 1.729 (subject 9). R2 per subject ranges 0.068 to 0.404.
- Alignment of GPS and step clocks is adopted, not proven. A +/- 1 window shift sensitivity run changes test R2 for Random Forest to 0.268 (-1) and 0.309 (+1) versus 0.347.
- 25 tracks have GPS path length / distanceReference outside 0.8-1.25. They were kept and flagged. Excluding them from evaluation gives test RF MAE 1.382, R2 0.264 (n=2,070).
- Window-level R2 is modest because step cadence is nearly constant (target std 2.678) and speed explains little of the within-subject variance.
- Dryad is hand-held phone data; these tracks do not represent Android pocket or waist placement.

## Reproducibility
Seed 42; versions: Python 3.14.3, scikit-learn 1.9.1, xgboost 3.4.1, numpy 2.5.5, pandas 3.1.1. Model files are in `ml/models/`.
