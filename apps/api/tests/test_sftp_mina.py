"""SFTP data room against Apache MINA SSHD (github.com/apache/mina-sshd), run from its jars through
tests/mocks/sftp/SftpMock.java. Skipped unless SSHD_CLASSPATH names a text file holding the MINA jar classpath
(see docs/MOCKS.md) and java and javac are on PATH. The host key is pinned: the test reads it from the server
the first time, then checks that the connector refuses any other key."""
import base64
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import paramiko
import pytest

from app.connectors.base import ConnectorError
from app.connectors.sftp import SftpSource

CP_FILE = os.environ.get("SSHD_CLASSPATH", "")
pytestmark = pytest.mark.skipif(
    not (CP_FILE and Path(CP_FILE).is_file() and shutil.which("java") and shutil.which("javac")),
    reason="MINA SSHD classpath or JDK not available")
SRC = Path(__file__).parent / "mocks" / "sftp" / "SftpMock.java"
USER, PASSWORD = "dataroom", "room-pass"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def sftp_server(tmp_path_factory):
    base = tmp_path_factory.mktemp("sftp")
    cp = Path(CP_FILE).read_text().strip()
    out = base / "classes"
    out.mkdir()
    subprocess.run(["javac", "-d", str(out), "-cp", cp, str(SRC)], check=True, capture_output=True)
    root = base / "data"
    (root / "deal" / "finance").mkdir(parents=True)
    (root / "deal" / "cim.csv").write_text("metric,value\nrevenue,1234\n")
    (root / "deal" / "finance" / "model.csv").write_text("metric,value\nebitda,300\n")
    port = _free_port()
    proc = subprocess.Popen(["java", "-cp", f"{out}:{cp}", "SftpMock", str(port), str(root), USER, PASSWORD],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.stdout.readline().startswith("READY"):
            break
    else:
        proc.kill()
        pytest.fail("SFTP mock did not start")
    yield {"port": port}
    proc.terminate()
    proc.wait(timeout=10)


def _server_host_key(port: int) -> str:
    t = paramiko.Transport(("127.0.0.1", port))
    t.connect()
    key = t.get_remote_server_key()
    t.close()
    return f"{key.get_name()} {base64.b64encode(key.asbytes()).decode()}"


def _source(port: int, **over) -> SftpSource:
    opts = {"host": "127.0.0.1", "port": str(port), "username": USER, "path": "/deal",
            "host_key": _server_host_key(port), **over}
    return SftpSource(PASSWORD, **opts)


def test_tree_is_read_recursively_with_sftp_links(sftp_server):
    items = {i.name: i for i in _source(sftp_server["port"]).items()}
    assert sorted(items) == ["cim.csv", "finance/model.csv"]
    assert items["cim.csv"].data == b"metric,value\nrevenue,1234\n"
    assert items["cim.csv"].url == "sftp://127.0.0.1/deal/cim.csv"
    assert items["cim.csv"].version  # mtime and size


def test_unpinned_or_wrong_host_key_is_refused(sftp_server):
    other = paramiko.RSAKey.generate(1024)
    wrong = f"ssh-rsa {base64.b64encode(other.asbytes()).decode()}"
    with pytest.raises(ConnectorError, match="SFTP connect failed"):
        list(_source(sftp_server["port"], host_key=wrong).items())


def test_bad_password_and_missing_options(sftp_server):
    with pytest.raises(ConnectorError, match="SFTP connect failed"):
        list(SftpSource("wrong", host="127.0.0.1", port=str(sftp_server["port"]), username=USER, host_key=_server_host_key(sftp_server["port"])).items())
    with pytest.raises(ConnectorError, match="host and opts.username"):
        list(SftpSource("x").items())
