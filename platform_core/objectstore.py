"""S3-compatible object store (MinIO in dev): large raw payloads, documents, cold tier."""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache
from urllib.parse import urlparse

from minio import Minio

from platform_core.config import get_settings

RAW_BUCKET = "cortex-raw"


@lru_cache
def client() -> Minio:
    s = get_settings()
    u = urlparse(s.object_store)
    return Minio(
        u.netloc, access_key=s.object_store_access_key, secret_key=s.object_store_secret_key, secure=u.scheme == "https"
    )


async def put_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    def _put() -> None:
        client().put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)

    await asyncio.to_thread(_put)
    return f"s3://{bucket}/{key}"


async def get_bytes(bucket: str, key: str) -> bytes:
    def _get() -> bytes:
        r = client().get_object(bucket, key)
        try:
            return r.read()
        finally:
            r.close()
            r.release_conn()

    return await asyncio.to_thread(_get)
