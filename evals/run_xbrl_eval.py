"""Check app.xbrl against golden_xbrl_v1: companyfacts lookup by accn+concept+period must equal the
golden value (which was independently read from the filing's inline XBRL).
Usage: python evals/run_xbrl_eval.py DATA_DIR"""
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.xbrl import candidates, crosscheck, load_companyfacts, period_from_context  # noqa: E402


def main(data: Path) -> dict:
    cache, counts, bad = {}, {}, []
    for line in (data / "golden" / "golden_xbrl_v1.jsonl").open():
        it = json.loads(line)
        ix = next((s for s in it["sources"] if s["type"] == "ixbrl"), None)
        api = next((s for s in it["sources"] if s["type"] == "xbrl-api"), None)
        if ix is None or api is None:  # items kept for other checks have no inline/API pair to compare
            counts["no_ixbrl_api_pair"] = counts.get("no_ixbrl_api_pair", 0) + 1
            continue
        per = period_from_context(ix["contextRef"])
        if per is None:  # opaque context ids (c-12): fall back to the dates in the question text
            q = it["question"]
            m = re.search(r"(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", q)
            m2 = re.search(r"(?:as of|at) (\d{4}-\d{2}-\d{2})", q)
            per = (m.group(1), m.group(2)) if m else ((None, m2.group(1)) if m2 else None)
        if per is None:
            counts["unparsed_context"] = counts.get("unparsed_context", 0) + 1
            bad.append((it["id"], "context", ix["contextRef"]))
            continue
        facts = cache.setdefault(api["file"], load_companyfacts(json.loads((data / api["file"]).read_text())))
        cands = candidates(facts, ix["concept"], per[1], per[0], accn=ix["accn"], unit=None)
        res = crosscheck(Decimal(str(it["answer"]["value"])), cands)
        counts[res.status] = counts.get(res.status, 0) + 1
        if res.status != "match":
            bad.append((it["id"], res.status, ix["concept"], per, [str(v) for v in res.distinct_values]))
    out = {"counts": counts, "not_match": bad[:15]}
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]))
