"""
Razorpay billing — trial-to-paid conversion.

Public (no auth required):
  GET  /billing/plans          — list plans (also accessible with payment_token)
  POST /billing/webhook        — Razorpay webhook (payment.captured / payment_link.paid)

Authenticated OR payment_token:
  POST /billing/create-order   — create Razorpay order (in-app checkout)
  POST /billing/verify         — verify signature → activate org

Authenticated only:
  GET  /billing/status         — current subscription status for the org
"""

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

import razorpay
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_utils import get_current_user, decode_access_token
from database import get_db
from models import BillingOrder, Organization, Plan
from services.billing_invoice_pdf_service import generate_invoice_pdf

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

router = APIRouter(prefix="/billing", tags=["Billing"])


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────

def _rzp() -> razorpay.Client:
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def _activate_org(org: Organization, order: BillingOrder, db: Session) -> None:
    now = datetime.now(timezone.utc)
    org.is_trial = False
    org.trial_status = "converted"
    org.subscription_start_date = now
    org.subscription_end_date = now + timedelta(days=order.duration_days)
    if order.plan_id:
        org.plan_id = order.plan_id
    org.onboarding_complete = True
    org.onboarding_completed_at = now
    db.commit()


def _resolve_org_from_request(request: Request, db: Session) -> Organization:
    """
    Resolve org from either:
      - Normal Bearer access token (authenticated user)
      - Short-lived payment_token (locked-out trial-expired user)
    """
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth_header.split(" ", 1)[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # payment_token carries org_id directly; access token carries user sub
    if payload.get("scope") == "billing":
        org_id = payload.get("org_id")
        if not org_id:
            raise HTTPException(status_code=401, detail="Invalid payment token")
        org = db.query(Organization).filter_by(id=org_id).first()
    else:
        from models import User
        user = db.query(User).filter_by(id=payload.get("sub")).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        org = db.query(Organization).filter_by(id=user.organization_id).first()

    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return org


# ──────────────────────────────────────────────────────────────────────────
# Schemas
# ──────────────────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    plan_id: str


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/plans  — public-ish (no auth needed)
# ──────────────────────────────────────────────────────────────────────────

@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    plans = db.query(Plan).filter(
        Plan.isactive == True,
        Plan.price_paise != None,
        Plan.billing_cycle != None,
    ).order_by(Plan.price_paise).all()

    return [
        {
            "id": str(p.id),
            "name": p.planname,
            "description": p.plan_description,
            "billing_cycle": p.billing_cycle,          # monthly | yearly
            "duration_days": p.duration_days,
            "amount_paise": p.price_paise,
            "amount_display": f"₹{p.price_paise // 100:,}",
            "amount_per_month": (
                f"₹{p.price_paise // 100 // 12:,}/mo"
                if p.billing_cycle == "yearly" else
                f"₹{p.price_paise // 100:,}/mo"
            ),
        }
        for p in plans
    ]


# ──────────────────────────────────────────────────────────────────────────
# POST /billing/create-order  — auth token OR payment_token
# ──────────────────────────────────────────────────────────────────────────

@router.post("/create-order")
async def create_order(
    payload: CreateOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    org = _resolve_org_from_request(request, db)

    plan = db.query(Plan).filter_by(id=payload.plan_id, isactive=True).first()
    if not plan or not plan.price_paise:
        raise HTTPException(status_code=404, detail="Plan not found or has no price")

    client = _rzp()
    rz_order = client.order.create({
        "amount": plan.price_paise,
        "currency": "INR",
        "receipt": f"org_{str(org.id)[:8]}",
        "notes": {
            "org_id": str(org.id),
            "org_name": org.name,
            "plan_id": str(plan.id),
            "plan_name": plan.planname,
        },
    })

    order = BillingOrder(
        org_id=org.id,
        plan_id=plan.id,
        razorpay_order_id=rz_order["id"],
        amount=plan.price_paise,
        currency="INR",
        duration_days=plan.duration_days or 365,
        status="pending",
    )
    db.add(order)
    db.commit()

    return {
        "razorpay_key_id": RAZORPAY_KEY_ID,
        "razorpay_order_id": rz_order["id"],
        "amount": plan.price_paise,
        "currency": "INR",
        "plan_name": plan.planname,
        "org_name": org.name,
        "contact_email": org.primary_email or "",
    }


# ──────────────────────────────────────────────────────────────────────────
# POST /billing/verify  — auth token OR payment_token
# ──────────────────────────────────────────────────────────────────────────

@router.post("/verify")
async def verify_payment(
    payload: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Verify Razorpay HMAC signature
    body = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    order = db.query(BillingOrder).filter_by(
        razorpay_order_id=payload.razorpay_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status == "paid":
        return {"message": "Already activated", "status": "paid"}

    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    db.flush()

    org = db.query(Organization).filter_by(id=order.org_id).first()
    _activate_org(org, order, db)

    return {"message": "Payment verified. Your account is now active.", "status": "paid"}


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/status  — authenticated only
# ──────────────────────────────────────────────────────────────────────────

@router.get("/status")
def billing_status(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    plan = db.query(Plan).filter_by(id=org.plan_id).first() if org.plan_id else None

    return {
        "is_trial": org.is_trial,
        "trial_status": org.trial_status,
        "trial_end_date": org.trial_end_date.isoformat() if org.trial_end_date else None,
        "subscription_end_date": org.subscription_end_date.isoformat() if org.subscription_end_date else None,
        "plan": {
            "id": str(plan.id),
            "name": plan.planname,
            "billing_cycle": plan.billing_cycle,
        } if plan else None,
    }


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/orders  — payment history for the org
# ──────────────────────────────────────────────────────────────────────────

@router.get("/orders")
def billing_orders(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    orders = (
        db.query(BillingOrder)
        .filter_by(org_id=current_user.organization_id)
        .order_by(BillingOrder.created_at.desc())
        .all()
    )
    result = []
    for o in orders:
        plan = db.query(Plan).filter_by(id=o.plan_id).first() if o.plan_id else None
        result.append({
            "id": str(o.id),
            "plan_name": plan.planname if plan else None,
            "billing_cycle": plan.billing_cycle if plan else None,
            "amount_paise": o.amount,
            "currency": o.currency,
            "status": o.status,
            "razorpay_payment_id": o.razorpay_payment_id,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        })
    return result


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/orders/{order_id}/invoice  — HTML invoice (browser prints as PDF)
# ──────────────────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/invoice")
def billing_invoice(
    order_id: str,
    request: Request,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    # Accept auth from Bearer header OR ?token= query param (for direct browser download)
    from models import User
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header.split(" ", 1)[1]
    if not raw_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(raw_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter_by(id=payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    order = db.query(BillingOrder).filter_by(id=order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if str(order.org_id) != str(user.organization_id):
        raise HTTPException(status_code=403, detail="Access denied")
    if order.status != "paid":
        raise HTTPException(status_code=400, detail="Invoice only available for paid orders")

    org = db.query(Organization).filter_by(id=user.organization_id).first()
    plan = db.query(Plan).filter_by(id=order.plan_id).first() if order.plan_id else None

    invoice_no = f"INV-{str(order.id)[:8].upper()}"
    paid_date = order.paid_at or order.created_at

    pdf_bytes = generate_invoice_pdf(
        invoice_no=invoice_no,
        org_name=org.name if org else "—",
        org_email=org.primary_email or "" if org else "",
        plan_name=plan.planname if plan else "Subscription",
        billing_cycle=plan.billing_cycle or "" if plan else "",
        amount_paise=order.amount or 0,
        paid_date=paid_date,
        razorpay_payment_id=order.razorpay_payment_id or "",
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice_no}.pdf"'},
    )


# ──────────────────────────────────────────────────────────────────────────
# POST /billing/webhook  — PUBLIC, called by Razorpay
# ──────────────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body_bytes = await request.body()

    if RAZORPAY_WEBHOOK_SECRET:
        sig = request.headers.get("x-razorpay-signature", "")
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode(),
            body_bytes,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=400, detail="Webhook signature invalid")

    event = json.loads(body_bytes)
    event_type = event.get("event")
    print(f"[BILLING-WEBHOOK] event={event_type}")

    rz_order_id = None
    rz_payment_id = None

    if event_type == "payment.captured":
        payment = event["payload"]["payment"]["entity"]
        rz_order_id = payment.get("order_id")
        rz_payment_id = payment.get("id")

    elif event_type == "payment_link.paid":
        payment = event["payload"]["payment"]["entity"]
        rz_payment_id = payment.get("id")
        rz_order_id = payment.get("order_id")
        # Also try to match via payment_link_id
        link_id = event["payload"].get("payment_link", {}).get("entity", {}).get("id")
        if link_id and not rz_order_id:
            order = db.query(BillingOrder).filter_by(
                razorpay_payment_link_id=link_id
            ).first()
            if order and order.status != "paid":
                order.razorpay_payment_id = rz_payment_id
                order.status = "paid"
                order.paid_at = datetime.now(timezone.utc)
                db.flush()
                org = db.query(Organization).filter_by(id=order.org_id).first()
                if org:
                    _activate_org(org, order, db)
                    print(f"[BILLING-WEBHOOK] Org {org.name} activated via payment_link.paid")
            return {"status": "ok"}

    if rz_order_id:
        order = db.query(BillingOrder).filter_by(razorpay_order_id=rz_order_id).first()
        if order and order.status != "paid":
            order.razorpay_payment_id = rz_payment_id
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            db.flush()
            org = db.query(Organization).filter_by(id=order.org_id).first()
            if org:
                _activate_org(org, order, db)
                print(f"[BILLING-WEBHOOK] Org {org.name} activated via {event_type}")

    return {"status": "ok"}
