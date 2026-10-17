"""Google Drive folder ingest against a local fake of the Drive v3 API: nested folders, citations, limit."""
import json

from app.connectors.files import GoogleDrive

D = "https://www.googleapis.com/drive/v3/files"


def drive(routes):
    def http(url, headers):
        assert headers["Authorization"] == "Bearer tok"
        if url in routes:
            return routes[url]
        for k, v in routes.items():
            if url.startswith(k):
                return v
        raise AssertionError(f"unrouted {url}")
    return http


def listing(files):
    return json.dumps({"files": files}).encode()


def test_nested_folders_keep_paths_and_every_file_cites_drive():
    routes = {
        f"{D}?q=%27root%27": listing([
            {"id": "deals", "name": "Deals", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "top", "name": "Teaser.pdf", "mimeType": "application/pdf", "modifiedTime": "t1"}]),
        f"{D}?q=%27deals%27": listing([
            {"id": "atl", "name": "Atlas", "mimeType": "application/vnd.google-apps.folder"}]),
        f"{D}?q=%27atl%27": listing([
            {"id": "m1", "name": "Model", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "t2"}]),
        f"{D}/top?alt=media": b"%PDF",
        f"{D}/m1/export": b"PK",
    }
    items = list(GoogleDrive("tok", drive(routes)).items())
    names = sorted((i.name, i.url) for i in items)
    assert names == [
        ("Deals/Atlas/Model.xlsx", "https://drive.google.com/file/d/m1/view"),
        ("Teaser.pdf", "https://drive.google.com/file/d/top/view")]
    assert all(i.url.startswith("https://drive.google.com/") for i in items)


def test_limit_stops_the_walk_early():
    routes = {
        f"{D}?q=%27root%27": listing([
            {"id": "a", "name": "a.pdf", "mimeType": "application/pdf"},
            {"id": "b", "name": "b.pdf", "mimeType": "application/pdf"}]),
        f"{D}/a?alt=media": b"a",
        f"{D}/b?alt=media": b"b",
    }
    items = list(GoogleDrive("tok", drive(routes)).items(limit=1))
    assert [i.name for i in items] == ["a.pdf"]
