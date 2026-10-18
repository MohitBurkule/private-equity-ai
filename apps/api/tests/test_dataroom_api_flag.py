"""Room API mock adapter, behind DATAROOM_API=1. The response shape is a fixture, not a vendor contract."""
import json

import pytest

from app.connectors.base import ConnectorError
from app.connectors.dataroom import DatasiteApi, IntralinksApi


def fake(routes):
    seen = []

    def http(url, headers):
        seen.append((url, headers))
        if url not in routes:
            raise AssertionError(f"unexpected call {url}")
        return json.dumps(routes[url]).encode()
    return http, seen


FILES = {"files": [{"path": "Finance/ebitda.xlsx", "size": 2048, "modified": "2026-09-01"},
                   {"name": "Legal/msa.pdf", "size": "512", "modified": "2026-09-02"}]}
PERMS = {"permissions": [{"user": "deal-team@fund.example", "role": "editor"}]}


def test_room_api_is_off_by_default(monkeypatch):
    monkeypatch.delenv("DATAROOM_API", raising=False)
    http, seen = fake({})
    with pytest.raises(ConnectorError, match="DATAROOM_API=1"):
        IntralinksApi("tok", http, room_id="r1").list_files()
    assert seen == []  # no call leaves the process while the flag is off


def test_room_api_lists_files_and_permissions_when_on(monkeypatch):
    monkeypatch.setenv("DATAROOM_API", "1")
    http, seen = fake({"https://api.datasite.com/rooms/r9/files?limit=200": FILES,
                       "https://api.datasite.com/rooms/r9/permissions": PERMS})
    c = DatasiteApi("tok", http, room_id="r9")
    assert c.list_files() == [
        {"path": "Finance/ebitda.xlsx", "size": 2048, "modified": "2026-09-01"},
        {"path": "Legal/msa.pdf", "size": 512, "modified": "2026-09-02"}]
    assert c.permissions() == [{"user": "deal-team@fund.example", "role": "editor"}]
    assert all(h["Authorization"] == "Bearer tok" for _, h in seen)


def test_room_id_is_required(monkeypatch):
    monkeypatch.setenv("DATAROOM_API", "1")
    with pytest.raises(ConnectorError, match="room_id"):
        IntralinksApi("tok", fake({})[0]).permissions()
