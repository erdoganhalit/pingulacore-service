from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import Settings, get_settings


class ObjectStorageService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.client = boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name=self.settings.s3_region,
            config=Config(signature_version="s3v4"),
        )

    def ensure_buckets(self) -> None:
        existing = {bucket["Name"] for bucket in self.client.list_buckets().get("Buckets", [])}
        for bucket in [
            self.settings.s3_catalog_bucket,
            self.settings.s3_generated_bucket,
            self.settings.s3_rendered_bucket,
        ]:
            if bucket not in existing:
                self.client.create_bucket(Bucket=bucket)

    def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def upload_file(self, *, bucket: str, key: str, path: Path, content_type: str) -> None:
        self.client.upload_file(
            str(path),
            bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def get_object(self, *, bucket: str, key: str) -> tuple[bytes, str | None]:
        obj: dict[str, Any] = self.client.get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
        return data, obj.get("ContentType")

    def list_objects(self, *, bucket: str, prefix: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
        if prefix:
            kwargs["Prefix"] = prefix
        items: list[dict[str, Any]] = []
        while True:
            resp: dict[str, Any] = self.client.list_objects_v2(**kwargs)
            for row in resp.get("Contents", []):
                items.append(
                    {
                        "key": str(row.get("Key") or ""),
                        "size": int(row.get("Size") or 0),
                        "last_modified": row.get("LastModified"),
                    }
                )
            if not resp.get("IsTruncated"):
                break
            kwargs["ContinuationToken"] = resp.get("NextContinuationToken")
        return items

    def object_exists(self, *, bucket: str, key: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))
            if status in {404, 400, 403}:
                return False
            raise

    def delete_object(self, *, bucket: str, key: str) -> bool:
        if not self.object_exists(bucket=bucket, key=key):
            return False
        self.client.delete_object(Bucket=bucket, Key=key)
        return True
