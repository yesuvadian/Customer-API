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
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from bson import Binary
from auth_utils import get_current_user
from services.mongo_service import MongoService

router = APIRouter(
    prefix="/mongo",
    tags=["MongoDB"],
    dependencies=[Depends(get_current_user)]
)

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), folder_name: str = None):
    """
    Upload a file and insert into MongoDB with Binary content.
    """
    try:
        # Read file content as bytes
        content = await file.read()
        mongo_binary = Binary(content)  # convert bytes to BSON Binary

        # Prepare payload for insertion
        mongo_payload = {
            "filename": file.filename,
            "filetype": file.content_type,
            "fileContent": mongo_binary,  # important
            "foldername": folder_name
        }

        # Insert using existing MongoService method
        result = MongoService.insert(mongo_payload)
        
        return {"message": "File uploaded and inserted successfully", "document": result}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
