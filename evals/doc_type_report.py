"""Print accuracy by document type for one golden set, given a results file.

Usage: python evals/doc_type_report.py evals/golden/golden_v1.jsonl results.json
results.json maps item id to true or false for each item the eval scored. Items it did not score are left out."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.eval_report import report


def main(golden: Path, results: Path) -> None:
    items = [json.loads(x) for x in golden.open()]
    print(json.dumps(report(items, json.loads(results.read_text())), indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
