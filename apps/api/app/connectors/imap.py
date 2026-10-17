"""Generic IMAP mailbox: any provider that speaks IMAP (Fastmail, Dovecot, Exchange IMAP, Gmail with an app
password). Each message is ingested as an .eml document through the normal email path. The token is the
mailbox password, sealed in the vault like every other token. Plain IMAP is allowed only to localhost."""
from __future__ import annotations

import hashlib
import imaplib

from app.connectors.base import Connector, ConnectorError, Item

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class Imap(Connector):
    """opts: host (required), user (required), port (default 993), mailbox (default INBOX),
    tls ('1' default; '0' only for localhost). Read-only: the mailbox is opened with EXAMINE."""
    name, label = "imap", "IMAP mailbox"

    def items(self, limit: int = 50):
        host, user = self.opts.get("host", ""), self.opts.get("user", "")
        if not host or not user:
            raise ConnectorError("opts.host and opts.user are required")
        tls = self.opts.get("tls", "1") != "0"
        if not tls and host not in LOCAL_HOSTS:
            raise ConnectorError("plain IMAP is allowed only to localhost")
        mailbox = self.opts.get("mailbox", "INBOX")
        try:
            cls = imaplib.IMAP4_SSL if tls else imaplib.IMAP4
            with cls(host, int(self.opts.get("port", "993")), timeout=30) as M:
                M.login(user, self.token)
                M.select(mailbox, readonly=True)
                _, data = M.uid("search", None, "ALL")
                for uid in data[0].split()[-max(limit, 1):]:
                    _, msg = M.uid("fetch", uid, "(RFC822)")
                    raw = msg[0][1]
                    uid_s = uid.decode()
                    yield Item(f"imap:{host}:{mailbox}:{uid_s}", f"imap-{uid_s}.eml", raw,
                               f"imap://{host}/{mailbox}/{uid_s}", hashlib.sha256(raw).hexdigest()[:16])
        except (imaplib.IMAP4.error, OSError) as e:
            raise ConnectorError(f"IMAP failed: {e}") from e
