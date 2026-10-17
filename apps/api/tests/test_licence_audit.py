import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from licence_audit import classify


def test_permissive_licence_passes():
    assert classify("MIT", []) == "PERMISSIVE"


def test_copyleft_is_flagged_not_refused():
    assert classify("LGPL-3.0-only", []) == "COPYLEFT"
    assert classify("", ["License :: OSI Approved :: GNU Affero General Public License v3"]) == "COPYLEFT"


def test_missing_licence_is_unknown_never_guessed():
    assert classify("", []) == "UNKNOWN"
    assert classify("Proprietary EULA", []) == "UNKNOWN"
