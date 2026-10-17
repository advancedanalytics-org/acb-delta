"""Storage service adapter for MinIO (Phase 1), vStorage (Phase 2), or local fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(
        self,
        endpoint_url: str = "http://localhost:9000",
        bucket: str = "documents",
        access_key: str = "acb",
        secret_key: str = "acb",
        local_dir: str = "/tmp/acb_delta/storage",
    ) -> None:
        self.endpoint_url = endpoint_url
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.local_dir = Path(local_dir)
        self.local_dir.mkdir(parents=True, exist_ok=True)

    def _get_s3_client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name="us-east-1",
        )

    def upload_file(
        self,
        content: bytes,
        key: str,
        content_type: str = "application/pdf",
    ) -> str:
        """Upload file content to S3-compatible storage or fallback to local directory."""
        try:
            s3 = self._get_s3_client()
            # Ensure bucket exists
            try:
                s3.head_bucket(Bucket=self.bucket)
            except ClientError:
                s3.create_bucket(Bucket=self.bucket)

            s3.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
            return f"{self.endpoint_url}/{self.bucket}/{key}"
        except (BotoCoreError, ClientError, Exception) as exc:
            logger.warning(
                "S3 upload failed (%s); storing file locally in %s: %s",
                self.endpoint_url,
                self.local_dir,
                exc,
            )
            local_path = self.local_dir / key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)
            return f"/storage/{key}"
