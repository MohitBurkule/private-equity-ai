"""Google Drive (Docs/Sheets exported to Office formats), Box and Dropbox file stores."""
from __future__ import annotations

import json
from urllib.parse import quote

from app.connectors.base import Connector, Item

D = "https://www.googleapis.com/drive/v3"
EXPORT = {  # native Google types cannot be downloaded raw; export to formats ingest understands
    "application/vnd.google-apps.document": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
FOLDER = "application/vnd.google-apps.folder"


class GoogleDrive(Connector):
    """opts: folder=<folder id> (default root)."""
    name, label = "gdrive", "Google Drive / Sheets"

    def items(self, limit: int = 50):
        stack, n = [(self.opts.get("folder", "root"), "")], 0
        while stack and n < limit:
            fid, prefix = stack.pop()
            token = ""
            while n < limit:
                q = quote(f"'{fid}' in parents and trashed=false")
                page = self._get_json(f"{D}/files?q={q}&pageSize=100&fields=nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime)"
                                      + (f"&pageToken={token}" if token else ""))
                for f in page.get("files", []):
                    if n >= limit:
                        return
                    mt, name = f["mimeType"], f["name"]
                    if mt == FOLDER:
                        stack.append((f["id"], f"{prefix}{name}/"))
                        continue
                    if mt in EXPORT:
                        out_mt, ext = EXPORT[mt]
                        data = self.http(f"{D}/files/{f['id']}/export?mimeType={quote(out_mt)}", self._auth())
                        name += ext
                    elif mt.startswith("application/vnd.google-apps."):
                        continue  # forms, drawings, shortcuts: no faithful export
                    else:
                        data = self.http(f"{D}/files/{f['id']}?alt=media", self._auth())
                    # Every file cites its Drive page; the fallback covers responses that omit webViewLink.
                    url = f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view"
                    yield Item(f["id"], f"{prefix}{name}", data, url, f.get("modifiedTime", ""))
                    n += 1
                token = page.get("nextPageToken", "")
                if not token:
                    break

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}


class Box(Connector):
    """opts: folder=<folder id> (default 0 = root)."""
    name, label = "box", "Box"

    def items(self, limit: int = 50):
        stack, n = [(self.opts.get("folder", "0"), "")], 0
        while stack and n < limit:
            fid, prefix = stack.pop()
            offset = 0
            while n < limit:
                page = self._get_json(f"https://api.box.com/2.0/folders/{fid}/items?limit=100&offset={offset}&fields=id,name,type,modified_at,etag")
                rows = page.get("entries", [])
                for e in rows:
                    if e["type"] == "folder":
                        stack.append((e["id"], f"{prefix}{e['name']}/"))
                    elif e["type"] == "file" and n < limit:
                        data = self.http(f"https://api.box.com/2.0/files/{e['id']}/content", {"Authorization": f"Bearer {self.token}"})
                        yield Item(e["id"], f"{prefix}{e['name']}", data, f"https://app.box.com/file/{e['id']}",
                                   e.get("etag") or e.get("modified_at", ""))
                        n += 1
                offset += len(rows)
                if not rows or offset >= page.get("total_count", 0):
                    break


class Dropbox(Connector):
    """opts: path='' (root). Uses list_folder + download; both are POST in the real API, so this
    connector uses the `Http` hook with the JSON args in the Dropbox-API-Arg header / query form."""
    name, label = "dropbox", "Dropbox"

    def items(self, limit: int = 50):
        path = self.opts.get("path", "")
        page = self._post_json("https://api.dropboxapi.com/2/files/list_folder", {"path": path, "recursive": True})
        n = 0
        while True:
            for e in page.get("entries", []):
                if e.get(".tag") != "file":
                    continue
                if n >= limit:
                    return
                arg = json.dumps({"path": e["id"]})
                data = self.http("https://content.dropboxapi.com/2/files/download",
                                 {"Authorization": f"Bearer {self.token}", "Dropbox-API-Arg": arg})
                yield Item(e["id"], e["path_display"].lstrip("/"), data,
                           f"https://www.dropbox.com/home{quote(e['path_display'])}", e.get("rev", ""))
                n += 1
            if not page.get("has_more"):
                return
            page = self._post_json("https://api.dropboxapi.com/2/files/list_folder/continue", {"cursor": page["cursor"]})

    def _post_json(self, url: str, body: dict) -> dict:
        # Http is GET-shaped; the body rides in a header the default transport turns into a POST.
        raw = self.http(url, {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                              "X-Post-Body": json.dumps(body)})
        return json.loads(raw)
