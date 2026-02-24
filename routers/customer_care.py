import sys
import os
import html  # ✅ Import for escaping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.email_service import EmailService

router = APIRouter()
email_service = EmailService()

class ContactEmailRequest(BaseModel):
    from_email: str
    subject: str
    message: str

@router.post("/contact/send")
async def send_contact_email(payload: ContactEmailRequest):
    TO_EMAIL = "venkat@cogniwatt.com"

    # ✅ Escape all user-supplied values before embedding in HTML
    safe_from    = html.escape(payload.from_email)
    safe_subject = html.escape(payload.subject)
    safe_message = html.escape(payload.message)

    body_html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #004080;">New Message from Supplier Portal</h2>
        <table style="width:100%; border-collapse:collapse;">
            <tr>
                <td style="padding:8px; font-weight:bold; color:#333;">From:</td>
                <td style="padding:8px; color:#555;">{safe_from}</td>
            </tr>
            <tr style="background:#f9f9f9;">
                <td style="padding:8px; font-weight:bold; color:#333;">Subject:</td>
                <td style="padding:8px; color:#555;">{safe_subject}</td>
            </tr>
        </table>
        <hr style="margin:16px 0; border:none; border-top:1px solid #ddd;" />
        <h4 style="color:#004080;">Message:</h4>
        <p style="color:#444; line-height:1.6; white-space:pre-line;">{safe_message}</p>
        <hr style="margin:16px 0; border:none; border-top:1px solid #ddd;" />
        <small style="color:#999;">Sent via PowerXchange.ai Supplier Portal</small>
    </div>
    """

    try:
        email_service.send_email_starttls(
            to_email=TO_EMAIL,
            subject=f"[Supplier Portal] {safe_subject}",
            body_html=body_html,
        )
        return {"success": True, "message": "Email sent successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")