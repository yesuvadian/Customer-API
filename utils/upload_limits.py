"""
Shared upload-size guard for every router that accepts a file upload.

Reads the file in chunks and aborts as soon as MAX_UPLOAD_MB is crossed,
instead of buffering an unbounded upload into memory. One place to change
the limit or the read strategy for every endpoint that uses it — routers
should call read_upload_capped() rather than `await file.read()` directly.

Note this is an app-level guard only; also set client_max_body_size (nginx)
or the equivalent at the reverse proxy so an oversized request doesn't tie
up a worker thread just to reach this check.
"""
import os

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 5))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024


async def read_upload_capped(file: UploadFile, max_mb: int | None = None) -> bytes:
    """Read `file` fully, raising HTTP 413 the moment it exceeds the limit.

    `max_mb` overrides MAX_UPLOAD_MB for endpoints that need a different cap
    (e.g. a bulk-import route that legitimately expects larger files).
    """
    max_bytes = (max_mb * 1024 * 1024) if max_mb is not None else MAX_UPLOAD_BYTES
    limit_mb = max_mb if max_mb is not None else MAX_UPLOAD_MB

    chunks = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the {limit_mb} MB upload limit",
            )
    return bytes(chunks)
