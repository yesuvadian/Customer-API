from fastapi import APIRouter, Depends, HTTPException
from typing import List
from routers.totp import get_current_user
from services.erp_service import ERPService

router = APIRouter(
    prefix="/erp",
    tags=["ERP Database"],
    dependencies=[Depends(get_current_user)]
)

# ---------- Helpers -----------

def success(message, data=None):
    return {"status": "success", "message": message, "data": data}


def fail_unavailable():
    raise HTTPException(
        status_code=503,
        detail="ERP database unavailable. Try again later."
    )


# ---------- Health -----------

@router.get("/health")
async def health_postgres():
    # no connection attempt unless pool exists
    return await ERPService.health()

# ---------- INSERT -----------

@router.post("/insert")
async def data_insert(payload: List[dict]):
    if not payload:
        raise HTTPException(400, "Payload cannot be empty")

    # Try safe connection
    if not await ERPService.safe_init_pool():
        fail_unavailable()

    result = await ERPService.insert_data(payload)
    return success("Inserted successfully", result)


# ---------- UPDATE -----------

@router.put("/update")
async def data_update(payload: List[dict]):
    if not payload:
        raise HTTPException(400, "Payload cannot be empty")

    # Try safe connection
    if not await ERPService.safe_init_pool():
        fail_unavailable()

    result = await ERPService.update_data(payload)
    return success("Data updated successfully", result)

