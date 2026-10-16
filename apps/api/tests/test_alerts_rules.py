"""Alert rules must parse and must only reference metrics the app actually exports."""
import re
from pathlib import Path

import yaml

from app import tracing

RULES = Path(__file__).parents[3] / "deploy" / "monitoring" / "alerts.yml"


def test_rules_parse_and_have_runbook_fields():
    doc = yaml.safe_load(RULES.read_text())
    rules = [r for g in doc["groups"] for r in g["rules"]]
    assert rules and all({"alert", "expr", "labels", "annotations"} <= set(r) for r in rules)
    assert all(r["labels"].get("severity") in {"page", "ticket"} for r in rules)


def test_rules_reference_exported_metrics_only():
    exported = set(re.findall(r"^(pe_\w+)", tracing.render_metrics(), re.MULTILINE)) | {"pe_requests_total"}
    doc = yaml.safe_load(RULES.read_text())
    used = {m for g in doc["groups"] for r in g["rules"] for m in re.findall(r"\b(pe_\w+)", r["expr"])}
    assert used and used <= exported | {"pe_requests_total"}, used - exported
