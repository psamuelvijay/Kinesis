# Android M2 report: App A runs the Phase 2 GPS-only Random Forest

Branch: `android-m2` (based on `android-m0-m1`, M0/M1 head `c6c218e`)
Implementation commits: `f380f07` (export + golden files), `cdf6f74` (RF + pipeline in App A), `f3b3d10` (clock-aligned window index), `54c49c2` (Start fix). This report is committed on top of `54c49c2`.
Nothing is merged into `main`.

## Status

M2 is implemented for App A and the real Random Forest runs in it. Numerical parity with Python is proven by JVM unit tests (see Parity). Real-world accuracy is **not** validated. No walk with a counted ground truth was performed with the new estimator, so no accuracy claim is made.

## 1. What was implemented

- App A's placeholder stride estimator (`GpsStepEstimator`, 0.75 m stride) is removed. It is replaced by the Phase 2 pipeline:
  - `GpsWindowPipeline`: streaming port of `phase2_build_windows.py` cleaning, 5 s windowing and the 15 features.
  - `RandomForestModel`: plain Kotlin reader and traversal of the exported forest.
  - `GpsCountingEngine`: counts each closed window once, by window index.
- The last counted window index is persisted in DataStore (`PersistedCounting.lastCountedWindow`) and restored on service start. A cursor ahead of the clock (after a reboot) is cleared.
- Windows use a clock-aligned index (anchor 0 = floor(elapsedRealtimeMs / 5000)), so indices survive restarts (`f3b3d10`).
- GPS gap, no fix or no valid speed gives no prediction and 0 steps. Nothing is interpolated or invented. The UI state carries `gpsDataNote` ("GPS gap / insufficient data"). It is not rendered, so the UI is unchanged.
- App A stays GPS-only. `verifyNoPhysicalSensorDependency` passes. No accelerometer, gyroscope or STEP_COUNTER is used.

## 2. Model and export

- Selected model: Random Forest, taken from `best_model.joblib`: 300 trees, max_depth 8, min_samples_leaf 5, max_features 1.0. XGBoost was not used and nothing was substituted.
- Export script: `ml/export/export_rf_for_android.py`, run with `.venv/Scripts/python.exe`. It asserts those hyperparameters and that the model reproduces the stored `phase2_test_predictions.csv` RF predictions.
- Asset: `android/engine-gps/src/main/assets/gps_rf_model.bin` (1,553,644 bytes), little-endian. Header is `"KRF1"`, version 1, 300 trees, 15 features. Each node record is 29 bytes: feature (-2 for a leaf), float64 threshold, left, right, float64 leaf value, and a missing-goes-left flag.
- Prediction is the mean of the 300 leaf values, clamped to >= 0.
- Traversal: cast the feature to float32. NaN follows `missing_go_to_left`, which comes from `tree_.missing_go_to_left`. 12,793 split nodes route NaN right, so the flag is honoured. Otherwise go left when `x32 <= threshold`, compared as float64.
- Feature order: `n_fixes, n_speed_valid, displacement_m, path_m, speed_mean, speed_median, speed_max, speed_std, speed_delta, conf_mean, coverage_frac, covered_dur_s, derived_speed_mps, lag_speed_mean, lag_path_m`.
- Golden files in `android/engine-gps/src/test/resources/`:
  - `golden_model_vectors.json`: 300 held-out rows, 80 with NaN.
  - `golden_features.json`: raw fixes of 3 Dryad test tracks (`1_5`, `9_6`, `12_5`) and the expected windows from `windows_5s.csv`.

## 3. Parity results

Verified through automated JVM tests, not on a device.

| Check | Result |
|---|---|
| Model: Kotlin vs Python, 300 vectors (80 with NaN) | max abs diff 3.55e-15 (tolerance 1e-6) |
| Feature parity: raw-fix replay of 3 tracks, 154 windows | identical window set, max feature diff 1.29e-9 |
| Prediction on replayed windows | max abs diff 5.33e-15 |
| Asset format, checked earlier with a Python reader replicating the traversal | matches `best_model.joblib` to 1e-9 on 300 rows |

