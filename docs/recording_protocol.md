# Kinesis Phase 4: Live Recording Protocol (v1.0)

Status: written 2026-11-16, before any live recording exists. Companion to `docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md` (the "Logger Spec", referenced and not edited here). Where the Logger Spec defines a stream, field or file name, this protocol uses it unchanged. The additions are listed in section 4.

Purpose: record real phone data that (a) calibrate the stationary side of the fusion thresholds and (b) evaluate the frozen engine on held-out recordings. The engine is a **GPS-motion consistency detector**. It compares GPS-reported movement with phone motion (Model B activity probabilities and the step counter). It is not a learned spoofing classifier, and Model B is an activity classifier that was never trained on spoofing. The product wording is **movement accepted / movement flagged**.

Rules that apply to everything below:

- Real recordings only. Nobody generates, edits, interpolates, shifts or replays log rows. A session that went wrong is discarded and re-recorded (Logger Spec rule 4), never repaired.
- Spoofing in scenarios S5 and S6 is done with a mock-location app on your own phone, as a controlled demonstration, as the Logger Spec section 12 requires.
- The label comes from what you physically did (the setup), written on the task card. `Location.isMock` is logged and checked as a sanity test of the setup. It is never the label.

## 1. Scenarios

| Code | Scenario | Phone | GPS | Ground truth (`ground_truth`) | Engine is expected to report |
| --- | --- | --- | --- | --- | --- |
| S1 | Genuine walking outdoors | in hand, viewing/swinging | real | `walking` | movement accepted (GENUINE_WALKING) |
| S2 | Stationary on a table (outdoors or by a window, open sky) | flat on a table | real | `physically_stationary` | STATIONARY |
| S3 | Stationary in hand, standing still | in hand | real | `physically_stationary` | STATIONARY |
| S4 | Pocket walking outdoors | front or back trouser pocket | real | `walking` | movement accepted |
| S5 | Mock-location spoofing, phone physically stationary | flat on a table | mock app replays a walking route | `physically_stationary` | movement flagged (SUSPICIOUS_GPS_MOVEMENT) |
| S6 (optional) | Mock location while the user genuinely walks (conflict case) | in hand | mock app | `walking` | none defined. Reported separately, not counted as a miss |
| S7 (optional) | Vehicle, stairs or jogging | in hand or pocket | real | `other` | UNCERTAIN (never accepted, never flagged) |

Notes per scenario:

- **S1 and S4**: walk a continuous outdoor route of at least 5 min with open sky. Mix of paces is welcome; do not stop for more than a few seconds. S1 is the reference case for "movement accepted". S4 checks that a pocket does not turn real walking into a flag.
- **S2**: phone flat, screen up, on a stable table, outdoors or at an open window so GPS has fixes. Nobody touches it. The table must not vibrate (no one typing on it).
- **S3**: stand still holding the phone as when looking at it. Small natural hand movement is expected and is the point of the scenario. Do not sit or lie down.
- **S5**: phone flat on a table, untouched for the whole session. Start the mock-location app on a pre-defined walking route (use the same route(s) as the S1 walks where the app allows it) at walking pace. Developer options must have the mock app selected. Real GPS must be off for the app's mock provider to take over; note what the app does in the session notes. Do not carry, tilt or tap the phone during the bout.
- **S6**: same mock setup, but you genuinely walk with the phone. The phone motion and steps are real while GPS is mock. A consistency detector has nothing to contradict here, so this is a documented limit, not a target. Label it `S6` every time.
- **S7**: any of bus/car, stairs up and down, jogging. These test that the engine does not accept or flag behaviour outside walking. Record the sub-type in `notes`. Real GPS only.

## 2. Required amounts

| Item | Requirement |
| --- | --- |
| Duration of one session (operator start to operator end, still periods excluded) | **at least 5 min** (300 s). Shorter sessions are parsed but listed as below the minimum and reported separately |
| Sessions per required scenario (S1 to S5) | **at least 3**, recorded in separate visits (different time of day or day) |
| People | at least 2 if possible; each person records S1, S3 and S4 at least once. S2 and S5 can be done by either person |
| Phones | at least 2 different phone models if possible. Any one phone must not be the only source of S5 |
| Optional S6, S7 | at least 1 session each, 5 min, if recorded |
| Mock route | at least 1 route for S5; each route used in at least 2 S5 sessions |

With fewer people or phones the evaluation still runs. The report then states the real counts and makes no claim beyond them.

## 3. Calibration versus held-out evaluation (rule fixed before any data are seen)

Decided on 2026-11-16 and not changed after the first recording is looked at.

