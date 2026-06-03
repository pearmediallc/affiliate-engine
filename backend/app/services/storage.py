"""
S3 storage service — uploads generated images/videos to S3 for permanent persistence.
Falls back gracefully when AWS is not configured (dev / local mode).
"""
import os
import logging
import mimetypes
from ..config import settings

logger = logging.getLogger(__name__)


class StorageService:

    @staticmethod
    def _client():
        try:
            import boto3
            return boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
        except ImportError:
            return None

    @staticmethod
    def is_configured() -> bool:
        return bool(
            settings.aws_access_key_id
            and settings.aws_secret_access_key
            and settings.aws_s3_bucket
        )

    @staticmethod
    def upload_file(local_path: str, s3_key: str) -> str | None:
        """
        Upload a local file to S3.
        Returns the public URL, or None if S3 is not configured / upload fails.
        """
        if not StorageService.is_configured():
            return None

        client = StorageService._client()
        if not client:
            logger.warning("boto3 not installed — skipping S3 upload")
            return None

        try:
            content_type, _ = mimetypes.guess_type(local_path)
            content_type = content_type or "application/octet-stream"

            client.upload_file(
                local_path,
                settings.aws_s3_bucket,
                s3_key,
                ExtraArgs={"ContentType": content_type},
            )

            base = (
                settings.aws_s3_public_base_url.rstrip("/")
                if settings.aws_s3_public_base_url
                else f"https://{settings.aws_s3_bucket}.s3.{settings.aws_region}.amazonaws.com"
            )
            url = f"{base}/{s3_key}"
            logger.info(f"Uploaded {local_path} → {url}")
            return url

        except Exception as e:
            logger.error(f"S3 upload failed for {local_path}: {e}")
            return None

    @staticmethod
    def download_file(s3_key: str, local_path: str) -> bool:
        """Download an object from our S3 bucket to a local path.
        Returns True on success, False otherwise. Used by AutoEditor to
        recover shot videos from S3 when /tmp has been wiped (Render
        restart) — the bucket is private so unauth HTTP GET 403's."""
        if not StorageService.is_configured():
            return False
        client = StorageService._client()
        if not client:
            return False
        try:
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
            client.download_file(settings.aws_s3_bucket, s3_key, local_path)
            return True
        except Exception as e:
            logger.error(f"S3 download_file failed for {s3_key}: {e}")
            return False

    @staticmethod
    def parse_s3_key(url: str) -> str | None:
        """If `url` is a URL pointing at our configured bucket, return the
        object key. Otherwise None. Handles both virtual-hosted-style and
        path-style URLs."""
        if not url or not StorageService.is_configured():
            return None
        bucket = settings.aws_s3_bucket
        region = settings.aws_region or "us-east-1"
        # Virtual-hosted: https://<bucket>.s3.<region>.amazonaws.com/<key>
        prefix_vh = f"https://{bucket}.s3.{region}.amazonaws.com/"
        if url.startswith(prefix_vh):
            return url[len(prefix_vh):]
        # Virtual-hosted no region: https://<bucket>.s3.amazonaws.com/<key>
        prefix_vh_noreg = f"https://{bucket}.s3.amazonaws.com/"
        if url.startswith(prefix_vh_noreg):
            return url[len(prefix_vh_noreg):]
        # Path-style: https://s3.<region>.amazonaws.com/<bucket>/<key>
        prefix_ps = f"https://s3.{region}.amazonaws.com/{bucket}/"
        if url.startswith(prefix_ps):
            return url[len(prefix_ps):]
        return None

    @staticmethod
    def upload_bytes(data: bytes, s3_key: str, content_type: str = "application/octet-stream") -> str | None:
        """Upload raw bytes to S3. Returns public URL or None."""
        if not StorageService.is_configured():
            return None

        client = StorageService._client()
        if not client:
            return None

        try:
            client.put_object(
                Bucket=settings.aws_s3_bucket,
                Key=s3_key,
                Body=data,
                ContentType=content_type,
            )
            base = (
                settings.aws_s3_public_base_url.rstrip("/")
                if settings.aws_s3_public_base_url
                else f"https://{settings.aws_s3_bucket}.s3.{settings.aws_region}.amazonaws.com"
            )
            url = f"{base}/{s3_key}"
            logger.info(f"Uploaded bytes → {url}")
            return url
        except Exception as e:
            logger.error(f"S3 put_object failed for {s3_key}: {e}")
            return None
