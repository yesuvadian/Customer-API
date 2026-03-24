from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from services.websocket_service import connect, disconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    contact_id: str = Query(...),   # email
    erp_id: str = Query(None)       # optional
):
    await connect(websocket, contact_id, erp_id)

    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        disconnect(websocket, contact_id, erp_id)