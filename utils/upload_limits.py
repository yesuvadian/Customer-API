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

import config

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 5))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024

# Fallback extension used when the sniffed MIME type isn't in the map but the
# file otherwise passed validation (kept out of ALLOWED_UPLOAD_TYPES lookups).
_MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "text/csv": ".csv",
}


def safe_extension_for_mime(mime: str, default: str = ".bin") -> str:
    """Map a sniffed MIME type to a safe file extension for storage.

    Never trust `file.filename`'s extension for the extension that gets
    written to disk — derive it from the detected content instead.
    """
    return _MIME_TO_EXT.get(mime, default)


def detect_mime(data: bytes, filename: str | None = None) -> str:
    """Sniff the real MIME type of `data` from its content (not the
    client-supplied Content-Type header). Callers that need the detected
    type (e.g. to pick a safe extension when writing to disk) should use
    this instead of re-implementing the magic/mimetypes fallback.
    """
    import magic
    import mimetypes

    try:
        return magic.from_buffer(data, mime=True)
    except Exception:
        guessed, _ = mimetypes.guess_type(filename or "")
        return guessed or "application/octet-stream"


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


async def read_and_validate_upload(
    file: UploadFile, category: str | tuple[str, ...] | list[str], max_mb: int | None = None
) -> bytes:
    """Stream-cap by size, then sniff real content and enforce the category's
    allow-list. Raises HTTPException(400) for a dangerous/unsupported type,
    413 for oversized. Use this instead of `.read()`/`read_upload_capped`
    for every endpoint that accepts user-facing file uploads.

    `category` is normally one key of `config.ALLOWED_UPLOAD_TYPES` (e.g.
    "document", "image", "spreadsheet"). Pass a tuple/list of keys for an
    endpoint that legitimately accepts more than one category (e.g. a report
    importer that takes either a PDF or an Excel file) — the allow-lists are
    merged.
    """
    max_bytes = (max_mb * 1024 * 1024) if max_mb is not None else MAX_UPLOAD_BYTES
    limit_mb = max_mb if max_mb is not None else MAX_UPLOAD_MB

    # 1. Fast-path reject dangerous extensions before reading a single byte.
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext in config.DANGEROUS_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' is not allowed for security reasons.",
        )

    # 2. Fast-path reject by known size (Starlette's UploadFile.size is
    # populated by the multipart parser before the handler runs) before
    # re-reading the body.
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {limit_mb} MB upload limit",
        )

    # 3. Bounded chunked read (same abort logic as read_upload_capped).
    data = await read_upload_capped(file, max_mb=max_mb)

    # 4. Sniff real content type and enforce the category allow-list.
    detected = detect_mime(data, filename)

    categories = (category,) if isinstance(category, str) else tuple(category)
    allowed_map: dict[str, set[str]] = {}
    for cat in categories:
        allowed_map.update(config.ALLOWED_UPLOAD_TYPES.get(cat, {}))
    allowed_exts = {e for exts in allowed_map.values() for e in exts}

    # Accept only when the sniffed MIME is one this category permits AND the
    # filename extension matches what that MIME is allowed to carry (the
    # table already maps e.g. application/zip -> {".xlsx"} for the common
    # "xlsx sniffs as zip" case, so no separate extension-only fallback is
    # needed here).
    if not (detected in allowed_map and ext in allowed_map[detected]):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(allowed_exts))}",
        )

    return data
