# Android sensor compatibility for Model B (activity classifier)

Scope: how Android `TYPE_LINEAR_ACCELERATION` and `TYPE_GYROSCOPE` can supply inputs to the Model B classifier (WALKING / STATIONARY / OTHER). No Android code exists yet and nothing in this document has been run on a device.

Labels used in each section: **Verified** means checked against repository code or result files. **Inferred** means reasoned from Android/platform knowledge or from the repository, but not tested.

Sources in the repository: `ml/feature_extraction/activity_features.py`, `ml/models/activity_training_config.json`, `results/metrics/activity_preparation_report.json`, `activity_within_dataset_metrics.json`, `activity_generalisation_metrics.json`, `activity_feature_scale_comparison.json`, `phase3_gates/modelb_review.md`.

## 1. What Model B was trained on

**Status: Verified (repository facts).**

- Input per window: 128 samples x 6 channels = linear acceleration x/y/z in **g**, gyroscope x/y/z in **rad/s**, at **50 Hz** (2.56 s), 50% overlap (stride 64 for MotionSense; UCI windows used as provided).
- MotionSense columns: `userAcceleration.x/y/z`, `rotationRate.x/y/z` from `A_DeviceMotion`. UCI HAR columns: `body_acc_x/y/z`, `body_gyro_x/y/z`.
- Labels: wlk/WALKING -> WALKING; sit, std, LAYING -> STATIONARY; jog, stairs up/down -> OTHER. Jogging and stairs are not STATIONARY.
- Scope: an activity classifier. It was not trained or evaluated on GPS spoofing. Spoofing detection comes from later fusion logic.
- Features (11, in this order, from `FEATURE_NAMES`; `ml/models/activity_feature_list.json` holds the same list):

| # | Feature | Definition |
|---|---|---|
| 1 | `acc_mag_mean` | mean of per-sample acceleration magnitude (g) |
| 2 | `acc_mag_std` | population std (ddof=0) of magnitude |
| 3 | `acc_mag_rms` | sqrt(mean(mag^2)) |
| 4 | `acc_mag_var` | population variance of magnitude |
| 5 | `acc_mag_energy` | sum(mag^2) over 128 samples |
| 6 | `gyro_mag_mean` | mean of gyro magnitude (rad/s) |
| 7 | `gyro_mag_var` | population variance of gyro magnitude |
| 8 | `acc_peak_count` | `scipy.signal.find_peaks` on acc magnitude, prominence >= 0.1 g, distance >= 10 samples |
| 9 | `acc_dominant_freq_hz` | argmax of rFFT power of mean-removed magnitude, DC bin excluded |
| 10 | `acc_spectral_energy` | sum of non-DC power, power = abs(F)^2 / n |
| 11 | `acc_spectral_entropy` | log2 Shannon entropy of normalised power over bins 1..64, divided by log2(64) |

If total non-DC power is below 1e-12, features 9, 10 and 11 are set to 0.

- Selected model (validation macro-F1): XGBoost for MotionSense, UCI and Combined (`max_depth` 3, 300 trees; learning rate 0.05, 0.15 for UCI, 0.05 combined).
- Headline results (within-dataset, subject-independent test, XGBoost):

| Dataset | Accuracy | Macro-F1 | Test subjects |
|---|---|---|---|
| MotionSense | 0.9378 | 0.9207 | 4 |
| UCI HAR | 0.9206 | 0.8835 | 9 |

- Cross-dataset (generalisation experiment, not headline): MotionSense -> UCI macro-F1 0.5805, UCI -> MotionSense 0.5539. Combined model: 0.9319 on MotionSense test and 0.8832 on UCI test. These show that a model trained on one device and placement transfers poorly to another. No Android device has been tested, and Android should be treated as a third, unseen domain.

## 2. TYPE_LINEAR_ACCELERATION

**Status: Inferred (Android behaviour not tested here; training-side facts Verified).**

