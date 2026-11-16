# Phase 3 Plan: Model B Activity Classifier

Written before any Phase 3 implementation. Status: plan only. Phase 3 stops at the report; no Android development, no merge into main. All metrics will come from files produced by scripts on real data. No number is entered by hand and none is estimated in advance.

Sources read: `results/phase2_report.md` (Section 8), `datasets/dataset_inventory.md/.json`, `docs/dataset_documentation.md`, `docs/model_documentation.md`, `results/metrics/inspect_motionsense.json`, `inspect_uci_har.json`, `ml/preprocessing/inspect_*.py`.

---

## 1. Scope

Implemented in Phase 3:

1. **Model B**: a physical-activity classifier (WALKING / STATIONARY / OTHER) trained on MotionSense and UCI HAR activity labels.
2. **Model A follow-up 1**: timestamp-alignment sensitivity check.
3. **Model A follow-up 2**: anomalous-GPS-track exclusion table.
4. **Read-only inspection** of the four modified Phase 2 model/prediction files.
5. **Android compatibility document** for inference inputs.

Not in scope: Android development, fusion logic, merging into main, any GPS-spoofing training or evaluation.

**Spoofing statement (applies to every Phase 3 document).** Model B is trained on activity labels only. Neither dataset contains spoofed GPS. Model B is not trained or evaluated on GPS-spoofing attacks, and its accuracy says nothing about spoofing detection. Spoofing detection will come from the later fusion logic.

---

## 2. Fixed decisions (from the user)

| Item | Decision |
|---|---|
| MotionSense inputs | `A_DeviceMotion` `userAcceleration.x/y/z` (g) and `rotationRate.x/y/z` (rad/s) |
| UCI HAR inputs | Raw Inertial Signals `body_acc_x/y/z` (g) and `body_gyro_x/y/z` (rad/s), 128-sample rows |
| Excluded inputs | `total_acc`, MotionSense `gravity.*`, `attitude.*`, `B_Accelerometer`, and the 561 precomputed UCI features |
| Window | 128 samples at 50 Hz (2.56 s), 50% overlap (stride 64), within recordings only |
| Resampling | None. No interpolation and no created samples |
| Headline | Within-dataset, subject-independent evaluation |
| Cross-dataset and combined-model | Reported separately as generalisation experiments |

Using only `A_DeviceMotion` for both accelerometer and gyroscope removes the cross-stream alignment problem: Phase 1 found row-count mismatches between A, B and C in all 360 recordings (maximum difference 198 rows). Both signals come from the same file, so row i of acceleration and rotation rate belong to the same record.

**MotionSense sampling rate.** 50 Hz is documented, not measured. MotionSense has no timestamp column (`has_timestamp_column` false in `inspect_motionsense.json`), so the rate cannot be verified from the data. "128 samples = 2.56 s" for MotionSense rests on that documentation. The same is true for UCI HAR, which is distributed as already-cut windows without timestamps.

**Processing differences, to be documented in the report.** `userAcceleration` is the output of the Core Motion sensor-fusion gravity removal on an iPhone 6s in a front trouser pocket. UCI `body_acc` is gravity-removed with a low-pass filter on a Samsung Galaxy S II at the waist. Both are in g and gravity-free, but their filters, devices and placements differ. This is a known source of cross-dataset shift. Gyroscope units are rad/s in both.

---

## 3. Datasets and label mapping

### 3.1 MotionSense
24 subjects, 15 trials (360 recordings), 6 activities. Recordings are read from `A_DeviceMotion_data.zip` without modifying the raw files. Windows are cut within each recording only (never across recordings). A trailing partial window shorter than 128 samples is dropped and counted.

### 3.2 UCI HAR
30 subjects. Windows are used as provided (128 samples per row, per Inertial Signals file). I will not reconstruct continuous signals from the overlapping rows. The original split is subject-disjoint: 21 train subjects, 9 test subjects.

### 3.3 Label mapping

| Class | MotionSense | UCI HAR |
|---|---|---|
| WALKING | `wlk` | WALKING |
| STATIONARY | `sit`, `std` | SITTING, STANDING, LAYING |
| OTHER | `jog`, `ups`, `dws` | WALKING_UPSTAIRS, WALKING_DOWNSTAIRS |

