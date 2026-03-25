from fastapi import WebSocket

# key = customer_id
active_connections: dict[str, list[WebSocket]] = {}


# -------------------------------------------------
# 🔌 Connect (store under customer_id)
# -------------------------------------------------
async def connect(websocket: WebSocket, customer_id: str):
    await websocket.accept()

    customer_id = str(customer_id).strip()

    if customer_id not in active_connections:
        active_connections[customer_id] = []

    if websocket not in active_connections[customer_id]:
        active_connections[customer_id].append(websocket)

    print("✅ WS CONNECTED:", customer_id)


# -------------------------------------------------
# ❌ Disconnect
# -------------------------------------------------
def disconnect(websocket: WebSocket, customer_id: str):
    customer_id = str(customer_id).strip()

    if customer_id in active_connections:
        if websocket in active_connections[customer_id]:
            active_connections[customer_id].remove(websocket)

        # cleanup empty list
        if not active_connections[customer_id]:
            del active_connections[customer_id]

    print("❌ WS DISCONNECTED:", customer_id)


# -------------------------------------------------
# 📡 Send Message (SAFE + CLEANUP)
# -------------------------------------------------
async def send_to_user(customer_id: str, data: dict):
    customer_id = str(customer_id).strip()

    if customer_id not in active_connections:
        print("⚠️ No active WS for:", customer_id)
        return

    dead_connections = []

    # iterate safely
    for ws in active_connections[customer_id][:]:
        try:
            await ws.send_json(data)
            print("📡 Sent WS:", customer_id, data)

        except Exception as e:
            print("❌ WS send failed:", e)
            dead_connections.append(ws)

    # cleanup dead sockets
    for ws in dead_connections:
        if ws in active_connections.get(customer_id, []):
            active_connections[customer_id].remove(ws)

    # remove key if empty
    if customer_id in active_connections and not active_connections[customer_id]:
        del active_connections[customer_id]