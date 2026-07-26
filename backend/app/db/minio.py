"""MinIO client singleton and bucket bootstrap."""

from __future__ import annotations

from functools import lru_cache

from minio import Minio

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_minio_client() -> Minio:
    """Return a singleton MinIO client."""
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_root_user,
        secret_key=s.minio_root_password.get_secret_value(),
        secure=False,
    )


def ensure_minio_bucket(bucket: str | None = None) -> str:
    """Create the bucket if missing and return its name."""
    s = get_settings()
    bucket_name = bucket or s.minio_bucket
    client = get_minio_client()
    if not client.bucket_exists(bucket_name):
        client.make_bucket(bucket_name)
        log.info("minio.bucket_created", bucket=bucket_name)
    return bucket_name


def close_minio() -> None:
    # minio-py holds no persistent connection requiring explicit close
    if get_minio_client.cache_info().currsize > 0:
        get_minio_client.cache_clear()
