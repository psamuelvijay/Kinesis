# Fixtures: FORMAT TEST ONLY

`FORMAT_TEST_ONLY_session/` is a hand-specified, 6-second schema-conformance fixture for `ingest_live_logs.py`
(50 Hz alternating placeholder values, seven GPS rows, three step-counter rows).

**Format test only. Not data. Not used for any metric, threshold or calibration.** No phone recorded it.
`ingest_live_logs.py` rejects it unless called with the `format_test` split, so it cannot enter `evaluate_live.py` or `calibrate_live.py`.

