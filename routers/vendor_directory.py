import os
import httpx
from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/vendor-directory", tags=["Vendor Directory"])

VENDOR_APP_URL = os.getenv("VENDOR_APP_URL", "http://127.0.0.1:8001")
INTERNAL_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")


@router.get("/vendors", summary="Fetch all vendors from supplier portal")
async def get_vendors():
    """
    Calls the supplier-side /internal/vendors endpoint
    and returns the vendor list to the customer portal.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{VENDOR_APP_URL}/internal/vendors",
                headers={
                    "secret": INTERNAL_SECRET,
                    "Content-Type": "application/json",
                },
            )

        if response.status_code == 200:
            return {
                "success": True,
                "count": len(response.json()),
                "vendors": response.json(),
            }
        elif response.status_code == 403:
            raise HTTPException(
                status_code=403,
                detail="Access denied: internal secret mismatch.",
            )
        else:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Supplier API error: {response.text}",
            )

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot reach supplier API at {VENDOR_APP_URL}. Is it running?",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Supplier API timed out.",
        )


@router.get("/vendors/ping", summary="Check supplier API connectivity")
async def ping_supplier():
    """
    Quick health check — verifies the supplier API is reachable
    and the secret is valid.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{VENDOR_APP_URL}/internal/vendors",
                headers={"secret": INTERNAL_SECRET},
            )
        return {
            "supplier_url": VENDOR_APP_URL,
            "status_code": response.status_code,
            "reachable": True,
            "secret_valid": response.status_code == 200,
        }
    except Exception as e:
        return {
            "supplier_url": VENDOR_APP_URL,
            "reachable": False,
            "error": str(e),
        }
@router.get("/vendors/{vendor_id}/documents", summary="Fetch all documents for a vendor")
async def get_vendor_documents(vendor_id: str):
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{VENDOR_APP_URL}/internal/vendors/{vendor_id}/documents",
                headers={"secret": INTERNAL_SECRET},
            )
        if response.status_code == 200:
            return response.json()
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach supplier API.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Supplier API timed out.")


from fastapi import Query
from fastapi.responses import StreamingResponse

@router.get(
    "/vendors/{vendor_id}/documents/{doc_type}/{doc_id}/download",
)
async def download_vendor_document(
    vendor_id: str,
    doc_type: str,
    doc_id: str,
    view: bool = Query(False)   # ← NEW
):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{VENDOR_APP_URL}/internal/vendors/{vendor_id}/documents/{doc_type}/{doc_id}/download",
                headers={"secret": INTERNAL_SECRET},
            )

        if response.status_code == 200:
            ct = response.headers.get(
                "content-type",
                "application/octet-stream"
            )

            filename = "document"
            cd_header = response.headers.get("content-disposition")
            if cd_header and "filename=" in cd_header:
                filename = cd_header.split("filename=")[-1]

            # 🔥 key fix
            disposition = "inline" if view else "attachment"

            return StreamingResponse(
                iter([response.content]),
                media_type=ct,
                headers={
                    "Content-Disposition":
                        f'{disposition}; filename={filename}'
                },
            )

        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Cannot reach supplier API."
        )
    
@router.get("/vendors/{vendor_id}/documents/download-all")
async def download_all_vendor_documents(vendor_id: str):
    from fastapi.responses import StreamingResponse
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{VENDOR_APP_URL}/internal/vendors/{vendor_id}/documents/download-all",
                headers={"secret": INTERNAL_SECRET},
            )
        if response.status_code == 200:
            return StreamingResponse(
                iter([response.content]),
                media_type="application/zip",
                headers={"Content-Disposition": response.headers.get("content-disposition", f'attachment; filename="vendor_docs.zip"')},
            )
        raise HTTPException(status_code=response.status_code, detail=response.text)
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Cannot reach supplier API.")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Supplier API timed out.")