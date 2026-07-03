"""
BillingService — Razorpay Payment Link creation for trial-expired orgs.

Called when trial expires at login (first time only).
Razorpay sends the link directly to the org email via their built-in delivery.
"""

import os
from datetime import datetime, timezone

import razorpay
from sqlalchemy.orm import Session

from models import BillingOrder, Organization, Plan

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")


def _rzp() -> razorpay.Client:
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def send_payment_link(db: Session, org: Organization) -> None:
    """
    Create a Razorpay Payment Link for the org and let Razorpay send it
    to the org's primary email. Skips if a pending link already exists.
    """
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        print("[BILLING] Razorpay keys not configured — skipping payment link")
        return

    # Don't send duplicate links
    existing = db.query(BillingOrder).filter(
        BillingOrder.org_id == org.id,
        BillingOrder.razorpay_payment_link_id != None,
        BillingOrder.status == "pending",
    ).first()
    if existing:
        print(f"[BILLING] Pending payment link already exists for org {org.name}")
        return

    # Pick the yearly plan as default (lowest cost per month)
    plan = db.query(Plan).filter(
        Plan.isactive == True,
        Plan.billing_cycle == "yearly",
        Plan.price_paise != None,
    ).first()

    # Fall back to monthly if no yearly plan
    if not plan:
        plan = db.query(Plan).filter(
            Plan.isactive == True,
            Plan.price_paise != None,
        ).order_by(Plan.price_paise).first()

    if not plan:
        print("[BILLING] No active plan found — cannot create payment link")
        return

    client = _rzp()
    notify_email = org.primary_email or ""
    notify_phone = (org.primary_phone or "").replace(" ", "").replace("-", "")

    link_payload = {
        "amount": plan.price_paise,
        "currency": "INR",
        "description": f"CogniWatt subscription — {plan.planname} plan for {org.name}",
        "notify": {
            "sms": bool(notify_phone and notify_phone.startswith("+91")),
            "email": bool(notify_email),
        },
        "reminder_enable": True,
        "notes": {
            "org_id": str(org.id),
            "plan_id": str(plan.id),
        },
        "callback_method": "get",
    }

    if notify_email:
        link_payload["customer"] = {
            "name": org.name,
            "email": notify_email,
            "contact": notify_phone or "",
        }

    rz_link = client.payment_link.create(link_payload)

    order = BillingOrder(
        org_id=org.id,
        plan_id=plan.id,
        razorpay_payment_link_id=rz_link["id"],
        amount=plan.price_paise,
        currency="INR",
        duration_days=plan.duration_days or 365,
        status="pending",
    )
    db.add(order)
    db.commit()
    print(f"[BILLING] Payment link {rz_link['short_url']} sent to {notify_email} for org {org.name}")
