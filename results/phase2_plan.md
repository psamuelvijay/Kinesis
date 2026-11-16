# Phase 2 Plan: Dryad Preparation and GPS-only Step Estimator (Model A)

Branch: `phase2-gps-step-estimator`. Phase 3 is not started. No metric is reported unless computed from the actual data.

## What Phase 2 implements
1. **Alignment verification.** For each of the 198 Model A tracks, compare the `positions.csv` and `steps.csv` time axes (`ms`, first/last stamps, relation to `events.csv` signalStart/testStart/testEnd and steps `endDate`). Phase 1 inferred that both use the signalStart axis; Phase 2 tests this per track and reports tracks where the offset is inconsistent. A cross-check compares the GPS path length and total steps against `distanceReference` and `totSteps`. Windows are built only if alignment is verified; otherwise the discrepancy is reported and the affected tracks are excluded or the work stops with a warning.
2. **Step-counter decrease investigation.** In 40 of 198 tracks (subjects 3, 10, 11, 12, 14, 18) the cumulative `steps` value decreases by up to 4 between rows. Examine where decreases occur (duplicate `ms`, row ordering, `startDate`/`endDate` changes, relation to sorting by `ms`), their size, and the effect on window totals. The handling rule is chosen from the findings and documented. Negative differences are not clipped blindly.
3. **GPS cleaning.** Sort positions by `ms` (non-monotonic in 16 tracks). Drop rows with `speed` < 0 (invalid, -1) and non-finite values. Mark long gaps (threshold chosen from the measured gap distribution and documented). No interpolation across long gaps. Windows that overlap a long gap or have too few valid GPS rows are dropped, and the counts are recorded.
4. **5 s windowing.** Non-overlapping 5 s windows on the verified common time axis. The target is the step-count increase within the window, derived from the cumulative counter. Features come only from GPS in the window: speed statistics (mean, std, min, max, median), valid-row count, coordinate-derived distance and speed, heading change, altitude change, confInterval statistics. No motion data and no step data as input.
5. **Subject-independent splits.** Split by subject ID into train, validation and test with a fixed seed, so no subject appears in more than one set. Subject 15 has no GPS and is absent. Split membership and window counts per set are saved.
6. **Models and baselines.** RandomForest and XGBoost regressors on the GPS-only features, tuned on the validation set only. Baselines: train-mean predictor and a linear model of steps against GPS speed x window length (cadence-from-speed). Model A is not tested until the configuration is fixed.
7. **Evaluation.** On the held-out test subjects: MAE, RMSE and R² for steps per 5 s window, for both models and the baselines. Performance is also reported by walking-speed range (bins from GPS speed, bin edges and per-bin sample counts stated). Also report per-subject results to show variance, and the full-track step total error where meaningful.
8. **Docs.** Dataset preparation report (inputs, exclusions with counts and reasons, alignment and step-decrease findings, cleaning rules), model results, evaluation methodology, limitations and a proposed Phase 3 plan. Update `docs/dataset_documentation.md` and the inventory only with facts found in Phase 2. Existing unrelated files under `docs/` are not touched.
9. **Verification.** Re-run scripts from raw data to confirm the outputs reproduce. Check that no subject appears in two splits, that window counts reconcile with the exclusion log, that all reported numbers come from the saved metric files, and that `datasets/dryad/raw/Data.zip` and the unrelated `docs/` files keep the SHA256 hashes recorded in `.agents/tasks/phase2/hashes_before.json`.

## Dataset used
Dryad Walking Activity Dataset (DOI 10.5061/dryad.n2z34tn5q), extracted copy in `datasets/dryad/extracted/`. Model A input: 198 tracks with valid GPS and steps, 18 subjects. Excluded before Phase 2: `15_0`-`15_4` (no GNSS) and `8_10` (no metadata row). Raw files stay unmodified. MotionSense and UCI HAR are not used in Phase 2.

## Expected output
- `ml/preprocessing/` scripts for alignment check, step-decrease analysis, cleaning and windowing.
- `ml/` training and evaluation scripts for Model A.
- Processed window table (outside `raw/`), split files, exclusion log.
- `results/metrics/*.json` with alignment, step-decrease, cleaning, and model metrics.
- Trained model files and figures if produced.
- Phase 2 report with the sections listed in item 8.

## Success evaluation
- Alignment is stated as verified only with per-track evidence from the data. If it fails, the report says so.
- The step-decrease handling is justified by the investigation, and every exclusion has a count and reason.
- No synthetic data or interpolation across long gaps.
- Splits are subject-disjoint, checked by a test.
- Random Forest, XGBoost and both baselines are scored with MAE, RMSE, R² and per-speed-range tables, all traceable to metric files.
- Scripts reproduce the outputs.
- Unrelated uncommitted files in `docs/` are unchanged, never staged, and verified by hash.
- Work stops after Phase 2 for review.
