# Review 2: Phase 4 live-data finalisation (SKIP path)

Live evaluation was not performed (user replied SKIP), so only the SKIP checks apply. Suites were not re-run.

**Verdict**: APPROVED

Watch for: (1) `phase4_live_eval.json` and the live calibration JSON still say `PENDING USER DATA`, while the report says `NOT PERFORMED` (confirmed, cosmetic). (2) `results/phase4_report.md`, `results/phase4_run_log.md` and `results/metrics/phase4_preservation_check.json` are modified but uncommitted, and the report says "Committed on `phase4-fusion-engine`" (confirmed). Commit them by explicit path.

## High-level view

Live evaluation is clearly marked not performed. Section 8 of the report carries the required wording ("live evaluation not performed; pending logger validation and S1-S5 collection"). Section 9 (stationary-on-table) is a separate section with the same status. The live JSON records no metrics and states that nothing was simulated.

Thresholds are unchanged. The SHA-256 of `ml/fusion_engine/thresholds.json` (5184189b...b639725) and of `engine.py` (b5340c22...6ab) match `phase4_thresholds_hash.json`. `thresholds.json` still lists `V_MOVE_MPS`, `V_MOVE_DISP_MPS`, `STEP_ZERO_MAX` and `P_STAT_STATIONARY` as provisional. `live_split.json` does not exist, which is correct since no live sessions exist. Because no live data was collected, the live-only checks (session disjointness, evaluation-time freeze, tuning on evaluation data, calibration versus demonstration reporting) do not apply. The working-tree diff touches only report and log text, with no changes under `ml/`.

Scope limits appear in the report header. Model B is stated to be an activity classifier never trained on spoofing. The fusion layer is described as a consistency detector with no learned spoofing classifier. A grep of the report found no reward, crypto or token wording except the line that prohibits it. The `datasets/live_recordings/` directories hold only `.gitkeep`, and no fabricated logs were found.

<details>
<summary>Issues (3)</summary>

1. **Status wording mismatch** (confirmed) — `phase4_live_eval.json` and the live calibration JSON say `PENDING USER DATA`. Either change them to `NOT PERFORMED` or add a note that they mean the same thing.
2. **Uncommitted report edits** (confirmed) — The report, run log and preservation JSON are modified but uncommitted, and the report says everything is committed. Commit these three paths explicitly, with no `git add .`, then push only `phase4-fusion-engine`.
3. **Scenario range inconsistency** (likely) — Report line 174 refers to scenarios "S1 to S7", while the SKIP wording and the next steps refer to S1-S5. Align them with `docs/recording_protocol.md`.

</details>

<details>
<summary>Details</summary>

## Scope of this review

I checked the report text, the run log diff, the threshold and hash files, the live JSON and the git status. I did not recompute the Dryad held-out numbers against their JSON files, so "report numbers match JSON" is only partly verified (the threshold hashes match). Untracked items in `docs/`, `.agents/` and the PDF modification are unrelated and must stay out of the commit.

</details>

<details>
<summary>File map</summary>

- results/phase4_report.md: live sections changed to NOT PERFORMED
- results/phase4_run_log.md: live-gate SKIP entry appended
- results/metrics/phase4_preservation_check.json: verification_live_gate_skip record added

Full diff: `git diff -- results/phase4_report.md results/phase4_run_log.md results/metrics/phase4_preservation_check.json`

</details>