Jogging and stairs are never STATIONARY, and a test will assert this on the mapping. WALKING is level walking only. Class counts per dataset and split will be reported after mapping, since OTHER and STATIONARY are composites.

---

## 4. Experiments

### 4.1 Headline: within-dataset, subject-independent

- **MotionSense.** 24 subjects, fixed seed, split 16 train / 4 validation / 4 test subjects. No subject appears in two sets.
- **UCI HAR.** Provided 21/9 train/test split. A subject-disjoint validation set is carved from the 21 train subjects. The 9 test subjects are not used for any choice.
- **Test protocol.** Models, features and hyperparameters are chosen on validation only. The test set is scored once, with the final configuration. Test scores are not used to change anything.
- **Models compared** (suitable for 2.56 s windows of 6 channels, on engineered features): majority-class baseline, logistic regression, Random Forest, XGBoost (gradient boosting). Features: per-channel and magnitude statistics (mean, std, min, max, energy, zero crossings, and a few frequency-domain terms), identical code for both datasets. Raw-window deep models are not planned unless the reviewer asks for them. Final feature list and grids are frozen before looking at test.

### 4.2 Generalisation experiments (reported separately, never as the headline)
- Train on MotionSense, test on UCI HAR (and the reverse).
- Combined model: train on both datasets' train subjects, test on each dataset's held-out subjects.
- Cross-dataset runs use the same features and label mapping. Their weaker results are expected from device, placement and filter differences and will be reported as found.

### 4.3 Model A follow-up: timestamp-alignment sensitivity
Phase 2 adopted H0 (no lag shift) with moderate confidence. Phase 3 re-evaluates the existing Model A on the existing test windows under alternative alignments: the H1 convention (positions relative to testStart), and sub-window shifts smaller than the 5 s windows used in Phase 2 (for example plus or minus 1, 2 and 3 s of GPS offset against steps). It reports MAE, RMSE and R2 per alignment for Random Forest and XGBoost on the unchanged subject split. Phase 2's coarse window-index shifts are not repeated. The stored models are not retrained. The outcome is reported as sensitivity only and does not change the Phase 2 headline.

### 4.4 Model A follow-up: anomalous-GPS-track exclusion table
The 25 tracks with GPS path / distanceReference outside 0.8-1.25 stay in the headline results. A separate table gives results with them excluded, for validation and test and for each model, plus per-subject counts of excluded windows. The table is built from stored predictions and the existing flags.

### 4.5 Read-only inspection of the four modified Phase 2 files
`git status` shows modified Phase 2 artefacts in `ml/models/` (including `best_model.joblib`, `random_forest.joblib`, `xgboost.json`, `training_config.json`, `evaluation_metrics.json`) and `results/metrics/` (`phase2_model_metrics.json`, `phase2_test_predictions.csv`), plus plots. I will identify which four files the user means, or inspect all that appear modified, using `git diff`, hashes and metadata only, and write down what differs from HEAD. I will not restore, discard, stage or overwrite them. Any decision about them goes back to the user. `.agents/` and the unrelated `docs/` changes are also left untouched.

### 4.6 Android compatibility document
`docs/android_compatibility.md` covers:
- `TYPE_LINEAR_ACCELERATION` (m/s^2, gravity removed) provides the accelerometer input; divide by 9.80665 to get g.
- `TYPE_GYROSCOPE` (rad/s) provides the gyroscope input.
- Sampling: request 50 Hz (`SensorManager` period 20,000 us). Android treats the period as a hint, and delivery is irregular. The inference input has to be exactly 128 samples. The document will state how the app must buffer, and that resampling or interpolation done on the phone is outside what the model was trained on, so any mismatch is a stated risk.
- Axes: Android device axes versus Core Motion axes (and sign conventions) and whether features chosen are invariant to them (magnitude-based features are, per-axis features are not). Device-orientation and pocket/waist placement shift is stated as untested.
- Filter differences between Android linear acceleration, Core Motion `userAcceleration` and UCI `body_acc` are stated as an unverified compatibility risk.
- The document will say that no Android data were collected or tested in Phase 3.

---

## 5. Expected outputs