What parity does not cover:
- The teleport-drop path. The golden tracks have 0 teleport drops, so it is untested against Python.
- Only 2 confidence-dropped fixes exist in the golden data (one in `1_5`, one in `12_5`). Gap handling is covered by 3 long gaps in `1_5` and 1 in `9_6`.
- Golden windows are aligned to Dryad's `testStart`. Replay tests use `window_grid_start_ms`. On the phone the grid is clock-aligned, so window boundaries on a live walk differ from the golden grid.

## 4. Does Android preprocessing match Python?

The logic matches on the golden data. These differences remain:

1. **Confidence input.** Python drops fixes using Dryad's `confInterval`. Android uses `Location.accuracy` (NaN, <0 or >50 m dropped). These are **not guaranteed equivalent**. `confInterval` is the dataset's own confidence field, and `Location.accuracy` is the platform's 68% horizontal radius estimate. The feature `conf_mean` is affected. This is the largest unverified difference between the training and phone inputs.
2. **Speed validity.** Android treats `hasSpeed() == false`, NaN and negative speed as invalid, as Python treats raw `-1` and NaN. Whether phone GPS speed has the same distribution as Dryad's speed is untested.
3. **Window anchor.** Python anchors at the track start. The phone anchors on the clock (see above). Window content differs from the Python grid on a live walk.
4. **Fix timing.** The phone uses `elapsedRealtime`, and fix rate and irregularity depend on the device and `LocationManager` settings. Dryad's rate may differ.
5. **Teleport rule.** Ported as an iterative drop above 10 m/s on a buffer. Untested against Python data.

## 5. Start-button fix (`54c49c2`)

- Cause: Start only published a blocked state when permissions were missing. The request lived on the permission card, so a second Start tap was needed.
- Fix (shared `ui-shared`, both apps): `CountingViewModel.startWithPermissions` requests missing runtime permissions, remembers a pending start, and starts exactly once on the result. Double taps and an active or starting session are ignored. Denial leaves the existing permission card and settings path, and Start asks again. The bridge fires the listener after the notification prompt.
- Automated: `StartWithPermissionsTest`, 6 tests pass.
- Physical devices: on both phones the user reported counting after one Start tap. On both phones permissions were probably already granted from M1, so the permission-then-auto-start path was most likely **not** exercised on hardware.

## 6. Build and test results

Run with `GRADLE_USER_HOME=E:\gradle-user-home`, in `android/`.

- `gradlew test check assembleDebug lint`: passed in 25 s. 56 unit tests, 0 failures, 0 skipped. Lint passed for all 7 modules. `verifyNoPhysicalSensorDependency` and `verifyNoGpsDependency` pass.
- `connectedDebugAndroidTest` on Pixel_9 AVD (API 35, headless, `-gpu swiftshader_indirect`) passed.
  - The first full run failed once at `:app-fusion` with an ddmlib install exception, which was not a test failure.
  - A rerun of `:app-fusion:connectedDebugAndroidTest --rerun-tasks` passed (exit 0, no counts printed).
  - In the first run `:app-gps` ran 8 tests and `ui-shared` ran 4, all passing.

## 7. Results by evidence level

### Verified on physical device

OPPO CPH2213 (App A, Android 13, serial 9DXGAUMRYDOV69L7):
- Update install (`install -r`) succeeded, data kept.
- One foreground service record (`GpsCountingService`, `isForeground=true`), notification id 1001 on channel `counting_status`.
- Same pid (21846) before, during and after a screen-off of more than 30 s. Process and service survival only. The step count was not read before and after.
- 0 `FATAL EXCEPTION` or ANR entries in logcat and 0 in the crash buffer.
- `dumpsys sensorservice` showed 0 sensor connections for the app's pid.
- Counting after one Start tap: user-reported.

OnePlus CPH2401 (App B, Android 14, serial UOBACMH6US6DFABY):
- Update install succeeded, data kept.
- One `SensorFusionCountingService` record, foreground, type health (0x100), notification id 1001.
- `STEP_COUNTER` (type 0x13) connection held for pid 11655 at 200000 µs, so there is no regression in sensor registration.
- 0 crash or ANR entries.
- Screen-off survival, first attempt partial: the user was handling the phone, and the screen woke at about 40 s.
- Screen-off survival, re-run (adb-verified, phone left untouched): after `input keyevent 223` the phone stayed in `Dozing` at all six 5 s samples, which is at least 30 s. Pid 11655 was unchanged. The service was still foreground (id 1001, type 0x100 health). `SensorStepCounterFeed` was a single registration on STEP_COUNTER for pid 11655 with 0 dropped events. The crash buffer showed nothing for the app. The phone was stationary, so counting continuity during screen-off is still not read.
- Counting after one Start tap: user-reported.

