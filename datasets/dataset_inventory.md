# Dataset Inventory (Phase 1)

Machine-readable version: `dataset_inventory.json`. Numbers come from `results/metrics/inspect_*.json`, produced by `ml/preprocessing/inspect_*.py`. Raw files under `datasets/*/raw/` are unmodified.

| | Dryad walking | MotionSense | UCI HAR |
|---|---|---|---|
| Source | https://datadryad.org/dataset/doi%3A10.5061/dryad.n2z34tn5q (DOI 10.5061/dryad.n2z34tn5q) | https://github.com/mmalekzadeh/motion-sense | https://archive.ics.uci.edu/dataset/240/human+activity+recognition+using+smartphones (DOI 10.24432/C54S4K) |
| Version | Dryad v6, published 2024-11-01 | GitHub master, commit 261cb0d | v1.0 (UCI page updated 2024-03-10) |
| License | CC0-1.0 | MIT | CC BY 4.0 |
| Status | Downloaded (`Data.zip` untouched; extracted copy in `datasets/dryad/extracted/`), inspected | Downloaded, inspected | Downloaded, inspected |
| Usable subjects | 18 with GPS + steps; 14 with GPS + motion + steps (19 in metadata) | 24 | 30 (21 train, 9 test; no overlap) |
| Usable recordings | 198 tracks with GPS + steps (Model A); 146 with GPS + motion + steps (fusion calibration); 203 in metadata | 360 (24 subjects x 15 trials) | 10,299 pre-cut windows |
| Measured sampling rate | GPS median of per-track medians 1.0 Hz (range 0.14-1.90); motion about 58.8 Hz median interval (17 ms); steps rows irregular, 0.25-1.98 Hz mean | not measurable (no timestamps); documented 50 Hz | not measurable (no timestamps); documented 50 Hz |
| Excluded | Model A: 6 folders; fusion: 58 folders | none for missing data; see mismatch below | none |

## Dryad
Source files: `data/metadata_tracks.csv` (203 rows, 23 columns, 19 subjects) and `data/subject_S/S_N/{events,positions,steps,motion,orientation}.csv` per track; `reference_cont_distance.csv` exists in 35 tracks (metadata `gt_type` = continuous: 35, final: 168). The extracted tree has 204 track folders. Folder `8_10` has data (positions 281 rows, steps 423, motion 10,506) but no row in `metadata_tracks.csv`, so it has no reference distance or device info. It is excluded.

Columns (all from the data): positions `ms, latitude, longitude, altitude, confInterval, heading, speed`; steps `ms, steps, floorsUp, floorsDown, distance, startDate, endDate`; motion `ms, accelX/Y/Z, accelWithGX/Y/Z, rotRateAlpha/Beta/Gamma, interval`; orientation `ms, abs, alpha, beta, gamma`; events `signalStart, testStart, testEnd`. Metadata has missing values only in distanceByApp, totSteps, total_gaps_time_gnss, fs_gnss, fs_steps (5 each, the no-GNSS tracks) and total_gaps_time_inertial, fs_acc (52 each, the no-motion tracks).

Availability from metadata: hasMotion True 151 / False 52; hasGNSS True 198 / False 5. Motion and GNSS: both 146, motion only 5, GNSS only 52, neither 0.

**Usable tracks**
- Model A (valid GPS, GPS speed present, steps present): 198 tracks, 18 subjects.
- Fusion calibration (also motion present): 146 tracks, 14 subjects (3-8, 10-14, 16-18).

**Excluded**
- 5 tracks `15_0`-`15_4`: hasGNSS=False, positions.csv and steps.csv empty. They still have motion data. Subject 15 is entirely excluded from Model A.
- `8_10`: no metadata row.
- 52 tracks for fusion only: hasMotion=False, motion.csv empty. They remain usable for Model A. Subjects 0, 1, 2 and most of 9 are in this group. Full list in `dataset_inventory.json` under `excluded_recordings`.