| Output | Path |
|---|---|
| This plan | `results/phase3_plan.md` |
| MotionSense preparation script | `ml/preprocessing/phase3_prepare_motionsense.py` |
| UCI HAR preparation script | `ml/preprocessing/phase3_prepare_uci_har.py` |
| Feature extraction (shared) | `ml/phase3_features.py` |
| Training and evaluation script | `ml/phase3_train_activity.py` |
| Splits and exclusion counts | `results/metrics/phase3_splits.json`, `results/metrics/phase3_preparation_report.json` |
| Within-dataset metrics (headline) | `results/metrics/phase3_within_dataset_metrics.json` |
| Cross-dataset and combined metrics | `results/metrics/phase3_generalisation_metrics.json` |
| Model A alignment sensitivity | `results/metrics/phase3_model_a_alignment_sensitivity.json` |
| Model A anomalous-track table | `results/metrics/phase3_model_a_anomaly_exclusion.json` |
| Phase 2 file inspection (read-only) | `results/metrics/phase3_phase2_file_inspection.json` |
| Confusion matrices and figures | `results/plots/phase3_*.png` |
| Models (new files, Phase 2 models untouched) | `ml/models/model_b/` |
| Android compatibility | `docs/android_compatibility.md` |
| Phase 3 report with proposed Phase 4 plan | `results/phase3_report.md` |
| Documentation update | `docs/model_documentation.md` (new Model B section appended, nothing existing rewritten) |

Outputs go to new file names so existing Phase 2 files are not overwritten.

---

## 6. How success is evaluated

Success means the work is correct, reproducible and honestly reported. It does not mean a target accuracy.

**Metrics (Model B).** Accuracy, per-class and macro precision, recall and F1, and a confusion matrix (counts and row-normalised) for every reported test. Class counts are given next to every table. Macro-F1 is the primary summary because the classes are imbalanced. Results are compared with the majority-class baseline.

**Checks that must pass (written into the metrics files):**
1. Zero subject overlap between train, validation and test, in every experiment.
2. No window crosses a recording boundary; no resampling, interpolation or created samples (row counts before and after windowing reconcile, with dropped partial windows counted).
3. Only the specified channels are used as model inputs (no `total_acc`, gravity, attitude, 561 features).
4. Label mapping test: jog, ups, dws, UCI upstairs and downstairs are never STATIONARY.
5. Test sets are scored once per experiment; selection used validation only.
6. Fixed seeds recorded; running the scripts again reproduces the metric files, and package versions are saved.
7. Every number in `phase3_report.md` appears in a metric file.
8. Preservation: Phase 2 tracked files, `.agents/` and unrelated `docs/` are unchanged by Phase 3 (hash comparison before and after).
9. Model A follow-ups: the alignment table covers every alternative alignment listed in 4.3, and the anomaly table shows headline (all tracks) and exclusion results side by side.

**Reporting rules.** Within-dataset results are the headline. Cross-dataset and combined-model results are labelled generalisation. Small test sets (4 MotionSense subjects, 9 UCI subjects) get per-subject results and a note that differences between models may be within subject variation. Weak or negative results are reported as found. The report states that MotionSense 50 Hz is documented and unmeasured, that no Android data were tested, and that the classifier has no spoofing labels.

---

## 7. Risks and open items

- MotionSense `userAcceleration` and UCI `body_acc` differ in device, placement and gravity-removal method, so cross-dataset scores will likely be lower than within-dataset scores.
- STATIONARY merges sitting, standing and laying. Laying exists only in UCI HAR. Per-dataset class balance will be shown.
- OTHER merges jogging and stairs, which can look like walking in 2.56 s windows. Confusion between WALKING and OTHER is expected and will be inspected in the confusion matrices.
- Overlapping windows from the same recording share samples. Subject-level splits prevent leakage, and the report notes that window counts overstate independent sample size.
- Identity of "the four modified model/prediction files" is inferred from `git status`; the inspection will list exactly what it found.

---

## 8. Proposed order of work

1. Inspection and hash snapshot (read-only) of Phase 2 files, `.agents/`, unrelated `docs/`.
2. MotionSense and UCI HAR preparation, with counts.
3. Features, splits, within-dataset training and one-time test scoring.
4. Generalisation experiments.
5. Model A alignment sensitivity and anomaly exclusion table.
6. Android compatibility document, report and documentation append.
7. Post-run preservation check. Stop for review.
