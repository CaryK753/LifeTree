"""Blob storage port with MinIO and local content-addressed adapters."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.core.config import get_settings
from app.core.local_storage import prepare_local_storage


@dataclass(frozen=True, slots=True)
class StoredBlob:
    key: str
    size: int
    sha256: str
    content_type: str


@runtime_checkable
class BlobStore(Protocol):
    def prepare(self) -> None: ...

    def put_bytes(self, data: bytes, *, content_type: str) -> StoredBlob: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool: ...


def _blob_key(digest: str) -> str:
    return f"sha256/{digest[:2]}/{digest}.blob"


class LocalFileBlobStore:
    """Persist immutable blobs below the native LifeTree data directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, data: bytes, *, content_type: str) -> StoredBlob:
        digest = hashlib.sha256(data).hexdigest()
        stored = StoredBlob(
            key=_blob_key(digest),
            size=len(data),
            sha256=digest,
            content_type=content_type or "application/octet-stream",
        )
        path = self._path(stored.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._atomic_write(path, data)
        metadata = path.with_suffix(".json")
        if not metadata.exists():
            self._atomic_write(metadata, json.dumps(asdict(stored)).encode("utf-8"))
        return stored

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        path.unlink()
        path.with_suffix(".json").unlink(missing_ok=True)
        return True

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if (
            len(parts) != 3
            or parts[0] != "sha256"
            or len(parts[1]) != 2
            or len(parts[2]) != 69
            or not parts[2].endswith(".blob")
        ):
            raise ValueError("Invalid content-addressed blob key")
        digest = parts[2][:-5]
        if parts[1] != digest[:2] or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("Invalid content-addressed blob key")
        return self.root / parts[0] / parts[1] / parts[2]

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temp_path = Path(temporary.name)
        os.replace(temp_path, path)


class MinioBlobStore:
    def __init__(self, bucket: str | None = None) -> None:
        self.bucket = bucket

    def prepare(self) -> None:
        from app.db.minio import ensure_minio_bucket

        self.bucket = ensure_minio_bucket(self.bucket)

    def put_bytes(self, data: bytes, *, content_type: str) -> StoredBlob:
        from app.db.minio import get_minio_client

        self.prepare()
        digest = hashlib.sha256(data).hexdigest()
        key = _blob_key(digest)
        get_minio_client().put_object(
            bucket_name=self.bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type or "application/octet-stream",
        )
        return StoredBlob(key, len(data), digest, content_type or "application/octet-stream")

    def get_bytes(self, key: str) -> bytes:
        from app.db.minio import get_minio_client

        self.prepare()
        response = get_minio_client().get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def exists(self, key: str) -> bool:
        from app.db.minio import get_minio_client

        self.prepare()
        try:
            get_minio_client().stat_object(self.bucket, key)
        except Exception:  # noqa: BLE001
            return False
        return True

    def delete(self, key: str) -> bool:
        from app.db.minio import get_minio_client

        if not self.exists(key):
            return False
        get_minio_client().remove_object(self.bucket, key)
        return True


@lru_cache(maxsize=1)
def get_blob_store() -> BlobStore:
    settings = get_settings()
    if settings.lifetree_storage_mode == "local":
        paths = prepare_local_storage(settings.lifetree_data_dir)
        return LocalFileBlobStore(paths.objects)
    return MinioBlobStore(settings.minio_bucket)


def close_blob_store() -> None:
    get_blob_store.cache_clear()


__all__ = [
    "BlobStore",
    "LocalFileBlobStore",
    "MinioBlobStore",
    "StoredBlob",
    "close_blob_store",
    "get_blob_store",
]
