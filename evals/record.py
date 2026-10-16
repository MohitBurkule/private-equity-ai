"""Run the eval suites and post their results to the API so the Evals tab shows history.

Usage: PE_API_URL=http://localhost:8000 PE_API_KEY=pe_... python evals/record.py DATA_DIR [suite ...]
Suites: golden, retrieval, uk, xbrl (default: all). A suite that cannot run (missing data) is reported
and skipped, never recorded as a pass.
"""
import contextlib
import importlib
import io
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
SUITES = {"golden": "run_golden_eval", "retrieval": "run_retrieval_eval", "uk": "run_uk_eval", "xbrl": "run_xbrl_eval"}


def post(url: str, key: str, body: dict) -> None:
    req = urllib.request.Request(f"{url}/evals", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


def main(data: Path, names: list[str]) -> int:
    url, key = os.environ["PE_API_URL"].rstrip("/"), os.environ["PE_API_KEY"]
    bad = 0
    for name in names or list(SUITES):
        try:
            mod = importlib.import_module(SUITES[name])
            with contextlib.redirect_stdout(io.StringIO()):  # the suites print their own report
                metrics = mod.main(data)
        except Exception as e:  # noqa: BLE001 - report and continue with the other suites
            print(f"{name}: could not run ({type(e).__name__}: {e}); not recorded")
            bad += 1
            continue
        post(url, key, {"suite": name, "metrics": metrics})
        print(f"{name}: recorded")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), sys.argv[2:]))