**Sampling rates (measured per track from `ms`, not uniform)**
- GPS (198 tracks): median of per-track median rates 1.0 Hz, 25th percentile 0.25 Hz, minimum 0.14, maximum 1.90. Largest gap in a track: median 4.7 s, maximum 361 s.
- Motion (152 tracks with data): median interval gives 58.8 Hz for every track, but the mean rate per track ranges 6.3 to 60.0 Hz. Four tracks of subject 8 (`8_2`, `8_4`, `8_6`, `8_10`) are far below 50 Hz (6.3, 15.2, 22.6, 31.2 Hz mean; one of them, `8_10`, is already excluded).
- Steps rows: mean 0.25 to 1.98 rows per second per track, irregular, max gap 1 to 300 s. Rows per track: median 328.

**steps.csv semantics (differs from the README)**
The README describes `steps` as an incremental count. In all 198 usable tracks `startDate` has a single value, `endDate` grows, and the last `steps` value equals metadata `totSteps` in 197 tracks (off by 1 in one). So `steps` is a running total since `startDate`. Incremental steps per GPS window must be derived by differencing. In 40 of 198 tracks (subjects 3, 10, 11, 12, 14, 18) the running total is not monotonic, with decreases of up to 4 steps between rows. Identical `ms` values occur on consecutive rows. The sum of the raw `steps` column is 22 to 787 times totSteps and must not be used as a target.

**Time alignment**
- All times are ms from a per-track `signalStart`. There is no wall clock or time zone, so no time-zone error is possible, and the phone clocks cannot be synchronised across devices.
- The README says positions `ms` zero equals testStart. The data do not agree: positions `ms` begins before testStart in the median track (median of first position minus testStart -3.1 s, range -59.4 s to 0), and positions end near testEnd (median -0.4 s). The positions clock therefore looks like the signalStart axis, which is how steps.csv is also stamped (endDate max minus testEnd, median -3.1 s). This is an inference, not documented.
- Positions `ms` is not monotonic in 16 of 198 tracks (subjects 5 and 14). Sort before windowing.
- GPS speed: 53 of the 198 tracks contain `speed` = -1 rows (invalid), and the valid fraction of rows per track has median 99% but minimum 48%. Filter negatives before use.
- Path length from GPS coordinates over distanceReference: median 1.02. 26 of 198 tracks lie outside 0.8-1.25 (min 0.24, max 18.2 for `5_5`). 106 tracks have anonymized coordinates (`gnss_anonimized`=True); their median ratio is 1.01, so shape and distance appear preserved, but absolute positions are not real.
## MotionSense
- Streams (zip, 360 CSVs each): A_DeviceMotion (1,412,865 rows total), B_Accelerometer (1,433,825), C_Gyroscope (1,413,262).
- Columns: A has `attitude.roll/pitch/yaw`, `gravity.x/y/z`, `rotationRate.x/y/z`, `userAcceleration.x/y/z`. B and C have `x,y,z`. Every file has an unnamed integer index column and no timestamp.
- Missing values: 0 in all columns of all streams.
- Subjects: 24 (codes 1-24, matching `data_subjects_info.csv`: code, weight, height, age, gender; 14 gender=1, 10 gender=0).
- Labels (folder prefix): dws (downstairs) 72 recordings, jog 48, sit 48, std 48, ups (upstairs) 72, wlk 72. Trials: dws 1,2,11; ups 3,4,12; sit 5,13; std 6,14; wlk 7,8,15; jog 9,16.
- Recording length: min 377, median 2,948.5, max 16,424 rows (A stream).
- Issue: all 360 recordings have different row counts across streams. B has 17 to 198 more rows than A (median 48). C differs from A by -1 to +5 rows. Without timestamps the accelerometer and gyroscope streams cannot be sample-aligned.

## UCI HAR
- 10,299 windows of 128 samples (2.56 s, 50% overlap), 561-feature vectors, 9 raw Inertial Signals (total_acc, body_acc, body_gyro, each x/y/z). 0 missing values in X and all signal files.
- Train: 7,352 windows, 21 subjects. Test: 2,947 windows, 9 subjects. No subject appears in both.
- Labels: 1 WALKING, 2 WALKING_UPSTAIRS, 3 WALKING_DOWNSTAIRS, 4 SITTING, 5 STANDING, 6 LAYING. Train counts 1226/1073/986/1286/1374/1407. Test counts 496/471/420/491/532/537.
- Units per README: total_acc and body_acc in g, body_gyro in rad/s.

