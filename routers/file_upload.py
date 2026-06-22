"""
Generic file upload endpoint.
POST /upload/file  — saves file to uploads/documents/, returns {file_url, file_name, file_size, mime_type}
"""
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from auth_utils import get_current_user

router = APIRouter(prefix="/upload", tags=["File Upload"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "documents")


@router.post("/file")
async def upload_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    ext = os.path.splitext(file.filename or "file")[1]
    stored_name = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(UPLOAD_DIR, stored_name)

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    with open(dest, "wb") as f:
        f.write(content)

    relative_url = f"uploads/documents/{stored_name}"
    return {
        "file_url":  relative_url,
        "file_name": file.filename,
        "file_size": len(content),
        "mime_type": file.content_type,
    }
