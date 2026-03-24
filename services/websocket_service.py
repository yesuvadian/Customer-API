from fastapi import WebSocket

active_connections: dict[str, list[WebSocket]] = {}


# -------------------------------------------------
# 🔌 Connect (store under email + erp_id)
# -------------------------------------------------
async def connect(websocket: WebSocket, contact_id: str, erp_id: str = None):
    await websocket.accept()

    keys = [contact_id]

    if erp_id:
        keys.append(erp_id)

    for key in keys:
        if key not in active_connections:
            active_connections[key] = []

        # ✅ prevent duplicate connections
        if websocket not in active_connections[key]:
            active_connections[key].append(websocket)

    print("✅ WS CONNECTED:", keys)


# -------------------------------------------------
# ❌ Disconnect
# -------------------------------------------------
def disconnect(websocket: WebSocket, contact_id: str, erp_id: str = None):
    keys = [contact_id]

    if erp_id:
        keys.append(erp_id)

    for key in keys:
        if key in active_connections and websocket in active_connections[key]:
            active_connections[key].remove(websocket)

            # ✅ cleanup empty lists
            if not active_connections[key]:
                del active_connections[key]

    print("❌ WS DISCONNECTED:", keys)


# -------------------------------------------------
# 📡 Send Message (SAFE + CLEANUP)
# -------------------------------------------------
async def send_to_user(contact_id: str, data: dict):
    if contact_id not in active_connections:
        print("⚠️ No active WS for:", contact_id)
        return

    dead_connections = []

    # ✅ iterate over copy to avoid runtime issues
    for ws in active_connections[contact_id][:]:
        try:
            await ws.send_json(data)
            print("📡 Sent WS:", contact_id, data)

        except Exception as e:
            print("❌ WS send failed:", e)
            dead_connections.append(ws)

    # ✅ cleanup dead sockets
    for ws in dead_connections:
        if ws in active_connections.get(contact_id, []):
            active_connections[contact_id].remove(ws)

    # ✅ remove key if empty
    if contact_id in active_connections and not active_connections[contact_id]:
        del active_connections[contact_id]