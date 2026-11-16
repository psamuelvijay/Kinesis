# Dataset Documentation (Phase 1)

Status of each dataset as found during Phase 1. Details and numbers: `datasets/dataset_inventory.md` and `results/metrics/inspect_*.json`.

## A. Dryad walking activity dataset
Caramaschi et al., Malmö University and Oxford University Hospitals NHS Trust. Dryad v6 (2024-11-01), CC0-1.0. `Data.zip` (166,445,892 bytes) was downloaded manually and is untouched in `datasets/dryad/raw/`. An extracted copy is in `datasets/dryad/extracted/` (git-ignored). Script: `ml/preprocessing/inspect_dryad.py`, output `results/metrics/inspect_dryad.json` (per-track detail).

- 19 subjects, 203 tracks in `metadata_tracks.csv`, 35 with continuous reference distance and 168 with final distance only. All phones were hand held. Devices include iPhones and Android phones (22 models). Timed Walk app 183 tracks, Malisa 20.
- Usable: 198 tracks (18 subjects) have GPS and steps. 146 tracks (14 subjects) also have motion. Exclusions and reasons: `datasets/dataset_inventory.md`.
- Motion has `accelX/Y/Z` without gravity, `accelWithGX/Y/Z` with gravity (m/s^2), and `rotRate*`, so raw-style accelerometer and gyroscope inputs exist for the fusion pipeline. They exist only for the 146 tracks.
- Dryad contains no spoofed GPS. Only genuine walking is available.

Issues that affect Model A (details in the inventory):
1. `steps` is a running total since a fixed `startDate`, not an incremental count as the README says. Targets must be differences of `steps` between window boundaries. In 40 tracks the running total decreases by up to 4 between rows.
2. Step rows are irregular (0.25 to 1.98 per second on average, gaps up to 300 s), so a 5 s window can have no step row. Window targets should be interpolated or built from the step total at window edges, and the rule must be documented.
3. GPS rates vary by track (median 1 Hz, but 25% of tracks are at or below 0.25 Hz). A 5 s window has 0 to 5 fixes. Rows with `speed` = -1 are invalid.
4. Positions timestamps look like they use the signalStart axis, contradicting the README. Positions are not monotonic in 16 tracks.
5. 106 tracks have anonymized coordinates. Distances and speeds are usable, absolute positions are not.
6. Motion sampling rate is about 59 Hz in most tracks and far lower in subject 8's tracks. Model B at 50 Hz needs resampling for Dryad motion.
## B. MotionSense
iPhone 6s in the front trouser pocket, SensingKit/Core Motion, documented 50 Hz, 24 participants, 15 trials each, 6 activities. MIT.
- Used files: `B_Accelerometer_data.zip` and `C_Gyroscope_data.zip` for Model B inputs; `A_DeviceMotion_data.zip` is a derived Core Motion product (gravity/userAcceleration split, attitude).
- No timestamps. 50 Hz cannot be measured from the data.
- Accelerometer and gyroscope streams of the same recording differ in length for all 360 recordings (accelerometer up to 198 rows longer). Any pairing needs a documented trimming or alignment rule, and cannot create samples.
- Mapping to project classes: wlk to WALKING; sit and std to STATIONARY; jog, ups, dws to OTHER.

## C. UCI HAR
Samsung Galaxy S II on the waist, 30 volunteers aged 19-48, 50 Hz, video-labelled. CC BY 4.0.
- Distributed as 2.56 s windows (128 samples, 50% overlap) rather than continuous recordings. Overlap means window-level random splits would leak; use subject-level splits.
- The original train/test split is by subject (21/9).
- Raw signals: total_acc (g, with gravity), body_acc (g), body_gyro (rad/s).
- Mapping: WALKING to WALKING; SITTING, STANDING, LAYING to STATIONARY; WALKING_UPSTAIRS, WALKING_DOWNSTAIRS to OTHER.

## Limitations affecting later phases
1. Fusion threshold calibration is limited to 14 subjects (146 tracks) with motion data. Model A uses 18 subjects (198 tracks), so subject-independent splits are small.
2. Device and placement differ: iPhone pocket (MotionSense), Samsung waist (UCI), and Dryad phones (many models, hand held). Cross-dataset results will include this shift.
3. Neither activity dataset has timestamps, and both are documented at 50 Hz only. Resampling to 50 Hz is a no-op if that holds, but it cannot be verified.
4. UCI windows are fixed at 128 samples, which constrains window sizes for Model B on UCI data.
5. Model B trained on these datasets has no GPS-spoofing labels. Its accuracy says nothing about spoofing detection.
6. Android step counter data are not in any of these datasets; fusion uses it only in live testing.

