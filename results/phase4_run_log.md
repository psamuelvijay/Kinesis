# Phase 4 run log

## Setup
Branch: phase4-fusion-engine from phase3-activity-classifier cb1de1a

### git status before restore
```n M docs/Kinesis_Literature_Survey.pdf
 M ml/models/evaluation_metrics.json
 M ml/models/training_config.json
 M results/metrics/phase2_model_metrics.json
 M results/plots/phase2_feature_importance.png
 M results/plots/phase2_mae_by_speed_bin_test.png
 M results/plots/phase2_pred_vs_actual_test.png
 M results/plots/phase2_residuals_test.png
?? .agents/
?? datasets/dryad/processed/phase3_modelA_sensitivity/
?? "docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md"
?? docs/Kinesis_Guide_Review.pptx
?? docs/Kinesis_Literature_Review.pptx
?? docs/Kinesis_Progress_Review_2.pptx
?? docs/Kinesis_Progress_Review_2_Final.pptx
?? docs/Review.pptx
?? results/metrics/phase3_gates/
?? results/metrics/phase4_preservation_check.json
```

### git status after restore (7 approved paths only)
```n M docs/Kinesis_Literature_Survey.pdf
?? .agents/
?? datasets/dryad/processed/phase3_modelA_sensitivity/
?? "docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md"
?? docs/Kinesis_Guide_Review.pptx
?? docs/Kinesis_Literature_Review.pptx
?? docs/Kinesis_Progress_Review_2.pptx
?? docs/Kinesis_Progress_Review_2_Final.pptx
?? docs/Review.pptx
?? results/metrics/phase3_gates/
?? results/metrics/phase4_preservation_check.json
```

## Work item 0: outdated commit statement
results/phase3_report.md line 3 said 'Nothing is committed'. Phase 3 is committed as cb1de1a on phase3-activity-classifier. Minimal edit: replaced that sentence with the commit reference and a note that the Phase 2 artefacts/docs described as uncommitted were uncommitted at the time of writing. No other text in the report changed. Not committed yet.

## Plan written
results/phase4_plan.md written before any Phase 4 code. Not committed.

