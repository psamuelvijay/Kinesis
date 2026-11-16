"""Phase 4 work item 3, step 1: write ml/fusion_engine/split.json (calibration vs held-out Dryad subjects). Uses NO residual or
evaluation information: the lists come from results/metrics/phase2_splits.json and the metadata hasMotion/hasGNSS columns only.

Rule: calibration = Phase 2 train subjects; held-out = Phase 2 test subjects + Phase 2 validation subjects; subjects without motion
or GNSS cannot be used. Validation subjects (3, 10, 11) went into held-out so that the held-out set has more than one usable subject
(test subjects 1 and 9 have no motion data, leaving only subject 12). They were used only for Model A hyper-parameter selection in
Phase 2 and never for any fusion threshold. Model A is comparison-only in the fusion engine.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml" / "preprocessing"))
import dryad_io as DIO  # noqa: E402


def main():
    p2 = json.loads((ROOT / "results/metrics/phase2_splits.json").read_text())["subjects"]
    md = DIO.metadata()
    usable = md[(md["hasMotion"] == True) & (md["hasGNSS"] == True)]  # noqa: E712
    usable_subj = sorted({int(s) for s in usable["subject"]})
    cal = sorted(s for s in p2["train"] if s in usable_subj)
    held = sorted(s for s in p2["test"] + p2["validation"] if s in usable_subj)
    assert not set(cal) & set(held)
    unusable = {str(s): "no motion and/or no GNSS tracks (metadata hasMotion/hasGNSS)" for s in sorted(p2["train"] + p2["validation"] + p2["test"]) if s not in usable_subj}
    doc = {
        "description": "Calibration vs held-out subjects for the Phase 4 fusion engine (Dryad genuine walking only; Dryad has no spoofing).",
        "source": "results/metrics/phase2_splits.json (subject-level Phase 2 split) intersected with metadata hasMotion==TRUE and hasGNSS==TRUE",
        "calibration_subjects": cal,
        "heldout_subjects": held,
        "heldout_detail": {"phase2_test_with_motion": sorted(s for s in p2["test"] if s in usable_subj),
                           "phase2_validation_with_motion": sorted(s for s in p2["validation"] if s in usable_subj),
                           "note": "Phase 2 validation subjects 3, 10, 11 were used to select Model A hyper-parameters. No fusion threshold has been computed from them. "
                                   "Only subject 12 is fully out-of-sample for Model A; Model A is comparison-only here."},
        "unusable_subjects": unusable,
        "overlap": sorted(set(cal) & set(held)),
        "n_tracks": {"calibration": int(usable["subject"].isin(cal).sum()), "heldout": int(usable["subject"].isin(held).sum())},
        "rules": ["Thresholds, quantiles and persistence N are computed from calibration subjects only.",
                  "Held-out subjects are touched once, by evaluate.py, after thresholds.json is frozen and hashed.",
                  "Split written before any held-out evaluation quantity was computed."],
    }
    (ROOT / "ml/fusion_engine/split.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("calibration_subjects", "heldout_subjects", "n_tracks", "overlap")}))


if __name__ == "__main__":
    main()