### Verified emulator or automated

- All JVM tests above, including model and feature parity.
- Instrumented tests on Pixel_9 (API 35).
- Emulator smoke test of App A with synthetic fixes (not research data, so it says nothing about accuracy):
  - Moving for 60 s at 1.5 m/s: steps rose to 106, distance 84 m.
  - Stationary for 60 s at speed 0: steps went from 106 to 121 (15 phantom steps, distance +4 m). There was no baseline for the old estimator, so the reduction is not quantified.
  - A 15 s gap added 1 step and no distance.
  - Fixes without speed for 20 s caused no crash. The speed readout showed 0.0 m/s.
  - The sensor-step, activity and movement-verdict rows read "Not used by this method".

### Build or static only

- `verifyNoPhysicalSensorDependency` and `verifyNoGpsDependency`.
- Lint on all modules.
- Frontend unchanged: `gpsDataNote` is not rendered. There is no screenshot comparison.

### Not tested

- Accuracy of App A against a counted walk, and whether the 1.403 MAE carries over.
- App B step accuracy against a counted walk.
- Zero dropped sensor events (not measured this milestone).
- Reset Steps, Stop, permission denial and GPS-unavailable behavior on the physical phones. Permission-denied and screen-off scenarios were not run on the emulator.
- The permission-then-auto-start path on hardware (permissions were likely already granted).
- Step count continuity during screen-off for either app.
- No duplicate counting after reopening, on a device. A unit test covers the restart cursor (`RealPipelineRestartTest`).
- Emulator logcat crash check (the command failed, so "no crash" there rests on the UI staying responsive).
- Teleport drop against real data, and API levels 29-33.

## 8. Limitations

- **Research caveat.** The Phase 2 held-out test numbers are Random Forest MAE 1.403 steps per 5 s window with R² about 0.35, and XGBoost MAE 1.399. They come from held-out subjects in the Dryad dataset. They **do not transfer** to Android without validation. The input differences in section 4 (`Location.accuracy` vs `confInterval`, window grid, phone GPS characteristics) could change accuracy in either direction. The R² of 0.365 quoted in the task is not re-verified here.
- The model only predicts for windows with enough valid GPS data. Gaps, no fix and no valid speed count as 0 steps, so under-counting is expected in poor GPS conditions (indoors, urban canyons).
- The model is a regression on 5 s windows. Stationary phantom steps are reduced but not removed (15 in 60 s on the emulator with synthetic data).
- NaN is common in the data (1,396 of 2,117 test rows have at least one, mostly `lag_*`). It is handled natively by the flag.
- The first window after a start has NaN `lag_*` features, as in Python.
- Debug builds only. No release signing or minification was checked.

## 9. Build and install commands

From `e:\My_Projects\Major Project\android` in PowerShell:

```
$env:GRADLE_USER_HOME = "E:\gradle-user-home"
.\gradlew.bat test check assembleDebug lint
adb -s 9DXGAUMRYDOV69L7 install -r "GpsOnlyApp\build\outputs\apk\debug\app-gps-debug.apk"
adb -s UOBACMH6US6DFABY install -r "SensorFusionApp\build\outputs\apk\debug\app-fusion-debug.apk"
```

Instrumented tests (emulator or device attached): `.\gradlew.bat connectedDebugAndroidTest`.
Regenerate the model asset and golden files: `.venv/Scripts/python.exe ml/export/export_rf_for_android.py` from the repo root.

APKs:
- App A: `android\GpsOnlyApp\build\outputs\apk\debug\app-gps-debug.apk`
- App B: `android\SensorFusionApp\build\outputs\apk\debug\app-fusion-debug.apk`

## 10. Git

- Branch: `android-m2`. Pushed to `origin/android-m2` only. Not merged into `main`.
- Code head before this report: `54c49c2`. See the git log for this report's commit hash.
