from fastapi import WebSocket
from services.websocket_manager import connect, disconnect

@router.websocket("/ws/{contact_id}")
async def websocket_endpoint(websocket: WebSocket, contact_id: str):
    await connect(websocket, contact_id)

    try:
        while True:
            await websocket.receive_text()
    except:
        disconnect(websocket, contact_id)