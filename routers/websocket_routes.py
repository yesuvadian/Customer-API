from fastapi import APIRouter, WebSocket
from services.websocket_service import connect, disconnect

router = APIRouter()


@router.websocket("/ws/{contact_id}")
async def websocket_endpoint(websocket: WebSocket, contact_id: str):
    await connect(websocket, contact_id)

    try:
        while True:
            await websocket.receive_text()
    except:
        disconnect(websocket, contact_id)