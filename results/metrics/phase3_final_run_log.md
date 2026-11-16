# Phase 3 final report and verification: run log
Branch `phase3-activity-classifier`. Nothing committed. `final_review.json` did not exist, so the full task was done.
## What was run
1. `python ml/evaluation/phase3_verify.py rerun` (system Python 3.14.3, scikit-learn 1.8.0, xgboost 3.2.0): ran `ml/activity_classifier/run_pipeline.py` twice. Both exit 0. SHA-256 of 10 outputs (within/generalisation/preparation/splits/feature-scale JSON, test predictions CSV, feature list, three model JSONs) were identical between run 1 and run 2 and equal to the files that existed before the reruns. PASS.
2. `python ml/evaluation/phase3_verify.py checks`: zero subject leakage PASS; no jog/stairs mapped to STATIONARY PASS (STATIONARY sources: sit, std, LAYING/SITTING/STANDING); no GPS/step features, 11 magnitude features PASS; raw dataset zips (5) equal to the 'before' snapshot PASS.
3. `python ml/evaluation/phase3_verify.py final` (run several times as the report was edited): report numbers generated from the JSON files all found in `results/phase3_report.md` (0 missing) PASS; four Phase 2 files vs `git show HEAD:` PASS (CSV only after CRLF normalisation); `ml/evaluation/preservation_hash.py compare` run, 'after' and 'comparison' written to `phase3_preservation_check.json`.
## Failures and caveats
- Preservation compare is not identical. Docs (7 files) and `.agents/` (6 files) are byte-identical. The four Phase 2 files differ from the 'before' snapshot because the 'before' snapshot held their modified versions and an earlier step restored them from HEAD (logged as user-approved; this step could not confirm the approval and restored nothing). Eight new Model A sensitivity window CSVs appear as 'added'.
- The earlier restore record has SHA-256 values for `xgboost.json` and the predictions CSV that do not match actual HEAD hashes. Actual files equal HEAD.
- The Model B pipeline rerun rewrote output files with identical bytes; no tracked Phase 2 file was touched by this step.
- `docs/model_documentation.md` was unmodified in git before this step, so a Model B section was appended to it (no separate file written).
- Not run: Dryad `motion.csv` scale comparison; no Android; no unit-test file.
## Files written
`results/phase3_report.md`, `results/metrics/phase3_verification.json`, `results/metrics/phase3_final_run_log.md`, `ml/evaluation/phase3_verify.py`, appended section in `docs/model_documentation.md`, `results/metrics/phase3_preservation_check.json` ('after' section updated).

## Review-fix pass (final_review.json, 6 findings)
- Report: restore approval marked UNVERIFIED (user must confirm, else a violation); verification table now shows the strict preservation check as FAILED (identical: false) with a conditional pass; disclosed the 21-line edit to docs/model_documentation.md; reworded the alignment-sensitivity sentence; labelled limitation 5 (Verified/Inferred); kept the seven system-Python artefacts open and unstaged.
- phase3_modified_files_inspection.json: corrected the two garbled hashes (worktree values), approval marked UNVERIFIED.
- phase3_verify.py: 'passed' for preservation is now the strict result; added passed_only_if_restore_approval_confirmed. Re-ran 'python ml/evaluation/phase3_verify.py final': all checks true except strict preservation (false, only the four restored files differ). Nothing committed.

- Orchestrator confirmed the user approved the four-file restore (chat reply to the modela-followups request). Report, inspection JSON and verifier updated to approved_by_user=true / PASS-with-approved-exception; re-ran 'phase3_verify.py final': all checks true. Not committed.
