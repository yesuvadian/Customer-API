from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from auth_utils import get_current_user
from services.mongo_service import MongoService

router = APIRouter(
    prefix="/mongo",
    tags=["MongoDB"],dependencies=[Depends(get_current_user)]
)


@router.get("/health")
def health():
    return MongoService.health_check()



@router.get("/")
def list_all():
    return MongoService.list_all()


@router.get("/{doc_id}")
def get(doc_id: str):
    try:
        return MongoService.get_one(doc_id)
    except Exception as e:
        raise HTTPException(404, str(e))


@router.post("/")
def insert(payload: dict):
    return MongoService.insert(payload)


@router.put("/{doc_id}")
def update(doc_id: str, payload: dict):
    try:
        return MongoService.update(doc_id, payload)
    except Exception as e:
        raise HTTPException(404, str(e))


@router.delete("/{doc_id}")
def delete(doc_id: str):
    try:
        return MongoService.delete(doc_id)
    except Exception as e:
        raise HTTPException(404, str(e))
