"""Microsoft Graph: Outlook mail, plus OneDrive/SharePoint document libraries (one API, one token)."""
from __future__ import annotations

import logging
import os
from urllib.parse import quote

from app.connectors.base import Connector, Item

log = logging.getLogger(__name__)
PROD_GRAPH = "https://graph.microsoft.com/v1.0"


def _graph_base() -> str:
    # GRAPH_BASE_URL is honoured only under PE_TEST_MODE=1 (parity and local tests); anything else is production Graph.
    override = os.environ.get("GRAPH_BASE_URL")
    if override and os.environ.get("PE_TEST_MODE") == "1":
        log.warning("GRAPH_BASE_URL override active under PE_TEST_MODE=1: %s", override)
        return override
    return PROD_GRAPH


G = _graph_base()


class Outlook(Connector):
    name, label = "outlook", "Outlook / Exchange"

    def items(self, limit: int = 50):
        url = f"{G}/me/messages?$top={min(limit, 100)}&$select=id,webLink,lastModifiedDateTime"
        n = 0
        while url and n < limit:
            page = self._get_json(url)
            for m in page.get("value", []):
                if n >= limit:
                    return
                mime = self.http(f"{G}/me/messages/{m['id']}/$value", {"Authorization": f"Bearer {self.token}"})
                yield Item(m["id"], f"outlook-{n}-{m['id'][-12:]}.eml", mime,
                           m.get("webLink", ""), m.get("lastModifiedDateTime", ""))
                n += 1
            url = page.get("@odata.nextLink", "")


class OneDriveSharePoint(Connector):
    """opts: drive='me/drive' (OneDrive) or 'sites/{site-id}/drive' (SharePoint library); folder path optional."""
    name, label = "sharepoint", "SharePoint / OneDrive"

    def items(self, limit: int = 50):
        drive = self.opts.get("drive", "me/drive")
        folder = self.opts.get("folder", "").strip("/")
        root = f"{G}/{drive}/root:/{folder}:/children" if folder else f"{G}/{drive}/root/children"
        stack, n = [(root, "")], 0
        while stack and n < limit:
            url, prefix = stack.pop()
            while url and n < limit:
                page = self._get_json(url)
                for e in page.get("value", []):
                    if "folder" in e:
                        stack.append((f"{G}/{drive}/items/{e['id']}/children", f"{prefix}{e['name']}/"))
                    elif "file" in e and n < limit:
                        data = self.http(f"{G}/{drive}/items/{e['id']}/content", {"Authorization": f"Bearer {self.token}"})
                        perms = self._get_json(f"{G}/{drive}/items/{e['id']}/permissions").get("value", [])
                        yield Item(e["id"], f"{prefix}{e['name']}", data, e.get("webUrl", ""),
                                   e.get("eTag") or e.get("lastModifiedDateTime", ""), acl=_grantees(perms))
                        n += 1
                url = page.get("@odata.nextLink", "")


def _grantees(perms: list) -> tuple[str, ...]:
    """The people and groups a SharePoint item's permissions name: an email for a person, "group:{id}" for an Azure AD
    group. Sharing links name neither, so they are left out and fail closed."""
    emails = []
    for perm in perms:
        grants = [perm.get("grantedToV2"), perm.get("grantedTo"), *perm.get("grantedToIdentitiesV2", []),
                  *perm.get("grantedToIdentities", [])]
        for grant in grants:
            grant = grant or {}
            user = grant.get("user") or {}
            email = user.get("email") or user.get("userPrincipalName")
            group_id = (grant.get("group") or {}).get("id")
            if email:
                emails.append(email)
            elif group_id:  # an Azure AD group: matched against a key's groups, not a person
                emails.append(f"group:{group_id}")
    return tuple(emails)


class DirectoryGroups(Connector):
    """Groups a person is in, read from the directory (Graph /users/{email}/memberOf). Read-only; the result is stored
    on the person's API key so group grants on synced documents apply without a hand-kept list."""
    name, label = "directory-groups", "Directory groups"

    def member_of(self, email: str) -> tuple[str, ...]:
        url = f"{G}/users/{quote(email, safe='')}/memberOf?$select=id"
        ids: set[str] = set()
        while url:
            page = self._get_json(url)
            ids |= {str(g["id"]).lower() for g in page.get("value", []) if g.get("id")}
            url = page.get("@odata.nextLink", "")
        return tuple(sorted(ids))