- Android reports acceleration in m/s^2 along the device x/y/z axes, with gravity removed. Android documents it as acceleration excluding gravity. The removal method is implementation-dependent (sensor fusion on many devices, a high-pass or low-pass gravity estimate on others) and varies by vendor and chip.
- Training counterparts: MotionSense `userAcceleration` (iPhone 6s, Core Motion sensor-fusion gravity removal, front trouser pocket) and UCI `body_acc` (Samsung Galaxy S II, waist, 0.3 Hz Butterworth gravity separation after median and 20 Hz Butterworth filtering). Verified from `domain_shift_note`. The two training sources already differ in processing, and Android adds a third processing chain.
- Because the filter is sensor-dependent, low-frequency content (slow postural change, slow turns) may leak into or be removed from the signal differently than in training. Features most exposed: `acc_mag_mean`, `acc_spectral_entropy`, and `acc_dominant_freq_hz` for low-motion windows.

## 3. TYPE_GYROSCOPE (and uncalibrated)

**Status: Inferred.**

- Android reports angular rate in **rad/s**, the same unit as training (MotionSense `rotationRate`, UCI `body_gyro`). No unit conversion is needed, but this equivalence of units for the two training sources is assumed from dataset documentation and is only partly confirmed by the scale comparison (Section 11).
- `TYPE_GYROSCOPE` is the calibrated stream. Android applies drift/bias compensation, so values have the bias removed.
- `TYPE_GYROSCOPE_UNCALIBRATED` gives raw rates plus a separate estimated-bias vector. Proposal: use `TYPE_GYROSCOPE` by default. Use the uncalibrated stream only if the calibrated one shows jumps from bias updates, and then subtract the reported bias in a documented way. Do not mix the two streams in one data set.
- Model B uses only two gyro features (`gyro_mag_mean`, `gyro_mag_var`) from the gyro magnitude. A small constant bias therefore mainly shifts `gyro_mag_mean` for STATIONARY windows. Whether a threshold on this matters has not been measured.

## 4. Unit conversion

**Status: Verified for training units (g and rad/s); Inferred for the Android side.**

- MotionSense and UCI acceleration are in g (Verified in `activity_features.py` docstring, and peak prominence is set in g).
- Android linear acceleration (m/s^2) -> g: `a_g = a_ms2 / 9.80665`. Apply to x, y and z before computing magnitudes.
- Gyro: no conversion (rad/s -> rad/s).
- Peak prominence (0.1 g) and the 1e-12 power floor assume g. Forgetting the division would inflate `acc_mag_*` by about 9.8x and `acc_mag_energy` / `acc_spectral_energy` by about 96x, and would push STATIONARY windows toward WALKING/OTHER.

## 5. Sampling rate and resampling

**Status: Inferred.**

- `SensorManager` rates (`SENSOR_DELAY_GAME`, or `registerListener` with a microsecond period) are requests. The OS may deliver faster or slower, and Android 12+ rate-limits sensors to 200 Hz unless `HIGH_SAMPLING_RATE_SENSORS` is declared. Delivery can be irregular, and batching can change event timing.
- Training assumed 50 Hz. MotionSense has no timestamp column, so its 50 Hz is documented and assumed, not measurable (Verified in `activity_preparation_report.json`). UCI windows are provided rows with no timestamps (Verified), so even the UCI rate was not independently checked.
- Proposal (inference-time only): record `event.timestamp` (nanoseconds) for each sample. Linearly resample each channel onto a uniform 50 Hz grid (20 ms step) before windowing. This is an on-device inference operation. **It does not alter any training data**, and no training file was resampled.
- Risks: (a) linear interpolation attenuates content near and above 25 Hz and slightly lowers peak amplitudes, which may affect `acc_peak_count` and the spectral features; (b) gaps (screen off, Doze, throttling) make interpolation fabricate data, so windows spanning a gap longer than a set limit should be dropped; (c) if the real device rate is below 50 Hz, the effective bandwidth is smaller than in training; (d) resampling is not part of the training pipeline, so any shift it causes in features has not been measured.
- Window: 128 resampled samples (2.56 s), stride 64 (50% overlap). The first prediction is available after 2.56 s of data.

## 6. Axis conventions

**Status: Inferred.**

