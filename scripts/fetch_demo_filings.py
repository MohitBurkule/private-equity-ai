"""Download the public SEC filings the demo seeds from, into DATA_DIR/filings, with a manifest.

  SEC_USER_AGENT="Name contact" python scripts/fetch_demo_filings.py DATA_DIR

Each file's URL, retrieval date and SHA-256 go into DATA_DIR/filings/manifest.json, so a later run can
show exactly which bytes the demo used. Files already present with a matching hash are not fetched again.
The User-Agent is read from the environment only; it is never written to the manifest or the repo.
"""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# (local name, SEC URL). The local names are what scripts/seed_ixbrl_facts.py and demo_extras.py expect.
FILES = [
    ("3M_2019_10K.htm",
     "https://www.sec.gov/Archives/edgar/data/66740/000155837020000581/mmm-20191231x10k62bf35.htm"),
    ("XPO_Ex10-2_TermLoanA_Agreement_2026-06.htm",
     "https://www.sec.gov/Archives/edgar/data/1166003/000110465926068522/tm2616097d1_ex10-2.htm"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(url: str, ua: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main() -> None:
    folder = Path(sys.argv[1]) / "filings"
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    ua = os.environ.get("SEC_USER_AGENT", "")
    if not ua:
        sys.exit("SEC_USER_AGENT is not set; SEC rejects anonymous requests. Skipping download.")
    for name, url in FILES:
        target = folder / name
        known = manifest.get(name, {})
        # A cached file counts only if its bytes still match the hash recorded when it was fetched.
        if target.exists() and known.get("sha256") == sha256(target):
            print(f"cached: {name}")
            continue
        target.write_bytes(fetch(url, ua))
        manifest[name] = {"url": url, "retrieved": datetime.now(UTC).date().isoformat(), "sha256": sha256(target)}
        print(f"fetched: {name} sha256={manifest[name]['sha256']}")
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n")


if __name__ == "__main__":
    main()
