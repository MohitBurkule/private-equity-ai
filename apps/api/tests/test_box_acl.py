"""Box items carry the access Box grants: users by login, groups by id, and folder shares inherited down the tree.
Runs against a local mock of the Box API, so no real account or credential is used."""
import json

from app.connectors.files import Box


def mock_box(routes):
    """routes maps a URL fragment to a JSON body (dict) or raw bytes. Any unmatched URL fails the test."""
    calls = []

    def http(url, headers):
        calls.append(url)
        for frag, body in routes.items():
            if frag in url:
                return body if isinstance(body, bytes) else json.dumps(body).encode()
        raise AssertionError(f"unexpected request: {url}")

    http.calls = calls
    return http


def collab(kind, login=None, group=None):
    who = {"type": "user", "login": login} if login else {"type": "group", "id": group}
    return {"accessible_by": who}


def test_a_file_carries_its_own_collaborators_and_the_folder_shares_above_it():
    routes = {
        "/folders/0/items": {"total_count": 1, "entries": [{"id": "10", "name": "Deal", "type": "folder"}]},
        "/folders/10/collaborations": {"entries": [collab("folder", login="partner@fund.example")]},
        "/folders/10/items": {"total_count": 1, "entries": [{"id": "99", "name": "cim.pdf", "type": "file",
                                                              "etag": "7"}]},
        "/files/99/collaborations": {"entries": [collab("file", login="vp@fund.example")]},
        "/files/99/content": b"%PDF-1.4 cim",
    }
    http = mock_box(routes)
    (item,) = list(Box("tok", http=http, folder="10").items())
    assert item.acl == ("partner@fund.example", "vp@fund.example")
    assert item.name == "cim.pdf" and item.version == "7"


def test_a_group_share_is_recorded_by_its_id():
    routes = {
        "/folders/0/items": {"total_count": 1, "entries": [{"id": "10", "name": "Deal", "type": "folder"}]},
        "/folders/10/collaborations": {"entries": [collab("folder", group="123")]},
        "/folders/10/items": {"total_count": 1, "entries": [{"id": "99", "name": "model.xlsx", "type": "file"}]},
        "/files/99/collaborations": {"entries": []},
        "/files/99/content": b"PK",
    }
    (item,) = list(Box("tok", http=mock_box(routes), folder="10").items())
    assert item.acl == ("group:123",)


def test_an_item_nobody_is_shared_with_gets_an_empty_list_so_it_fails_closed():
    routes = {
        "/folders/0/items": {"total_count": 1, "entries": [{"id": "99", "name": "note.docx", "type": "file"}]},
        "/files/99/collaborations": {"entries": []},
        "/files/99/content": b"PK",
    }
    (item,) = list(Box("tok", http=mock_box(routes)).items())
    assert item.acl == ()  # an empty list hides the item from every principal the source does not name
