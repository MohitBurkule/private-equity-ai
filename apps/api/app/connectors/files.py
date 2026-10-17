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

    def _drive_acl(self, fid: str) -> tuple[str, ...]:
        """Email addresses of the users and groups a file is shared with. Groups appear as "group:{email}". Anyone-with-
        the-link and domain-wide shares name no address, so they are left out and fail closed."""
        perms = self._get_json(f"{D}/files/{fid}/permissions?fields=permissions(type,emailAddress)").get("permissions", [])
        return tuple(f"group:{p['emailAddress']}" if p.get("type") == "group" else p["emailAddress"]
                     for p in perms if p.get("emailAddress") and p.get("type") in ("user", "group"))

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
                    acl = self._drive_acl(f["id"])
                    yield Item(f["id"], f"{prefix}{name}", data, url, f.get("modifiedTime", ""), acl=acl)
                    n += 1
                token = page.get("nextPageToken", "")
                if not token:
                    break

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}


class Box(Connector):
    """opts: folder=<folder id> (default 0 = root)."""
    name, label = "box", "Box"

    def _collaborators(self, kind: str, oid: str) -> set[str]:
        """Who Box lets into this file or folder: a user's login, or "group:{id}" for a group. A share by link names
        nobody, so it is left out and the item fails closed for everyone not named."""
        rows = self._get_json(f"https://api.box.com/2.0/{kind}/{oid}/collaborations?fields=accessible_by").get("entries", [])
        out = set()
        for r in rows:
            who = r.get("accessible_by") or {}
            if who.get("type") == "user" and who.get("login"):
                out.add(who["login"])
            elif who.get("type") == "group" and who.get("id"):
                out.add(f"group:{who['id']}")
        return out

    def items(self, limit: int = 50):
        # Each entry carries the access granted on the folders above it. Box inherits folder collaborations down the
        # tree, so a file is reachable by anyone shared on any ancestor folder as well as on the file itself.
        stack, n = [(self.opts.get("folder", "0"), "", frozenset())], 0
        while stack and n < limit:
            fid, prefix, inherited = stack.pop()
            folder_acl = inherited | frozenset(self._collaborators("folders", fid)) if fid != "0" else inherited
            offset = 0
            while n < limit:
                page = self._get_json(f"https://api.box.com/2.0/folders/{fid}/items?limit=100&offset={offset}&fields=id,name,type,modified_at,etag")
                rows = page.get("entries", [])
                for e in rows:
                    if e["type"] == "folder":
                        stack.append((e["id"], f"{prefix}{e['name']}/", folder_acl))
                    elif e["type"] == "file" and n < limit:
                        data = self.http(f"https://api.box.com/2.0/files/{e['id']}/content", {"Authorization": f"Bearer {self.token}"})
                        acl = folder_acl | frozenset(self._collaborators("files", e["id"]))
                        yield Item(e["id"], f"{prefix}{e['name']}", data, f"https://app.box.com/file/{e['id']}",
                                   e.get("etag") or e.get("modified_at", ""), acl=tuple(sorted(acl)))
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
