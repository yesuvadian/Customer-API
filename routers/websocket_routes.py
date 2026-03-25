from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from services.websocket_service import connect, disconnect
from services.zoho_contact_service import ZohoContactService

router = APIRouter()
contact_service = ZohoContactService()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    email: str = Query(...)   # ✅ client sends email
):
    try:
        # 🔁 convert email → customer_id
        contact = contact_service.get_contact_id_by_email(email)
        customer_id = str(contact.get("contact_id"))

        if not customer_id:
            await websocket.close()
            return

    except Exception as e:
        print("❌ Failed to resolve email:", e)
        await websocket.close()
        return

    # ✅ use ONLY customer_id internally
    await connect(websocket, customer_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        disconnect(websocket, customer_id)