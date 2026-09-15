"""
Generic file upload endpoint.
POST /upload/file       — saves file to uploads/documents/, returns {file_url, file_name, file_size, mime_type}
GET  /upload/file/{name} — serves the file bytes back to the client
"""
import mimetypes
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from auth_utils import get_current_user
from utils.upload_limits import read_and_validate_upload, detect_mime, safe_extension_for_mime

router = APIRouter(prefix="/upload", tags=["File Upload"])

# Defaults to a local folder for single-instance/dev use. For a multi-instance
# deployment, set UPLOAD_DIR in .env to a network share or object-storage
# mount point shared by every instance — a file saved on one instance must
# be readable from the others, which a local path alone cannot guarantee.
UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.join(os.path.dirname(__file__), "..", "uploads", "documents"),
)


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    content = await read_and_validate_upload(file, category="document")
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    # Derive the stored extension from the detected content, never from the
    # client-supplied filename, to prevent extension spoofing on disk.
    detected_type = detect_mime(content, file.filename)
    ext = safe_extension_for_mime(detected_type)
    stored_name = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(UPLOAD_DIR, stored_name)

    with open(dest, "wb") as f:
        f.write(content)

    relative_url = f"uploads/documents/{stored_name}"
    return {
        "file_url":  relative_url,
        "file_name": file.filename,
        "file_size": len(content),
        "mime_type": detected_type,
    }


@router.get("/file/{file_name}")
async def serve_file(
    file_name: str,
    current_user=Depends(get_current_user),
):
    path = os.path.join(UPLOAD_DIR, file_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")

    with open(path, "rb") as f:
        content = f.read()

    mime, _ = mimetypes.guess_type(file_name)
    return Response(
        content=content,
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{file_name}"'},
    )
