"""Answer-accuracy eval for /ask on FinanceBench numeric questions, with the local LLM.

Reuses the FinanceBench runner in run_llm_eval.py and reports:
  exact_numeric_match  share of questions whose answer contains the gold number
  verified_wrong       share answered with a verified claim that has the wrong number
  abstain              share the system declined to answer
  abstain_when_unsure  of the questions it did not get right, the share it abstained on
Usage: python evals/run_answer_accuracy.py DATA_DIR [--n 50]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.llm import get_llm
from run_llm_eval import (
    run_financebench,
)


def main(data: Path, n: int) -> dict:
    r = run_financebench(get_llm(), data, n)
    total, correct = r["n"], r["correct"]
    not_correct = total - correct
    return {"suite": "answer_accuracy", "n": total,
            "exact_numeric_match": round(correct / total, 3) if total else None,
            "verified_wrong": round(r["verified_wrong"] / total, 3) if total else None,
            "abstain": round(r["abstained"] / total, 3) if total else None,
            "abstain_when_unsure": round(r["abstained"] / not_correct, 3) if not_correct else None}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 50
    args = [a for a in args if a != str(n)]
    print(json.dumps(main(Path(args[0]), n), indent=1))