1. Two folders: `datasets/live_recordings/calibration/` and `datasets/live_recordings/evaluation/`.
2. `calibrate_live.py` recalibrates only the stationary GPS-jitter and stationary-IMU thresholds (`V_MOVE_MPS`, `V_MOVE_DISP_MPS`, `STEP_ZERO_MAX`, `P_STAT_STATIONARY`). It therefore uses only **S2 and S3 with real GPS**. All other scenarios (S1, S4, S5, S6, S7) are **evaluation only** and go to `evaluation/`. Mock-location sessions are never calibration data.
3. The split unit is the session. All sessions of one (person, phone, day) block go to one folder.
4. Evaluation recordings come from **different sessions and different days** than the calibration recordings. With two or more people, at least one person records S2 and S3 only in `evaluation/`. With three or more people or phones, one person and one phone are held out of calibration entirely.
5. Evaluation recordings are never used to set, adjust or choose a threshold, a persistence value, a scenario definition or an inclusion rule. If the evaluation shows a problem, the finding is reported. Changing a threshold afterwards needs new calibration recordings and a new held-out set.
6. `session.json` carries `"split"`. The tools refuse a session whose `split` differs from the folder it is in. `calibrate_live.py` never lists or opens `evaluation/`.
7. The engine, `split.json` and `thresholds.json` stay frozen (SHA-256 in `results/metrics/phase4_thresholds_hash.json`). `evaluate_live.py` refuses to run if any of them changed. Live recalibration writes a separate `thresholds_live.json` with its own hash, selected only by the flag `--use-live-calibration`.
8. Until real calibration data exist the stationary thresholds stay **provisional (no live stationary calibration data)** and every evaluation states that.

## 4. Log schema

One folder per session, `raw/<session_id>/` layout of the Logger Spec section 5, copied under `datasets/live_recordings/<split>/<session_id>/`. Files may be `.csv` or `.csv.gz`. Time columns are `SensorEvent.timestamp` and `Location.getElapsedRealtimeNanos()` unchanged (monotonic nanoseconds since boot, one clock), as the Logger Spec section 5 requires. Wall-clock time appears only once per session plus `utc_ms` in the location file.

| File | Columns | Android source | Notes |
| --- | --- | --- | --- |
| `linear_accel.csv` | `t_ns,x,y,z,accuracy` | `TYPE_LINEAR_ACCELERATION` | m/s^2, gravity removed. **Addition to the Logger Spec**, which lists `accel` (raw accelerometer): the fusion pipeline needs the gravity-free stream. Log `accel.csv` as well if you like; the tools read only `linear_accel.csv` and reject files whose median magnitude exceeds 5 m/s^2 (gravity included) |
| `gyro.csv` | `t_ns,x,y,z,accuracy` | `TYPE_GYROSCOPE` | rad/s |
| `step_counter.csv` | `t_ns,cumulative` | `TYPE_STEP_COUNTER` | cumulative since boot, on change. **Write the first value delivered after registering**; it is the baseline. Before the first change the counter is treated as unchanged |
| `step_detector.csv` | `t_ns` | `TYPE_STEP_DETECTOR` | optional, per event, reference only |
| `location.csv` | `t_ns,utc_ms,provider,lat,lon,alt,accuracy,speed,speed_acc,bearing,bearing_acc,is_mock` | `LocationManager` GPS provider | `t_ns` = `elapsedRealtimeNanos`. `is_mock` = `Location.isMock()` (API 31+) or `isFromMockProvider()` (older), written 0/1. Log the GPS provider at 1 Hz; keep whatever fields the app provides, do not fill gaps |
| `events.csv` | `t_ns,type,note` | logger | `bout_start`, `bout_end` and the other events of the Logger Spec section 4 |
| `session.json` | see below | logger + operator | |

`session.json` required fields (the Logger Spec section 4 names are kept; new ones marked *new*):

| Field | Content |
| --- | --- |
| `session_id`, `subject_id`, `protocol_version` | naming in section 6; pseudonymous subject (`S01`, `S02`) |
| `split` *new* | `calibration` or `evaluation` |
| `scenario` *new* | `S1` to `S7` |
| `ground_truth` *new* | `walking`, `physically_stationary` or `other`. Must match the scenario table above. Written from the task card, not from sensors |
| `device_model`, `android_version`, `sdk_int`, `manufacturer` | device (auto) |
| `start_utc_ms`, `start_elapsed_ns`, `boot_offset_ms` | `boot_offset_ms` = wall clock minus elapsed realtime at start |
| `operator_start_utc_ms`, `operator_end_utc_ms` *new* | the experimenter's start and end of the controlled bout (walking begins / phone placed and untouched; walking ends / phone picked up). The engine only evaluates inside this interval. The 10 s countdown and the 5 s still periods lie outside it |
| `has_step_counter` | true if the phone has `TYPE_STEP_COUNTER` (a stream with no change events then counts as zero steps) |
| `route_id`, `placement`, `orientation`, `environment` | context |
| `mock_app_name`, `mock_route_id` | required for S5 and S6 |
| `gps_provider` *new, optional* | provider name to evaluate, default `gps` |
| `notes` | anything unusual (phone fell, call, interruption) |

Sanity checks done by `ingest_live_logs.py`. A failing session is rejected with its reason and listed, never repaired: `split` equals the folder; `ground_truth` matches the scenario; S5 and S6 have at least 90% mock fixes and the other scenarios at most 1% (this tests the setup, it does not label); `linear_accel` is gravity-free; gyro is in rad/s; location is on the sensor clock (otherwise `utc_ms` minus `boot_offset_ms` is used and noted).