## Work item 1: Dryad IMU compatibility check (Model B input gate)
Code: ml/fusion_engine/dryad_imu_compat.py. Outputs: results/metrics/phase4_dryad_imu_check.json, results/metrics/phase4_dryad_modelB_windows.csv (40,916 window rows). Two runs gave identical SHA-256 for both files. Model B (activity_combined_xgboost) only loaded and used for predict_proba; not modified. Not committed.
Selection: metadata hasMotion and hasGNSS, non-empty motion/events: 146 tracks, 14 subjects (Verified). All tracks are hand held (Verified).
### Units (Verified from data unless marked)
- Dryad record gives no unit text for motion.csv. Column names match W3C DeviceMotionEvent (m/s^2, rotationRate deg/s, interval ms): Inferred.
- accelWithG magnitude median 10.24 m/s^2 over walk samples; |accelWithG - accel| median 9.81 (p10 9.58, p90 10.20); gravity direction step RMS per track median 0.024. So accel* is gravity removed, accelWithG* includes gravity, both m/s^2. Convert /9.80665 to g.
- Gyro: raw median magnitude 53.0 (walk samples); deg/s inferred. Ratio raw/MotionSense walking median = 28.1, after deg->rad = 0.49 (vs UCI walking 1.5). Per-device track medians span 25.6 to 188.9 (7.4x), no cluster at 57x, so no sign of mixed rad/s and deg/s across devices. Leaving gyro unconverted gives 0% WALKING (96% OTHER), consistent with deg/s. Conclusion: deg/s, converted by pi/180. Unit label rests on data scale plus API convention, not on Dryad text.
- iOS 25 tracks, Android 121. Values quantised to 0.1.
### Timestamps
- Median dt 17 ms in every track; mean rate per track median 59.8 Hz, p05 55.8, min 6.3 (track 8_4), 8_6 22.6, 8_2 31.2 Hz.
- 4 tracks have non-monotonic ms, 31 have duplicate ms. Handling: stable sort, drop duplicate ms.
- 95 tracks lost at least one window to gaps.
### Pipeline (decided)
m/s^2 -> g; deg/s -> rad/s; restrict to events testStart..testEnd; 50 Hz grid; linear interpolation only between observed samples at most 100 ms apart; 128-sample windows, stride 64; windows with an invalid grid point dropped; windows with <64 observed samples dropped (none hit). Of 42,428 possible windows: 1,512 dropped for gaps, 0 for under-coverage, 40,916 kept. 50,836 of 2,729,388 grid points were invalid. Risk (Inferred): 60 Hz to 50 Hz linear interpolation acts as a mild low-pass filter, no anti-alias filter; effect on features not measured.
### Feature scale vs training (median Dryad / median training WALKING)
acc_mag_mean 0.33 g: 0.48x MotionSense, 1.16x UCI. gyro_mag_mean 1.04 rad/s: 0.48x MotionSense, 1.55x UCI. acc_mag_var 0.15x / 1.64x. dominant freq 1.95 Hz: 1.25x / 1.0x. Dryad (hand held) lies between the pocket (MotionSense) and waist (UCI) training scales. No systematic offset beyond that.
### Frozen Model B on genuine Dryad walking (all windows genuine walking)
Overall: WALKING 51.2%, OTHER 40.5%, STATIONARY 8.2%.
By subject WALKING/STATIONARY/OTHER: 3: .91/.00/.09; 4: .56/.00/.44; 5: .54/.26/.20; 6: .48/.00/.52; 7: .40/.00/.60; 8: .63/.01/.37; 10: .61/.18/.21; 11: .52/.10/.38; 12: .47/.11/.42; 13: .54/.09/.37; 14: .39/.02/.59; 16: .75/.06/.19; 17: .48/.25/.28; 18: .53/.24/.23.
By OS: Android .51/.07/.42 (35,048 windows); iOS .52/.17/.31 (5,868). By speed bin (m/s): <1.0 .41/.26/.33; 1.0-1.3 .54/.07/.40; 1.3-1.6 .54/.02/.45; >=1.6 .52/.00/.48. App: Timed Walk .55/.10/.35; Malisa .39/.02/.59 (subject 14 only).
44% of tracks and 36% of subjects have WALKING share < 0.5.
### Finding (flagged, not hidden)
Unit and gravity compatibility holds, but Model B recognises only about half of genuine hand-held walking as WALKING and labels 8.2% STATIONARY (26% in slow walks below 1.0 m/s; 25% for subject 5). This is a domain gap (hand held vs pocket/waist training, Phase 3 cross-dataset macro-F1 0.55-0.59), not an unit offset. No rescaling applied. Consequences for fusion (proposal): rule R1 on P(STATIONARY) must have its threshold set on these Dryad genuine-walking windows (false-STATIONARY is the false-flag source); WALKING share must not be used as a positive walking test; expect elevated false flags for slow walkers; live Android hand-held and table recordings are needed to calibrate on-device. Model B stays frozen.
Not tested: Model B on Dryad stationary data (Dryad has none), so STATIONARY recall on Dryad is unknown.

