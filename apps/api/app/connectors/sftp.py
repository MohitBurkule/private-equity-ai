"""SFTP data rooms: every file under a remote directory (recursively) becomes one document, cited as sftp://host/path.
Host keys are verified against an `host_key` option (the server's public key, "ssh-ed25519 AAAA..."). Unknown or
changed keys are refused, never auto-accepted. Password auth; the token is the password, used once and never stored.
Version is mtime and size, so unchanged files are skipped on re-sync."""
from __future__ import annotations

import posixpath
from base64 import b64decode

import paramiko

from app.connectors.base import Connector, ConnectorError, Item


class SftpSource(Connector):
    """opts: host (required), host_key (required, "<type> <base64>"), username (required), port (default 22),
    path (remote directory, default '/')."""
    name, label = "sftp", "SFTP data room"

    def _connect(self) -> paramiko.SFTPClient:
        host, user = self.opts.get("host", ""), self.opts.get("username", "")
        port = int(self.opts.get("port", "22"))
        if not host or not user:
            raise ConnectorError("opts.host and opts.username are required")
        try:
            ktype, b64 = self.opts.get("host_key", "").split(" ", 1)
            key = paramiko.PKey.from_type_string(ktype, b64decode(b64))
        except ValueError as e:
            raise ConnectorError("opts.host_key must be '<key type> <base64 public key>'") from e
        client = paramiko.SSHClient()
        name = host if port == 22 else f"[{host}]:{port}"  # OpenSSH host-key naming for non-default ports
        client.get_host_keys().add(name, key.get_name(), key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(host, port=port, username=user, password=self.token, timeout=30,
                           look_for_keys=False, allow_agent=False)
        except (paramiko.SSHException, OSError) as e:
            raise ConnectorError(f"SFTP connect failed: {e}") from e
        return client.open_sftp()

    def items(self, limit: int = 50):
        sftp = self._connect()  # validates options first
        host = self.opts["host"]
        root = self.opts.get("path", "/") or "/"
        n = 0
        try:
            stack = [root]
            while stack:
                d = stack.pop()
                for attr in sorted(sftp.listdir_attr(d), key=lambda a: a.filename):
                    if n >= limit:
                        return
                    full = posixpath.join(d, attr.filename)
                    if attr.st_mode is not None and (attr.st_mode & 0o040000):
                        stack.append(full)
                        continue
                    with sftp.open(full, "rb") as f:
                        data = f.read()
                    rel = posixpath.relpath(full, root.rstrip("/") or "/")
                    yield Item(f"sftp:{host}:{full}", rel, data, f"sftp://{host}{full}",
                               f"{attr.st_mtime}-{attr.st_size}")
                    n += 1
        finally:
            sftp.get_channel().get_transport().close()