## 5. What the tools do with the logs

- **Model B inputs.** Linear acceleration is divided by 9.80665 (g). Each of the two streams is resampled to a 50 Hz grid using only observed samples. A grid point is valid only if the two observed samples around it are at most 100 ms apart, so long gaps are never bridged. Windows are 128 samples with stride 64, dropped if any point is invalid or fewer than 64 observed samples lie inside. This is the same pipeline as `dryad_imu_compat.py`.
- **GPS.** The Phase 2 cleaning rules: accuracy missing or above 50 m, duplicates and teleports (over 10 m/s) are dropped; speed counts only if finite and not negative; a 5 s window overlapping a gap over 10 s, or without a usable fix, becomes INSUFFICIENT_DATA. Mock apps that provide no accuracy therefore end up as INSUFFICIENT_DATA. That is reported as found, with the cleaning counts.
- **Steps.** Increase of `TYPE_STEP_COUNTER` inside each 5 s window.
- **Engine.** Frozen `engine.py` with `thresholds.json`, persistence N = 2.

Run order after recording:

```
python ml/fusion_engine/ingest_live_logs.py --check <session_dir>     # per-session schema check, writes nothing
python ml/fusion_engine/calibrate_live.py                              # calibration/ only; PENDING USER DATA until enough S2+S3 exist
python ml/fusion_engine/evaluate_live.py                               # frozen thresholds, provisional stationary side
python ml/fusion_engine/evaluate_live.py --use-live-calibration        # only after calibrate_live.py wrote thresholds_live.json
```

`calibrate_live.py` needs at least 2 sessions and 60 usable 5 s windows for each of S2 and S3. `evaluate_live.py` writes `results/metrics/phase4_live_eval.json` and `phase4_live_windows.csv`.

Metrics reported (reported state after persistence): spoofing detection rate per session and per decision window (S5; windows counted over all windows and over evaluable windows); time to detection (operator start to the end of the first flagged window; the floor is N x 5 s = 10 s); false positive rate on S1 to S4 (windows, sessions, episodes per device-hour); GPS distance falsely accepted (metres of GPS path inside windows reported GENUINE_WALKING during S5, with S6 separately); false "movement accepted" rate on physically stationary sessions (S2, S3, S5); per-scenario confusion over GENUINE_WALKING, STATIONARY, SUSPICIOUS_GPS_MOVEMENT, UNCERTAIN, plus an INSUFFICIENT_DATA column.

## 6. File naming

Session folder: `<SPLIT>-<YYYYMMDD>-<subject>-<device>-<scenario>-<nn>`, for example `CAL-20261120-S01-pixel7-S2-01` or `EVAL-20261125-S02-redmi-S5-02`. `<SPLIT>` is `CAL` or `EVAL`, `<nn>` counts sessions of the same block. The `session_id` inside `session.json` equals the folder name. Use pseudonymous subject IDs only. Raw logs contain GPS positions: they stay local or in the private store of the Logger Spec section 5, and `datasets/live_recordings/` is git-ignored (only the `.gitkeep` placeholders are tracked).

## 7. Checklist per session

Before:
- [ ] Phone charged above 30%, free storage above 500 MB, battery optimisation off for the logger.
- [ ] Task card chosen (scenario S1 to S7). The split folder for this (person, phone, day) is decided from section 3 **now**.
- [ ] GPS fix outdoors with accuracy 20 m or better; for S5/S6 mock app installed, selected in Developer options, route loaded; for S1 to S4, S7 the mock app is **off** and mock location is not selected.
- [ ] Logger writes `linear_accel`, `gyro`, `step_counter`, `location` (with `is_mock`), `events`; first step-counter value recorded at start.
- [ ] Phone placement as the scenario says (table flat / in hand / pocket).

During:
- [ ] Countdown, 5 s still, **operator start time noted**, bout of at least 5 min, **operator end time noted**, 5 s still.
- [ ] S2 and S5: nobody touches the phone or the table. S5: mock route runs at walking pace the whole bout.
- [ ] Anything unplanned (fall, call, stop, GPS lost for long): discard the session and re-record.

After:
- [ ] `session.json` complete: `scenario`, `ground_truth`, `split`, operator start/end, device, mock app (S5/S6).
- [ ] Run `ingest_live_logs.py --check <folder>` and read the warnings (duration, clock, mock fraction).
- [ ] Copy the folder to `datasets/live_recordings/<split>/`. Do not move it between splits afterwards.
- [ ] Record SHA-256 of the files (Logger Spec `manifest.sha256`).

## 8. Known limits to state when reporting

- The mock-location demonstration shows a consistency check on one mock app and the phones used. It is not a general anti-spoofing result, and S6 (mock while walking) is out of reach of this design by construction.
- The Dryad data that calibrated the walking thresholds are hand-held walking recorded with a different device set. Live S1 to S4 evaluate how those thresholds transfer to Android phones, including pocket carrying, which the calibration data do not contain.
- Few sessions give coarse rates. Report counts with the rates.
