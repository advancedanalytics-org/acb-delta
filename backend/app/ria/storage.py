"""Immutable store for uploaded originals: S3-compatible (MinIO / vStorage) or local disk."""

from functools import lru_cache
from pathlib import Path

from app.config import get_settings


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():  # originals are immutable: never overwrite
            path.write_bytes(data)
        return f"file://{path}"

    def get(self, uri: str) -> bytes:
        return Path(uri.removeprefix("file://")).read_bytes()


class S3Storage:
    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{self.bucket}/{key}"

    def get(self, uri: str) -> bytes:
        bucket, key = uri.removeprefix("s3://").split("/", 1)
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()


@lru_cache
def get_storage() -> LocalStorage | S3Storage:
    settings = get_settings()
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.storage_local_dir)
