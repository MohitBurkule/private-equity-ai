"""S3 source against moto (github.com/getmoto/moto), an open-source AWS mock run in-process as an HTTP server
on localhost. Objects are written with boto3 over the same endpoint, then read back through the connector."""
import socket

import boto3
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.connectors.base import ConnectorError
from app.connectors.s3 import S3Source
from app.main import app
from tests.helpers import new_tenant

moto_server = pytest.importorskip("moto.server")
BUCKET = "dataroom-atlas"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def s3_endpoint():
    port = _free_port()
    server = moto_server.ThreadedMotoServer(ip_address="127.0.0.1", port=port)
    server.start()
    endpoint = f"http://127.0.0.1:{port}"
    client = boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                          aws_access_key_id="AKIATEST", aws_secret_access_key="secret")
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key="deal/cim.csv", Body=b"metric,value\nrevenue,1234\n")
    client.put_object(Bucket=BUCKET, Key="deal/finance/model.csv", Body=b"metric,value\nebitda,300\n")
    client.put_object(Bucket=BUCKET, Key="other/notes.txt", Body=b"not this deal")
    yield endpoint
    server.stop()


def test_objects_under_prefix_become_documents_with_links(s3_endpoint):
    items = list(S3Source("AKIATEST:secret", bucket=BUCKET, prefix="deal/", endpoint=s3_endpoint).items())
    assert sorted(i.name for i in items) == ["cim.csv", "finance/model.csv"]
    cim = next(i for i in items if i.name == "cim.csv")
    assert cim.data.startswith(b"metric,value")
    assert cim.url == f"{s3_endpoint}/{BUCKET}/deal/cim.csv"
    assert cim.version  # ETag, so unchanged objects are skipped on re-sync


def test_limit_and_refusals(s3_endpoint):
    assert len(list(S3Source("AKIATEST:secret", bucket=BUCKET, endpoint=s3_endpoint).items(limit=1))) == 1
    with pytest.raises(ConnectorError, match="ACCESS_KEY_ID"):
        list(S3Source("nosecret", bucket=BUCKET, endpoint=s3_endpoint).items())
    with pytest.raises(ConnectorError, match="https"):
        list(S3Source("a:b", bucket=BUCKET, endpoint="http://files.example.com").items())
    with pytest.raises(ConnectorError, match="bucket"):
        list(S3Source("a:b").items())


def test_sync_endpoint_ingests_s3_objects_once(s3_endpoint, monkeypatch):
    monkeypatch.setattr(m, "CONNECTOR_HTTP", None)
    c = TestClient(app)
    h = new_tenant(c, "s3-sync")
    body = {"token": "AKIATEST:secret", "deal": None, "limit": 50,
            "options": {"bucket": BUCKET, "prefix": "deal/", "endpoint": s3_endpoint}}
    r = c.post("/connectors/s3/sync", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert len(r.json()["ingested"]) == 2
    assert c.post("/connectors/s3/sync", json=body, headers=h).json()["unchanged"] == 2
