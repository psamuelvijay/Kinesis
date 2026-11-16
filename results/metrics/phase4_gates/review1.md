# Phase 4 fusion engine: independent review (pass 1 re-review)

The Phase 4 fusion engine is calibrated and evaluated on genuine Dryad walking only. It is committed on `phase4-fusion-engine` as 1b3b9b1. It uses no ML for the fusion layer, no synthetic attack data and no Dryad detection rate. The earlier CHANGES_REQUESTED findings are fixed.

Watch for: live stationary and mock-location evaluation is pending user recordings, so the stationary thresholds are provisional (confirmed). Held-out coverage is weak: 41% of windows are INSUFFICIENT_DATA and 17 of 52 tracks never reach a reported GENUINE_WALKING (confirmed). The report states both.

**Verdict**: APPROVED

## High-level view

The engine is a deterministic, rule-based consistency detector. Its thresholds are quantiles of genuine walking from calibration subjects 4,5,6,7,8,13,14,16,17,18. Held-out subjects 3,10,11,12 are disjoint. The thresholds.json SHA-256 (5184189b...b639725) matches phase4_thresholds_hash.json, and evaluate.py asserts that hash before it evaluates (confirmed from the file and the run log). I did not re-run the suites. The coder's log records 56 tests passing and two reruns with hash-identical outputs.

On held-out genuine walking there were 5 raw SUSPICIOUS windows and 0 after persistence N=2. Report figures match phase4_dryad_eval.json: 962 windows (32.6%) GENUINE_WALKING, 708 (24.0%) UNCERTAIN, 1,210 (41.0%) INSUFFICIENT_DATA, and a median 50 s to the first reported GENUINE_WALKING with 17 tracks never reaching it. Every spec, report and JSON scope line says Dryad has no spoofing and gives no detection rate. Model B is described as an activity classifier not trained on spoofing, and the fusion layer as a consistency detector.

The wording is "movement accepted / flagged". A text search of the specs and reports for reward, crypto and token found only the "no rewards, crypto or tokens" statements. datasets/live_recordings holds only .gitkeep files, and the live calibration and evaluation outputs say PENDING. The only fixture is FORMAT_TEST_ONLY_session, which is flagged and refused for the calibration and evaluation splits.

The Phase 4 commit changes nothing under .agents/ or the PDF, and it adds no change to the Model A or Model B files. The PDF is still modified in the working tree, and the run log records its hash as unchanged.

## Notes (non-blocking)

1. The run log says the Dryad IMU check found Model B recognises only about half of genuine hand-held walking as WALKING. The held-out coverage numbers reflect that domain gap. This is disclosed, and the Android plan must calibrate on-device.
2. docs/model_documentation.md has an uncommitted three-line Phase 4 section appended. It is a tracked, agent-authored doc, and the edit is logged in the run log and the report. Ask the user whether to commit it. It touches no user-owned document.
3. Validation subjects were moved to held-out. This is disclosed and does not affect the thresholds.
4. The calibrated branch of calibrate_live.py and the S5 branch of evaluate_live.py have never run on real data (disclosed).

<details><summary>Issues (3)</summary>

1. **Provisional stationary thresholds** — V_MOVE, V_MOVE_DISP, STEP_ZERO_MAX and P_STAT_STATIONARY have no live stationary data behind them. Collect the S2/S3 recordings before any Android claim.
2. **Live evaluation pending** — no detection, latency or table-test numbers exist. Run the S1 and S4-S7 evaluation recordings per docs/recording_protocol.md.
3. **Uncommitted model_documentation.md section** — get the user's decision on committing it.

</details>
