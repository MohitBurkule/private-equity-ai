"""S3 and S3-compatible object stores (AWS, MinIO, Ceph). Every object under the prefix becomes one document,
named by its path under the prefix and cited by its object link. Version is the object's ETag, so an unchanged
object is skipped on re-sync. boto3 does the signing, so the injected Http is not used here.
Only https endpoints, or plain http to localhost for dev and mocks (moto, MinIO in compose)."""
from __future__ import annotations

from urllib.parse import quote, urlparse

from app.connectors.base import Connector, ConnectorError, Item

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


class S3Source(Connector):
    """opts: bucket (required), prefix (default ''), region (default us-east-1), endpoint (optional custom URL).
    Token is ACCESS_KEY_ID:SECRET_ACCESS_KEY, used once and never stored."""
    name, label = "s3", "S3 bucket"

    def items(self, limit: int = 50):
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError

        bucket = self.opts.get("bucket", "")
        if not bucket:
            raise ConnectorError("opts.bucket is required")
        prefix = self.opts.get("prefix", "")
        endpoint = self.opts.get("endpoint", "").rstrip("/")
        if endpoint:
            parsed = urlparse(endpoint)
            if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS or parsed.scheme not in ("http", "https"):
                raise ConnectorError("endpoint must be https, or http to localhost")
        key_id, _, secret = self.token.partition(":")
        if not secret:
            raise ConnectorError("token must be ACCESS_KEY_ID:SECRET_ACCESS_KEY")
        client = boto3.client("s3", endpoint_url=endpoint or None, region_name=self.opts.get("region", "us-east-1"),
                              aws_access_key_id=key_id, aws_secret_access_key=secret)
        n = 0
        try:
            for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if n >= limit:
                        return
                    if key.endswith("/"):
                        continue
                    data = client.get_object(Bucket=bucket, Key=key)["Body"].read()
                    url = f"{endpoint}/{bucket}/{quote(key)}" if endpoint else \
                        f"https://s3.console.aws.amazon.com/s3/object/{bucket}?prefix={quote(key)}"
                    yield Item(f"s3:{bucket}:{key}", key[len(prefix):].lstrip("/") or key, data, url,
                               obj.get("ETag", "").strip('"'))
                    n += 1
        except (BotoCoreError, ClientError) as e:
            raise ConnectorError(f"S3 failed: {e}") from e
