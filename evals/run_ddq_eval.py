"""golden_ddq_rules_v1: DDQ answers must name the expected firm rule, or abstain where no rule applies.
Usage: python evals/run_ddq_eval.py PROFILE_JSON [--llm]
Without --llm the word-overlap matcher runs; with --llm the retrieval plus local model runs (LLM_PROVIDER must be set)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app import ddq, ddq_llm  # noqa: E402

GOLD = Path(__file__).resolve().parent / "golden" / "golden_ddq_rules_v1.jsonl"


def accepted_from(profile: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for a in profile["accepted"]:
        out.setdefault(a["key"], []).append({"value": a["value"], "source": a["source"]})
    return out


def main(profile_path: str, use_llm: bool) -> dict:
    acc = accepted_from(json.loads(Path(profile_path).read_text()))
    gold = [json.loads(line) for line in GOLD.open()]
    qs = [ddq.Question(g["id"], "", g["question"]) for g in gold]
    if use_llm:
        from app.llm import get_llm
        got = ddq_llm.answer(qs, acc, get_llm())
    else:
        got = ddq.answer(qs, acc)
    tp = fp = fn = tn = 0
    wrong = []
    for g, r in zip(gold, got, strict=True):
        said = r["status"] == "answered"
        rule = r.get("rule") if said else None
        if g["expect"] is None:
            if said:
                fp += 1
                wrong.append({"id": g["id"], "expected": None, "got": rule})
            else:
                tn += 1
        elif said and rule == g["expect"]:
            tp += 1
        else:
            if said:
                fp += 1
            fn += 1
            wrong.append({"id": g["id"], "expected": g["expect"], "got": rule})
    out = {"n": len(gold), "correct_answers": tp, "wrong_answers": fp, "missed": fn, "correct_abstains": tn,
           "precision": round(tp / (tp + fp), 3) if tp + fp else None,
           "recall": round(tp / (tp + fn), 3) if tp + fn else None, "disagreements": wrong}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1], "--llm" in sys.argv)
