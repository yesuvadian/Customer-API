from fastapi import APIRouter, HTTPException
from typing import List

from services.erp_service import ERPService

router = APIRouter(
    prefix="/erp",
    tags=["ERP PostgreSQL"]
)


# ---------- Helpers -----------

def success(message, data=None):
    return {"status": "success", "message": message, "data": data}


def error(message, code):
    raise HTTPException(code, detail=message)


# ---------- Startup -----------

@router.on_event("startup")
async def startup():
    await ERPService.init_pool()


# ---------- Health -----------

@router.get("/health")
async def health_postgres():
    return await ERPService.health()


# ---------- INSERT -----------

@router.post("/insert")
async def data_insert(payload: List[dict]):
    try:
        if not payload:
            error("Payload cannot be empty", 400)

        result = await ERPService.insert_data(payload)
        return success("Inserted successfully", result)

    except Exception as e:
        raise HTTPException(400, str(e))


# ---------- UPDATE -----------

@router.put("/update")
async def data_update(payload: List[dict]):
    try:
        if not payload:
            error("Payload cannot be empty", 400)

        result = await ERPService.update_data(payload)
        return success("Data updated successfully", result)

    except Exception as e:
        raise HTTPException(400, str(e))
