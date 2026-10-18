"""Licence gate: no installed dependency of the default install has an unknown licence, and pymupdf (AGPL) is a
known open item. The audit script is the source of truth; this only fails the build on a row that needs a human read."""
import importlib.metadata as md
import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "licence_audit.py"
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _audit():
    spec = importlib.util.spec_from_file_location("licence_audit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_default_dependencies_have_no_unknown_licence():
    mod = _audit()
    unknown = []
    for name in mod.declared(()):
        try:
            meta = md.metadata(name)
        except md.PackageNotFoundError:
            continue  # not installed here; the audit script reports it as NOT AUDITED
        lic = meta.get("License-Expression") or meta.get("License") or ""
        if mod.classify(lic, meta.get_all("Classifier") or []) == "UNKNOWN":
            unknown.append(name)
    assert not unknown, f"licence needs a human read: {unknown}"


@pytest.mark.xfail(strict=True, reason="docs/LICENSES.md 'Still open': pymupdf (AGPL) is a default dependency "
                   "until the parse engines move to pypdfium2 or pdfplumber. Strict: remove this mark when it moves.")
def test_pymupdf_is_not_a_default_dependency():
    data = tomllib.loads(PYPROJECT.read_text())
    default = data["project"].get("dependencies", [])
    assert not any(re.match(r"(?i)pymupdf", d) for d in default), "pymupdf is AGPL: keep it out of the default install"
