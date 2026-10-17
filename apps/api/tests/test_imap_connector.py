"""Generic IMAP connector against a small IMAP4rev1 server written for these tests (stdlib only, localhost).
The real imaplib client talks to it, so login, EXAMINE, UID SEARCH and UID FETCH run over the wire."""
import shlex
import socketserver
import threading

import pytest

from app.connectors.base import ConnectorError
from app.connectors.imap import Imap

USER, PASSWORD = "ic@firm.test", "app-pass"


class _Handler(socketserver.StreamRequestHandler):
    def send(self, line: bytes) -> None:
        self.wfile.write(line + b"\r\n")

    def handle(self):
        srv = self.server
        self.send(b"* OK fake imap ready")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            tag, _, rest = line.decode().rstrip("\r\n").partition(" ")
            parts = shlex.split(rest)
            cmd = parts[0].upper()
            if cmd == "CAPABILITY":
                self.send(b"* CAPABILITY IMAP4rev1")
                self.send(f"{tag} OK done".encode())
            elif cmd == "LOGIN":
                if (parts[1], parts[2]) == (USER, PASSWORD):
                    self.send(f"{tag} OK logged in".encode())
                else:
                    self.send(f"{tag} NO bad credentials".encode())
            elif cmd in ("SELECT", "EXAMINE"):
                self.send(f"* {len(srv.messages)} EXISTS".encode())
                self.send(f"{tag} OK [READ-ONLY] {cmd} done".encode())
            elif cmd == "UID" and parts[1].upper() == "SEARCH":
                uids = " ".join(str(u) for u in sorted(srv.messages))
                self.send(f"* SEARCH {uids}".encode())
                self.send(f"{tag} OK search done".encode())
            elif cmd == "UID" and parts[1].upper() == "FETCH":
                uid = int(parts[2])
                raw = srv.messages[uid]
                self.wfile.write(f"* 1 FETCH (UID {uid} RFC822 {{{len(raw)}}}\r\n".encode() + raw + b")\r\n")
                self.send(f"{tag} OK fetch done".encode())
            elif cmd == "LOGOUT":
                self.send(b"* BYE bye")
                self.send(f"{tag} OK logout done".encode())
                return
            else:
                self.send(f"{tag} BAD unknown command".encode())


@pytest.fixture
def imap_server():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    srv.allow_reuse_address = True
    srv.messages = {
        1: b"From: ceo@acme.test\r\nSubject: Q3 numbers\r\n\r\nRevenue was 1,234 in Q3.\r\n",
        2: b"From: cfo@acme.test\r\nSubject: Covenant\r\n\r\nLeverage 2.9x.\r\n",
    }
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _conn(srv, password=PASSWORD, **extra):
    port = srv.server_address[1]
    return Imap(password, host="127.0.0.1", port=str(port), user=USER, tls="0", **extra)


def test_fetches_each_message_as_eml_with_source(imap_server):
    items = list(_conn(imap_server).items())
    assert [i.name for i in items] == ["imap-1.eml", "imap-2.eml"]
    assert items[0].data.startswith(b"From: ceo@acme.test")
    assert items[0].url == "imap://127.0.0.1/INBOX/1"
    assert items[0].external_id.endswith(":INBOX:1")


def test_limit_takes_newest_and_unchanged_mail_keeps_version(imap_server):
    (only,) = list(_conn(imap_server).items(limit=1))
    assert only.name == "imap-2.eml"
    first = list(_conn(imap_server).items())
    again = list(_conn(imap_server).items())
    assert [i.version for i in first] == [i.version for i in again]


def test_bad_password_is_connector_error(imap_server):
    with pytest.raises(ConnectorError, match="IMAP failed"):
        list(_conn(imap_server, password="wrong").items())


def test_plain_imap_refused_off_localhost_and_missing_opts():
    with pytest.raises(ConnectorError, match="localhost"):
        list(Imap("pw", host="mail.example.com", user=USER, tls="0").items())
    with pytest.raises(ConnectorError, match="required"):
        list(Imap("pw", user=USER).items())
