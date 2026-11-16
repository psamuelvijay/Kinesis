"""Hash files that must stay byte-identical and compare against a saved 'before' snapshot.

Usage:
    python ml/evaluation/preservation_hash.py snapshot            # writes 'before'
    python ml/evaluation/preservation_hash.py compare             # writes 'after' + diff, exit 1 on change
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "metrics" / "phase3_preservation_check.json"

FILES = [
    "docs/Kinesis_Literature_Survey.pdf",
    "docs/Kinesis Data Collection Protocol and Logger Spec (v0.1).md",
    "docs/Kinesis_Guide_Review.pptx",
    "docs/Kinesis_Literature_Review.pptx",
    "docs/Kinesis_Progress_Review_2.pptx",
    "docs/Kinesis_Progress_Review_2_Final.pptx",
    "docs/Review.pptx",
    "ml/models/best_model.joblib",
    "ml/models/random_forest.joblib",
    "ml/models/xgboost.json",
    "results/metrics/phase2_test_predictions.csv",
]
DIRS = [".agents", "datasets"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def collect() -> dict:
    paths = [ROOT / f for f in FILES]
    for d in DIRS:
        base = ROOT / d
        if base.exists():
            paths += [p for p in base.rglob("*") if p.is_file()]
    out = {}
    for p in sorted(set(paths)):
        rel = p.relative_to(ROOT).as_posix()
        out[rel] = sha256(p) if p.exists() else None
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    now = datetime.now(timezone.utc).isoformat()
    cur = collect()
    if mode == "snapshot":
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"before": {"timestamp_utc": now, "sha256": cur}}, indent=2))
        print(f"wrote before: {len(cur)} files")
        return 0
    data = json.loads(OUT.read_text())
    before = data["before"]["sha256"]
    changed = sorted(k for k in before if cur.get(k) != before[k])
    added = sorted(k for k in cur if k not in before)
    data["after"] = {"timestamp_utc": now, "sha256": cur}
    data["comparison"] = {"identical": not changed and not added, "changed_or_missing": changed, "added": added}
    OUT.write_text(json.dumps(data, indent=2))
    print("IDENTICAL" if data["comparison"]["identical"] else f"DIFFERENT: {changed} {added}")
    return 0 if data["comparison"]["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