## Work items 2 and 3: fusion engine and Dryad evaluation (not committed)
Code: ml/fusion_engine/{engine,make_split,build_signals,calibrate,evaluate,make_golden_vectors}.py, test_fusion_engine.py (52 tests pass). Spec: docs/fusion_engine_spec.md (new). The engine is pure Python and deterministic. It is a consistency detector, not a spoofing classifier. Model B is an activity classifier not trained on spoofing. Model A is comparison-only.
Order followed: split.json -> signals (no thresholds) -> calibrate on calibration subjects -> thresholds.json + SHA-256 (results/metrics/phase4_thresholds_hash.json) -> evaluate held-out. A full re-run of all five scripts gave identical SHA-256 for 8 output files.
Split: calibration = Phase 2 train subjects with motion (4,5,6,7,8,13,14,16,17,18; 94 tracks). Held-out = Phase 2 test + validation subjects with motion (3,10,11,12; 52 tracks). Test subjects 1 and 9 have no motion. Validation subjects went to held-out because only subject 12 was left otherwise; they never fed a threshold. Zero overlap asserted.
Thresholds (calibration quantiles): ACC_MAX_M 16.38 (p99), COV_MIN 0.792 (p10), V_MOVE 0.321 m/s (p05), V_MOVE_DISP 0.545 m/s (p05), V_WALK_MAX 1.846 m/s (p99), STEP_MIN 2 (p05), P_STAT_SUSPICIOUS 0.99987 (p99), N=2. Provisional (no live stationary calibration data): STEP_ZERO_MAX=1, P_STAT_STATIONARY=0.5, the GPS-still boundary.
Stationary search: Dryad events.csv has only signalStart/testStart/testEnd (no standing periods). 300 fixes before testStart-1 s exist in calibration tracks, but they are GNSS warm-up with no stationarity label, so not used. datasets/live_recordings/* are empty. No stationary jitter was measured or invented.
Persistence N (calibration, in-sample): N=1: 0.18 false SUSPICIOUS episodes/h, N=2: 0.09, N>=3: 0. N=2 chosen (smallest N>=2 under 1/h).
Held-out (genuine walking, 2,950 windows, raw states): GENUINE_WALKING 32.6%, UNCERTAIN 24.0%, STATIONARY 2.2%, SUSPICIOUS 0.17% (5 windows), INSUFFICIENT_DATA 41.0%. After persistence (N=2): 0 SUSPICIOUS windows, 0 episodes. Per subject SUSPICIOUS raw windows: 3:0, 10:0, 11:2, 12:3. Time to first reported GENUINE_WALKING: median 50 s, p90 113 s, 17 of 52 tracks never.
Findings: iOS held-out tracks are 92% INSUFFICIENT_DATA (sparse GPS fixes, low coverage); Android 16%. Model B OTHER makes 473 windows UNCERTAIN. No spoofing detection rate was computed. Results: results/metrics/phase4_dryad_eval.json.

## Work item 4: live recording protocol and live evaluation tooling (not committed)
Files: docs/recording_protocol.md (new), ml/fusion_engine/{ingest_live_logs,evaluate_live,calibrate_live}.py, ml/fusion_engine/tests/{test_live_schema.py,fixtures/}, .gitignore (3 lines appended), datasets/live_recordings/{calibration,evaluation}/.gitkeep. The user's Logger Spec v0.1 was read, not edited.
Real live recordings found: NONE. datasets/live_recordings/calibration/ and evaluation/ were empty. No log was fabricated. The only test input is ml/fusion_engine/tests/fixtures/FORMAT_TEST_ONLY_session (hand-specified placeholder values, flagged 'format test only, not data, not used for any metric'); the parser refuses it for the calibration and evaluation splits.
Live calibration: PENDING USER DATA. Stationary thresholds (V_MOVE_MPS, V_MOVE_DISP_MPS, STEP_ZERO_MAX, P_STAT_STATIONARY) remain provisional (no live stationary calibration data). calibrate_live.py wrote only results/metrics/phase4_live_calibration.json (status PENDING). thresholds.json and its hash are untouched.
Live evaluation: PENDING USER DATA. evaluate_live.py wrote only a PENDING status in results/metrics/phase4_live_eval.json. No detection rate, latency, false-positive rate or accepted-distance figure exists yet.
Split rule (docs/recording_protocol.md section 3, fixed before data): calibration = S2+S3 real-GPS stationary sessions only; S1, S4-S7 are evaluation only; different sessions and days; calibrate_live.py never lists the evaluation folder; evaluate_live.py verifies engine.py, split.json and thresholds.json hashes and only uses thresholds_live.json when --use-live-calibration is given.
Pipeline: linear acceleration m/s^2 -> g, gyro rad/s, 50 Hz grid from observed samples only (gap > 100 ms never bridged), 128-sample windows stride 64, frozen Model B; GPS cleaned with the Phase 2 rules.
Checks run: python -m pytest ml/fusion_engine -q -> 56 passed (52 existing + 4 new schema tests). Plumbing smoke test of evaluate_live.main on the fixture with outputs sent to a temp dir: ran; its numbers are not results.
Untested on real data: the S5 branch of evaluate_live.py and the calibrated branch of calibrate_live.py (no real recordings to run them on). Limitation: mock apps that give no accuracy field lose all fixes to the accuracy filter and give INSUFFICIENT_DATA; this is reported with cleaning counts, not patched.

## Work item 6: verification (not committed; no review1.json existed, so this is the first verification pass)
Ran once each, twice in sequence (dryad_imu_compat, make_split, build_signals, calibrate, evaluate), then `python -m pytest ml/fusion_engine -q` (56 passed). All 10 script runs exited 0.
1. Reproducibility: PASS. SHA-256 of 9 outputs (thresholds.json, split.json, phase4_thresholds_hash.json, fusion_signals.csv, calibration.json, dryad_eval.json, dryad_heldout_windows.csv, dryad_imu_check.json, dryad_modelB_windows.csv) identical before the reruns, after run 1 and after run 2.
2. No ML training in ml/fusion_engine: PASS. Grep for .fit(, partial_fit, .train(, xgb.train, fit_transform, GridSearch, Pipeline( found no code hits. Thresholds are quantiles in calibrate.py.
3. Thresholds frozen before evaluation, unchanged after: PASS. evaluate.py asserts thresholds.json, split.json and engine.py hashes against phase4_thresholds_hash.json (written by calibrate.py) before evaluating; hash 5184189b...b639725 unchanged after the reruns and equal to the value in the report.
4. Calibration/held-out disjoint: PASS. Calibration subjects 4,5,6,7,8,13,14,16,17,18; held-out 3,10,11,12; intersection empty. Every calibrated threshold's provenance.subjects equals the calibration list.
5. No synthetic/simulated attack code or data: PASS. Grep for perturb, replay, noise, inject, synthes, random found only a disclaimer string, a docstring saying the ingest script never perturbs data, and a test asserting the code uses no randomness. datasets/live_recordings has only .gitkeep files. Flag: ml/fusion_engine/tests/fixtures/FORMAT_TEST_ONLY_session is a hand-specified placeholder for format tests (not an attack, refused by the parser for calibration/evaluation, used for no metric).
6. Model A and Model B files unchanged: PASS. All 15 files in frozen_models_before (Model A best_model.joblib, random_forest.joblib, xgboost.json; Model B activity_*) match their hashes.
7. User docs preserved: PASS. docs/Kinesis_Literature_Survey.pdf is still modified (git ' M') with its hash unchanged; the 6 untracked docs and 6 .agents/ files are byte-identical. After-hashes and comparison are in results/metrics/phase4_preservation_check.json (frozen_models_after, docs_after, agents_after, verification_work_item_6).
8. Report vs JSON: PASS. Checked report sections 4, 6 and 7 against phase4_dryad_imu_check output, phase4_calibration.json, thresholds.json and phase4_dryad_eval.json (state counts and shares, anomaly-excluded 46 tracks/2,409 windows/4 raw, per-OS, per-speed, reasons, time-to-decision, Model A MAE, persistence table). No discrepancy found; no report or code edits were needed.
Notes: phase4_report.md still says it is uncommitted; update when the branch is committed. A first attempt to run this verification overlapped with a second launch (PowerShell alias clash on 'H'); the clean results above come from a single isolated script run. Live evaluation and stationary-on-table remain PENDING USER DATA.

## Work item 6: verification, pass 2 (review1.json verdict CHANGES_REQUESTED, findings fixed)
Fixes: (1) docs/model_documentation.md: removed stray CR in 'results/phase4_report.md' path. (2) That file is a tracked doc that the Phase 4 work edited (appended '## Fusion Engine (Phase 4)' section) and had not been logged; now logged here, in phase4_report.md and in phase4_preservation_check.json (verification_review1_pass.model_documentation_md). The line-ending-only change on the Reproducibility line was reverted by rebuilding the file from HEAD bytes (LF) plus the appended section; git diff now shows only the 3 added lines. The edit stays uncommitted pending the user's decision. (3) phase4_report.md status lines updated for the commit.
Re-ran: 5 pipeline scripts twice (all 10 exits 0), python -m pytest ml/fusion_engine -q (56 passed).
1. Reproducibility: PASS. 9 output files hash-identical before, after run 1, after run 2.
2. No ML training: PASS. No fit/partial_fit/train/fit_transform/GridSearch hits in ml/fusion_engine/*.py.
3. Thresholds frozen: PASS. thresholds.json SHA-256 5184189b...b639725 equals phase4_thresholds_hash.json; evaluate.py asserts it before evaluating.
4. Calibration/held-out disjoint: PASS (4,5,6,7,8,13,14,16,17,18 vs 3,10,11,12; split.json unchanged by reruns).
5. No synthetic attacks: PASS. Only disclaimer strings match perturb/replay/synthes/inject; datasets/live_recordings has only .gitkeep.
6. Model A and B unchanged: PASS (15 of 15 hashes match frozen_models_before).
7. User docs preserved: PASS (PDF still ' M', 7 doc hashes equal, 6 .agents files equal).
8. Report vs JSON: PASS. Outputs are byte-identical to those the report was checked against; no numeric edits.
