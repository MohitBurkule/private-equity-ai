"""Affinity stage sync: off unless AFFINITY_STAGE_SYNC=1. The payload shape is an unverified mock. SYNTHETIC records."""
import base64
import json

import pytest

from app.connectors.base import ConnectorError
from app.connectors.crm import Affinity


def _conn(http):
    return Affinity("tok", http, objects="opportunities")


def test_stage_sync_is_refused_while_the_flag_is_off(monkeypatch):
    monkeypatch.delenv("AFFINITY_STAGE_SYNC", raising=False)
    c = _conn(lambda *a: b"{}")
    with pytest.raises(ConnectorError, match="off"):
        c.fetch_stages(5)
    with pytest.raises(ConnectorError, match="off"):
        c.push_stage("9", "Won")


def test_flag_on_reads_and_writes_the_mock_shape(monkeypatch):
    monkeypatch.setenv("AFFINITY_STAGE_SYNC", "1")
    calls = []

    def http(url, headers):
        calls.append((url, headers))
        return json.dumps([{"id": 9, "name": "Synth Atlas", "stage": "Diligence"}]).encode()

    c = _conn(http)
    assert c.fetch_stages(5) == [{"id": "9", "name": "Synth Atlas", "stage": "Diligence"}]
    c.push_stage("9", "Won")
    url, headers = calls[-1]
    assert url == "https://api.affinity.co/opportunities/9"
    assert headers["X-Method"] == "PUT" and json.loads(headers["X-Post-Body"]) == {"stage": "Won"}
    assert headers["Authorization"] == "Basic " + base64.b64encode(b":tok").decode()
