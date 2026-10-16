"""golden_uk_ixbrl_v1: parsed identities and reliability flags must equal the golden labels.
Usage: python evals/run_uk_eval.py DATA_DIR"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.ixbrl import read_ixbrl  # noqa: E402


def main(data: Path) -> dict:
    n = rel_ok = checks_ok = fig_ok = missing = 0
    bad = []
    for line in (data / "golden" / "golden_uk_ixbrl_v1.jsonl").open():
        it = json.loads(line)
        path = data / it["sources"][0]["file"]
        if not path.exists():
            missing += 1
            continue
        n += 1
        r = read_ixbrl(path.read_text(errors="replace"))
        a = it["answer"]
        gold_checks = a.get("internal_checks", {})
        got = {k: v for k, v in r.checks.items() if v is not None}
        c_ok = got == gold_checks
        checks_ok += c_ok
        rel_ok += r.reliable == a["reliable"]
        f_ok = all(float(r.facts.get(k, -1)) == float(a[g]) for k, g in
                   (("FixedAssets", "fixed_assets"), ("TotalAssetsLessCurrentLiabilities",
                    "total_assets_less_current_liabilities"), ("Equity", "equity"))
                   if a.get(g) is not None and k in r.facts)
        fig_ok += f_ok
        if not (c_ok and r.reliable == a["reliable"] and f_ok):
            bad.append({"id": it["id"], "gold": [a["reliable"], gold_checks], "got": [r.reliable, got]})
    out = {"n": n, "missing_files": missing, "reliable_flag_correct": rel_ok,
           "identity_checks_equal": checks_ok, "figures_equal": fig_ok, "disagreements": bad[:10]}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(Path(sys.argv[1]))