- Android uses a fixed device frame (x right, y up the screen, z out of the screen). iOS Core Motion may use different axis directions or sign conventions for some channels. Which axes differ between MotionSense and Android has not been checked, so any per-axis sign flip is an assumption.
- Model B uses only **magnitudes** of the acceleration and gyro vectors. Magnitude is unchanged by axis permutation or sign flip, so these differences do not affect the 11 features. This is the main reason the feature set was chosen, and it is Verified that `extract_features` takes `np.linalg.norm` over the three axes before any other step.
- Placement still matters: MotionSense used a trouser pocket and UCI a waist mount, and the cross-dataset macro-F1 (about 0.55 to 0.58) shows placement/device shifts hurt. A phone in a hand, bag or pocket on Android may differ from both. This is not removed by magnitude features.
- Magnitude features do not remove differences in dynamics caused by placement, only in orientation.

## 7. Gravity separation differences

**Status: Verified for the training side, Inferred for Android.**

- MotionSense: Core Motion fused gravity removal. UCI: 0.3 Hz Butterworth high-pass body component. Android: vendor-dependent. Each yields different residual low-frequency behaviour and different noise in STATIONARY windows.
- In the training data STATIONARY windows have median `acc_mag_mean` 0.026 g (MotionSense) and 0.011 g (UCI); WALKING medians are 0.68 g and 0.28 g (Verified, `activity_feature_scale_comparison.json`). The two datasets differ by roughly 2.4x for WALKING magnitude, so absolute magnitude thresholds are not consistent across sources. This is a sign that the classifier is sensitive to the scale of the device and placement.
- If an Android device leaves a residual gravity component (poorly filtered), `acc_mag_mean` for STATIONARY could rise toward about 1 g and the classifier would misreport STATIONARY as WALKING/OTHER. Section 8 covers the fallback.

## 8. Devices without TYPE_LINEAR_ACCELERATION

**Status: Inferred (proposal only).**

- Check `SensorManager.getDefaultSensor(Sensor.TYPE_LINEAR_ACCELERATION)` for null at start-up. Report the device as unsupported for Model B if absent, or use the fallback.
- Fallback option A: use `TYPE_ACCELEROMETER` and `TYPE_GRAVITY` (if present) and subtract. Option B: `TYPE_ACCELEROMETER` with a software high-pass filter. For parity with UCI, a 0.3 Hz Butterworth high-pass is the closest to the training pipeline of one dataset (Verified for UCI). Neither option was tested against Model B, and each should be validated with the parity test in Section 10 and logged data before use.
- A missing gyroscope: Model B uses two gyro features. Retraining without gyro features would be a separate decision and is not proposed here.
- Record in the app which source is in use so results can be separated later.

## 9. Future export options (proposal only, nothing implemented)

**Status: Inferred.**

The selected model is XGBoost (depth 3, 300 trees, 3 classes), and a combined model is also saved (`ml/models/activity_*_xgboost.json` / `.joblib`).

1. **Kotlin feature reimplementation plus exported trees.** Reimplement the 11 features in Kotlin (rFFT, `find_peaks` with prominence and distance, log2 entropy). Trees exported as code or data. Lowest runtime dependency, highest parity-risk (the FFT and `find_peaks` details), so it needs the test plan below.
2. **ONNX** (via `onnxmltools`/`skl2onnx`/XGBoost converter) with ONNX Runtime Mobile for the classifier only. Features still computed in Kotlin.
3. **TFLite**: would require converting the trees (e.g. via a TF decision-forest wrapper) or retraining a different model. Not a direct fit for XGBoost.
4. **m2cgen-style code generation**: translates trained trees into plain Kotlin/Java source. Small and dependency-free. Supports XGBoost models. Compatibility with the installed xgboost 3.2.0 JSON format is unchecked.
5. **Hand-exported trees**: read the XGBoost JSON dump (`activity_*_xgboost.json`) and evaluate it in Kotlin. Same logic as option 4 with full control.

Whatever route is chosen, the class probability or margin output should be compared against the Python model on the same feature vectors (Section 10).

## 10. Feature-parity test plan

**Status: Inferred (plan, not yet run).**

Goal: the Kotlin features equal the Python features on identical input.

