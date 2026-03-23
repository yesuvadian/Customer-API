from fastapi import WebSocket

active_connections: dict[str, list[WebSocket]] = {}


async def connect(websocket: WebSocket, contact_id: str):
    await websocket.accept()

    if contact_id not in active_connections:
        active_connections[contact_id] = []

    active_connections[contact_id].append(websocket)
    print("✅ WS CONNECTED:", contact_id)


def disconnect(websocket: WebSocket, contact_id: str):
    if contact_id in active_connections:
        active_connections[contact_id].remove(websocket)
        print("❌ WS DISCONNECTED:", contact_id)


async def send_to_user(contact_id: str, data: dict):
    if contact_id in active_connections:
        for ws in active_connections[contact_id]:
            try:
                await ws.send_json(data)
                print("📡 Sent WS:", data)
            except Exception as e:
                print("❌ WS send failed:", e)