1. In Python, pick a fixed set of real windows: for example 3 per class from each dataset (WALKING, STATIONARY, OTHER, MotionSense and UCI), plus one low-power window that triggers the 1e-12 rule if one exists. Save the (128, 6) arrays in g and rad/s as CSV, and the 11-feature output of `extract_features` from `ml/feature_extraction/activity_features.py` as the expected CSV, with full float64 precision.
2. Run the Kotlin implementation on the same arrays as a JVM unit test, with no Android sensor involved and no resampling step.
3. Compare the 11 features per window. Expected: identical for `acc_peak_count`, and equal within a small floating-point tolerance (proposed 1e-9 relative) for the rest. Any difference beyond that is a defect to investigate, not a tolerance to widen. `acc_dominant_freq_hz` should match exactly, since it depends on the argmax bin.
4. Check edge cases explicitly: constant window (all-zero power rule), ties in the FFT argmax, peaks exactly at the prominence threshold, and `std`/`var` using ddof=0.
5. Compare the model output: feed the expected Python features to the exported model and check that predicted class and class probabilities match Python's `predict_proba` (tolerance proposed 1e-6).
6. Then, separately, run an on-device test that adds the unit conversion (m/s^2 -> g) and resampling steps, using a recorded raw Android log. Compare against a Python run of the same pipeline on the same log. This confirms the on-device chain but does not show the classifier is accurate on Android.

## 11. Magnitude-scale comparison against Dryad `motion.csv`

**Status: Verified (not done).**

The optional comparison of Android-style magnitudes against Dryad Phase 1 `motion.csv` was **not done**. The Model B scale file states: "Scale sanity only; the Dryad Phase 1 motion.csv was NOT used." What exists is a MotionSense vs UCI comparison of window-feature quantiles (`activity_feature_scale_comparison.json`, `results/plots/activity_feature_scale_by_dataset.png`). Its main finding is the scale gap: median WALKING `acc_mag_mean` 0.68 g (MotionSense) vs 0.28 g (UCI); median WALKING `gyro_mag_mean` 2.19 vs 0.67 rad/s. It does not say anything about Android.

## 12. Unverified assumptions

1. Android `TYPE_LINEAR_ACCELERATION` returns m/s^2 with gravity removed and behaves like the training `userAcceleration` / `body_acc` after dividing by 9.80665. No Android data has been recorded or compared.
2. The gravity-removal filter varies by device, and its effect on Model B accuracy is unknown.
3. `TYPE_GYROSCOPE` is bias-compensated, and its values are in the same rad/s scale as MotionSense `rotationRate` and UCI `body_gyro`. Not measured. The scale-comparison file shows the training sources differ by about 3x for walking gyro magnitude.
4. MotionSense is exactly 50 Hz (no timestamps, so unmeasurable) and UCI is 50 Hz as documented. Core Motion filtering details are assumed.
5. On-device linear resampling to 50 Hz does not shift the 11 features materially. Not tested. It may shift `acc_peak_count`, `acc_dominant_freq_hz` and the spectral features.
6. Android sensor delivery rates and the Android 12+ rate limit will allow about 50 Hz without gaps in the chosen app configuration.
7. Magnitude features make the iOS vs Android axis conventions irrelevant. Verified for axis flips and permutations, but placement and dynamics differences remain untested.
8. The phone placement on Android (pocket, hand, bag, waist) is within what MotionSense (pocket) and UCI (waist) represent. Unverified.
9. The accuracy figures (0.92 to 0.94) apply to Android devices. They apply only to within-dataset test subjects (4 and 9 subjects). Cross-dataset results (macro-F1 about 0.55 to 0.58) suggest large degradation on a new device.
10. XGBoost JSON/joblib models can be converted to the proposed export formats without changing predictions. Untested.
11. Kotlin `find_peaks` and rFFT reimplementations can match SciPy/NumPy to the tolerance in Section 10. Untested.
12. UCI windows are treated as overlapping and as provided rows. The reported window counts overstate the number of independent samples (see `activity_preparation_report.json`).
13. Fallback paths for devices without `TYPE_LINEAR_ACCELERATION` (Section 8) give acceptable features. Untested.
