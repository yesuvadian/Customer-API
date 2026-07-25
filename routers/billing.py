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
from typing import List, Optional
from uuid import UUID

import razorpay
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from auth_utils import get_current_user, decode_access_token
from middleware.org_auth import require_super_admin
from database import get_db
from models import (
    BillingAuditLog, BillingOrder, BillingScope, Module, OrgDepartment,
    OrgPlanPricing, Organization, Plan,
)
from services.billing_invoice_pdf_service import generate_invoice_pdf
from category_labels import (
    BillingStatusLabels, BillingStatusColors, BillingStatusIcons,
    BillingOrderStatusLabels, BillingOrderStatusColors,
)

RAZORPAY_KEY_ID     = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

router = APIRouter(prefix="/billing", tags=["Billing"])
admin_router = APIRouter(prefix="/admin", tags=["Billing Admin"])


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────

def _rzp() -> razorpay.Client:
    key_id = os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    print(f"[RAZORPAY] using key_id={key_id}")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")
    return razorpay.Client(auth=(key_id, key_secret))


def _activate_org_level(org: Organization, order: BillingOrder, db: Session) -> None:
    now = datetime.now(timezone.utc)
    org.is_trial = False
    org.trial_status = "converted"
    org.subscription_start_date = now
    base = max(now, org.subscription_end_date or now)
    org.subscription_end_date = base + timedelta(days=order.duration_days)
    if order.plan_id:
        org.plan_id = order.plan_id
    org.onboarding_complete = True
    org.onboarding_completed_at = now

    # If org was in dept_level mode, a webhook-triggered org payment (mode-switch flow)
    # must also clear dept billing data and switch scope — mirrors switch_to_org_verify.
    if org.billing_scope and org.billing_scope.code == "department_level" and not order.department_id:
        all_depts = db.query(OrgDepartment).filter_by(organization_id=org.id).all()
        for dept in all_depts:
            dept.is_billing_unit = False
            dept.subscription_end_date = None
        org_scope = db.query(BillingScope).filter_by(code="org_level").first()
        if org_scope:
            org.billing_scope_id = org_scope.id
        org.billing_hierarchy_level = None

    db.flush()  # caller holds the single commit


def _activate_dept_level(dept: OrgDepartment, order: BillingOrder, db: Session) -> None:
    now = datetime.now(timezone.utc)
    base = max(now, dept.subscription_end_date or now)
    dept.subscription_end_date = base + timedelta(days=order.duration_days)
    # End the org trial when any dept pays — trial converts to paid service
    org = db.query(Organization).filter_by(id=order.org_id).first()
    if org and org.is_trial:
        org.is_trial = False
        org.trial_status = "converted"

    db.flush()  # caller holds the single commit


def _check_already_processed(order: BillingOrder, incoming_payment_id: str, db: Session) -> bool:
    """Return True if this payment was already successfully processed."""
    if order.status == "paid":
        return True
    duplicate = db.query(BillingOrder).filter(
        BillingOrder.razorpay_payment_id == incoming_payment_id,
        BillingOrder.status == "paid",
    ).first()
    return duplicate is not None


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
    department_id: Optional[str] = None   # set for dept-level payment (Flow B)


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/plans  — public-ish (no auth needed)
# ──────────────────────────────────────────────────────────────────────────

@router.get("/plans")
def list_plans(
    request: Request,
    scope: Optional[str] = Query(None, description="billing scope code: org_level | department_level"),
    db: Session = Depends(get_db),
):
    # Resolve org from token if present (for org-specific pricing)
    org = None
    try:
        org = _resolve_org_from_request(request, db)
    except HTTPException:
        pass  # unauthenticated — use global pricing

    plans = db.query(Plan).filter(
        Plan.isactive == True,
        Plan.price_paise != None,
        Plan.billing_cycle != None,
    ).order_by(Plan.price_paise).all()

    # Resolve billing scope if provided
    billing_scope = None
    if scope:
        billing_scope = db.query(BillingScope).filter_by(code=scope).first()

    result = []
    for p in plans:
        price_paise = p.price_paise
        duration_days = p.duration_days
        pricing_source = "global_default"

        if org and billing_scope:
            override = db.query(OrgPlanPricing).filter_by(
                org_id=org.id, plan_id=p.id, billing_scope_id=billing_scope.id
            ).first()
            if override:
                price_paise = override.price_paise
                duration_days = override.duration_days or p.duration_days
                pricing_source = "org_specific"

        result.append({
            "id": str(p.id),
            "name": p.planname,
            "description": p.plan_description,
            "billing_cycle": p.billing_cycle,
            "duration_days": duration_days,
            "amount_paise": price_paise,
            "amount_display": f"₹{price_paise // 100:,}",
            "amount_per_month": (
                f"₹{price_paise // 100 // 12:,}/mo"
                if p.billing_cycle == "yearly" else
                f"₹{price_paise // 100:,}/mo"
            ),
            "pricing_source": pricing_source,
        })
    return result


# ──────────────────────────────────────────────────────────────────────────
# POST /billing/create-order  — auth token OR payment_token
# ──────────────────────────────────────────────────────────────────────────

@router.post("/create-order")
async def create_order(
    payload: CreateOrderRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Resolve org + token payload (need raw token claims for dept_id in Flow A)
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth_header.split(" ", 1)[1]
    token_payload = decode_access_token(token)
    if not token_payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    is_payment_token = token_payload.get("scope") == "billing"
    org = _resolve_org_from_request(request, db)

    is_dept_level = org.billing_scope and org.billing_scope.code == "department_level"

    # ── Stale-token guard ────────────────────────────────────────────────────
    # Org-level payment_token used against a dept-level org → reject
    if is_dept_level and is_payment_token and not token_payload.get("dept_id"):
        raise HTTPException(
            status_code=400,
            detail="Organisation is in department billing mode. Use a department payment token.",
        )

    # ── Dept-level payment path ──────────────────────────────────────────────
    if is_dept_level:
        # Flow A: blocked login — dept_id is in the payment token
        if is_payment_token and token_payload.get("dept_id"):
            dept_id = token_payload["dept_id"]
            billing_unit = db.query(OrgDepartment).filter_by(
                id=dept_id, organization_id=org.id, is_billing_unit=True
            ).first()
            if not billing_unit:
                raise HTTPException(status_code=400, detail="Payment token dept is not a valid billing unit.")
        else:
            # Flow B: voluntary renewal — dept_id from request body or auto-resolved from user
            from models import User
            user = db.query(User).filter_by(id=token_payload.get("sub")).first()
            if payload.department_id:
                billing_unit = db.query(OrgDepartment).filter_by(
                    id=payload.department_id, organization_id=org.id, is_billing_unit=True
                ).first()
                if not billing_unit:
                    raise HTTPException(status_code=400, detail="department_id is not a valid billing unit for this org.")
            else:
                # Auto-resolve from the requesting user's billing unit
                billing_unit = walk_up_tree(user.department_id, db, is_billing_unit=True) if user else None
                if not billing_unit:
                    raise HTTPException(status_code=400, detail="Could not resolve a billing unit for your department.")

        # Use org plan — depts cannot choose independently (Decision 12)
        if not org.plan_id:
            raise HTTPException(status_code=400, detail="No plan selected. Contact your organisation admin.")
        plan = db.query(Plan).filter_by(id=org.plan_id, isactive=True).first()
        if not plan or not plan.price_paise:
            raise HTTPException(status_code=404, detail="Org plan not found or has no price.")

        # Resolve dept-specific price override
        dept_scope = db.query(BillingScope).filter_by(code="department_level").first()
        price_paise = plan.price_paise
        if dept_scope:
            override = db.query(OrgPlanPricing).filter_by(
                org_id=org.id, plan_id=plan.id, billing_scope_id=dept_scope.id
            ).first()
            if override:
                price_paise = override.price_paise

        # Double-payment guard: return existing pending order for this dept
        existing_pending = db.query(BillingOrder).filter(
            BillingOrder.org_id == org.id,
            BillingOrder.department_id == billing_unit.id,
            BillingOrder.status == "pending",
        ).first()
        if existing_pending:
            return {
                "razorpay_key_id": RAZORPAY_KEY_ID,
                "razorpay_order_id": existing_pending.razorpay_order_id,
                "amount": existing_pending.amount_paise,
                "currency": existing_pending.currency,
                "plan_name": plan.planname,
                "org_name": org.name,
                "dept_name": billing_unit.name,
                "contact_email": org.primary_email or "",
            }

        client = _rzp()
        rz_order = client.order.create({
            "amount": price_paise,
            "currency": "INR",
            "receipt": f"dept_{str(billing_unit.id)[:8]}",
            "notes": {
                "org_id":    str(org.id),
                "org_name":  org.name,
                "dept_id":   str(billing_unit.id),
                "dept_name": billing_unit.name,
                "plan_id":   str(plan.id),
                "plan_name": plan.planname,
            },
        })

        order = BillingOrder(
            org_id=org.id,
            department_id=billing_unit.id,
            plan_id=plan.id,
            plan_name=plan.planname,
            razorpay_order_id=rz_order["id"],
            amount=price_paise,
            amount_paise=price_paise,
            currency="INR",
            duration_days=plan.duration_days or 365,
            status="pending",
        )
        db.add(order)
        db.commit()

        return {
            "razorpay_key_id": RAZORPAY_KEY_ID,
            "razorpay_order_id": rz_order["id"],
            "amount": price_paise,
            "currency": "INR",
            "plan_name": plan.planname,
            "org_name": org.name,
            "dept_name": billing_unit.name,
            "contact_email": org.primary_email or "",
        }

    # ── Org-level payment path (existing behaviour) ──────────────────────────
    plan = db.query(Plan).filter_by(id=payload.plan_id, isactive=True).first()
    if not plan or not plan.price_paise:
        raise HTTPException(status_code=404, detail="Plan not found or has no price")

    client = _rzp()
    rz_order = client.order.create({
        "amount": plan.price_paise,
        "currency": "INR",
        "receipt": f"org_{str(org.id)[:8]}",
        "notes": {
            "org_id":   str(org.id),
            "org_name": org.name,
            "plan_id":  str(plan.id),
            "plan_name": plan.planname,
        },
    })

    order = BillingOrder(
        org_id=org.id,
        plan_id=plan.id,
        plan_name=plan.planname,
        razorpay_order_id=rz_order["id"],
        amount=plan.price_paise,
        amount_paise=plan.price_paise,
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

    import logging as _verify_log
    _vlog = _verify_log.getLogger(__name__)

    order = db.query(BillingOrder).filter_by(
        razorpay_order_id=payload.razorpay_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if _check_already_processed(order, payload.razorpay_payment_id, db):
        return {"message": "Already activated", "status": "paid"}

    now = datetime.now(timezone.utc)

    # Cancelled order — capture wins (Scenario 4: price change post-capture)
    if order.status == "cancelled":
        order.status = "paid"
        order.razorpay_payment_id = payload.razorpay_payment_id
        order.razorpay_signature = payload.razorpay_signature
        order.paid_at = now
        order.anomaly_flag = True
        order.anomaly_reason = "price_changed_post_capture"
        db.flush()
        if order.department_id:
            dept = db.query(OrgDepartment).filter_by(id=order.department_id).first()
            if dept:
                if not dept.is_billing_unit:
                    dept.is_billing_unit = True
                _activate_dept_level(dept, order, db)
                _vlog.error(
                    f"ANOMALY: Order {order.id} was cancelled but payment {payload.razorpay_payment_id} captured. "
                    f"Dept '{dept.name}' activated. Flagged for review."
                )
            else:
                _vlog.error(f"ANOMALY: Order {order.id} cancelled, dept {order.department_id} not found. Manual refund required.")
        else:
            org = db.query(Organization).filter_by(id=order.org_id).first()
            if org:
                _activate_org_level(org, order, db)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"message": "Payment verified. Your account is now active.", "status": "paid", "note": "anomaly_flagged"}

    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    order.status = "paid"
    order.paid_at = now
    db.flush()

    if order.department_id:
        dept = db.query(OrgDepartment).filter_by(id=order.department_id).first()
        if dept:
            if not dept.is_billing_unit:
                dept.is_billing_unit = True
            _activate_dept_level(dept, order, db)
            recompute_billing_units(order.org_id, db)
        else:
            _vlog.warning(
                f"verify: dept {order.department_id} not found. Order {order.id} paid but not activated."
            )
    else:
        org = db.query(Organization).filter_by(id=order.org_id).first()
        if org:
            _activate_org_level(org, order, db)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Fire payment-confirmed notification
    try:
        from services.notification_service import NotificationService
        org = db.query(Organization).filter_by(id=order.org_id).first()
        dept = db.query(OrgDepartment).filter_by(id=order.department_id).first() if order.department_id else None
        if org:
            amount_display = f"₹{int((order.amount_paise or 0) / 100):,}"
            NotificationService(db).fire(
                event_type="billing_payment_confirmed",
                context={
                    "org_name": org.name,
                    "dept_name": dept.name if dept else org.name,
                    "plan_name": order.plan_name or "",
                    "amount": amount_display,
                },
                organization_id=org.id,
                source_id=order.id,
                source_type="BillingOrder",
                severity="info",
                extra_data={"order_id": str(order.id)},
            )
    except Exception as _ne:
        _vlog.warning(f"[Billing] Payment-confirmed notification failed: {_ne}")

    return {"message": "Payment verified. Your account is now active.", "status": "paid"}


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/status-meta  — static lookup tables (no auth needed)
# ──────────────────────────────────────────────────────────────────────────

@router.get("/status-meta")
def billing_status_meta():
    """
    Returns the complete set of billing status labels, colors, and icons so
    Flutter never hardcodes them.  Call once on startup and cache client-side.
    """
    subscription_statuses = []
    for key in ["active", "expired", "pending_payment", "trial", "trial_expired"]:
        subscription_statuses.append({
            "status":     key,
            "label":      BillingStatusLabels.get(key),
            "color":      BillingStatusColors.get(key),
            "icon":       BillingStatusIcons.get(key),
        })

    order_statuses = []
    for key in ["pending", "paid", "failed", "cancelled"]:
        order_statuses.append({
            "status": key,
            "label":  BillingOrderStatusLabels.get(key),
            "color":  BillingOrderStatusColors.get(key),
        })

    return {
        "subscription_statuses": subscription_statuses,
        "order_statuses":        order_statuses,
    }


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

    now = datetime.now(timezone.utc)

    if org.billing_scope and org.billing_scope.code == "department_level":
        billing_unit = walk_up_tree(current_user.department_id, db, is_billing_unit=True)
        if billing_unit:
            end = billing_unit.subscription_end_date
            days = max(0, (end - now).days) if end and end >= now else 0
            sub_status = "active" if (end and end >= now) else ("expired" if end else "pending_payment")
            return {
                "scope": "department",
                "dept_name": billing_unit.name,
                "dept_id": str(billing_unit.id),
                "subscription_end_date": end.isoformat() if end else None,
                "days_remaining": days if end else None,
                "alert_active": bool(end and 0 < (end - now).days <= 7),
                "status":       sub_status,
                "status_label": BillingStatusLabels.get(sub_status),
                "status_color": BillingStatusColors.get(sub_status),
                "status_icon":  BillingStatusIcons.get(sub_status),
            }
        # No billing unit ancestor — fall through to org-level response

    plan = db.query(Plan).filter_by(id=org.plan_id).first() if org.plan_id else None
    end = org.subscription_end_date
    days = max(0, (end - now).days) if end and end >= now else 0

    if org.is_trial:
        sub_status = "trial_expired" if (org.trial_end_date and org.trial_end_date < now) else "trial"
    elif end and end < now:
        sub_status = "expired"
    elif end:
        sub_status = "active"
    else:
        sub_status = "pending_payment"

    return {
        "scope": "organisation",
        "is_trial": org.is_trial,
        "trial_status": org.trial_status,
        "trial_end_date": org.trial_end_date.isoformat() if org.trial_end_date else None,
        "subscription_end_date": end.isoformat() if end else None,
        "days_remaining": days if end else None,
        "alert_active": bool(end and 0 < (end - now).days <= 7),
        "plan": {
            "id": str(plan.id),
            "name": plan.planname,
            "billing_cycle": plan.billing_cycle,
        } if plan else None,
        "status":       sub_status,
        "status_label": BillingStatusLabels.get(sub_status),
        "status_color": BillingStatusColors.get(sub_status),
        "status_icon":  BillingStatusIcons.get(sub_status),
    }


def _get_subtree_billing_unit_ids(root_dept_id, org_id, db) -> list:
    """Return IDs of all billing-unit departments in the subtree rooted at root_dept_id."""
    if root_dept_id is None:
        return []
    visited, queue = set(), [root_dept_id]
    billing_ids = []
    while queue:
        current = queue.pop()
        if current in visited:
            continue
        visited.add(current)
        dept = db.query(OrgDepartment).filter_by(id=current, organization_id=org_id).first()
        if not dept:
            continue
        if dept.is_billing_unit:
            billing_ids.append(dept.id)
        children = db.query(OrgDepartment).filter_by(
            parent_id=current, organization_id=org_id
        ).all()
        queue.extend(c.id for c in children)
    return billing_ids


# ──────────────────────────────────────────────────────────────────────────
# GET /billing/orders  — payment history for the org
# ──────────────────────────────────────────────────────────────────────────

@router.get("/orders")
def billing_orders(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    is_dept_level = org.billing_scope and org.billing_scope.code == "department_level"
    is_root_user = current_user.department_id is None

    if is_dept_level and not is_root_user:
        billing_unit = db.query(OrgDepartment).filter_by(id=current_user.billing_unit_id).first() if current_user.billing_unit_id else None
        if billing_unit:
            orders = db.query(BillingOrder).filter_by(
                org_id=org.id, department_id=billing_unit.id
            ).order_by(BillingOrder.created_at.desc()).all()
        else:
            orders = []
    else:
        # Root user (org admin) or org-level mode → all orders for the org
        orders = db.query(BillingOrder).filter_by(
            org_id=org.id
        ).order_by(BillingOrder.created_at.desc()).all()

    # Build dept name lookup
    dept_ids_in_orders = {o.department_id for o in orders if o.department_id}
    dept_name_map = {}
    if dept_ids_in_orders:
        depts = db.query(OrgDepartment).filter(OrgDepartment.id.in_(dept_ids_in_orders)).all()
        dept_name_map = {str(d.id): d.name for d in depts}

    result = []
    for o in orders:
        plan = db.query(Plan).filter_by(id=o.plan_id).first() if o.plan_id else None
        dept_id_str = str(o.department_id) if o.department_id else None
        result.append({
            "id": str(o.id),
            "plan_name": o.plan_name or (plan.planname if plan else None),
            "billing_cycle": plan.billing_cycle if plan else None,
            "amount_paise": o.amount_paise or o.amount,
            "currency": o.currency,
            "status":        o.status,
            "status_label":  BillingOrderStatusLabels.get(o.status),
            "status_color":  BillingOrderStatusColors.get(o.status),
            "department_id": dept_id_str,
            "department_name": dept_name_map.get(dept_id_str) if dept_id_str else None,
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

    dept_name = None
    if order.department_id:
        dept = db.query(OrgDepartment).filter_by(id=order.department_id).first()
        dept_name = dept.name if dept else None

    invoice_no = f"INV-{str(order.id)[:8].upper()}"
    paid_date = order.paid_at or order.created_at

    pdf_bytes = generate_invoice_pdf(
        invoice_no=invoice_no,
        org_name=org.name if org else "—",
        org_email=org.primary_email or "" if org else "",
        plan_name=order.plan_name or (plan.planname if plan else "Subscription"),
        billing_cycle=plan.billing_cycle or "" if plan else "",
        amount_paise=order.amount_paise or order.amount or 0,
        paid_date=paid_date,
        razorpay_payment_id=order.razorpay_payment_id or "",
        dept_name=dept_name,
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

    import logging as _wh_log
    _logger = _wh_log.getLogger(__name__)

    def _activate_order(order: BillingOrder, rz_payment_id: str, label: str):
        """Mark order paid and activate org or dept. Handles anomalies. Always commits."""
        if _check_already_processed(order, rz_payment_id, db):
            _logger.info(f"Webhook [{label}]: duplicate event for order {order.id}, skipping.")
            return

        now = datetime.now(timezone.utc)
        was_cancelled = order.status == "cancelled"

        order.razorpay_payment_id = rz_payment_id
        order.status = "paid"
        order.paid_at = now
        db.flush()

        if order.department_id:
            dept = db.query(OrgDepartment).filter_by(id=order.department_id).first()
            if dept:
                org = db.query(Organization).filter_by(id=order.org_id).first()
                # Scenario 2: org switched to org-level after dept order was placed
                if org and org.billing_scope and org.billing_scope.code == "org_level" \
                        and org.subscription_end_date and org.subscription_end_date > now:
                    order.anomaly_flag = True
                    order.anomaly_reason = "org_level_switch"
                    _logger.error(
                        f"ANOMALY [{label}]: Dept payment captured after org-level switch for org {org.id}. "
                        f"Money received but not applied. Consider refund. Order {order.id}."
                    )
                    db.commit()
                    return

                if was_cancelled:
                    order.anomaly_flag = True
                    order.anomaly_reason = "hierarchy_changed"
                    _logger.error(
                        f"ANOMALY [{label}]: Order {order.id} was cancelled but payment captured. "
                        f"Re-activating dept '{dept.name}'."
                    )

                if not dept.is_billing_unit:
                    dept.is_billing_unit = True
                _activate_dept_level(dept, order, db)
                recompute_billing_units(order.org_id, db)
                _logger.info(f"[BILLING-WEBHOOK] Dept '{dept.name}' activated via {label}")
            else:
                # Dept deleted after order was placed
                order.anomaly_flag = True
                order.anomaly_reason = "dept_deleted"
                _logger.error(
                    f"ANOMALY [{label}]: Dept {order.department_id} deleted but payment captured. "
                    f"Manual refund required. Order {order.id}."
                )
                db.commit()
                return
        else:
            org = db.query(Organization).filter_by(id=order.org_id).first()
            if org:
                _activate_org_level(org, order, db)
                _logger.info(f"[BILLING-WEBHOOK] Org '{org.name}' activated via {label}")

        try:
            db.commit()
        except Exception as e:
            db.rollback()
            _logger.error(f"Webhook [{label}]: DB commit failed for order {order.id}: {e}")

    if event_type == "payment.captured":
        payment = event["payload"]["payment"]["entity"]
        rz_order_id = payment.get("order_id")
        rz_payment_id = payment.get("id")

    elif event_type == "payment_link.paid":
        payment = event["payload"]["payment"]["entity"]
        rz_payment_id = payment.get("id")
        rz_order_id = payment.get("order_id")
        # Also try to match via payment_link_id when order_id is absent
        link_id = event["payload"].get("payment_link", {}).get("entity", {}).get("id")
        if link_id and not rz_order_id:
            order = db.query(BillingOrder).filter_by(razorpay_payment_link_id=link_id).first()
            if order:
                _activate_order(order, rz_payment_id, "payment_link.paid")
            return {"status": "ok"}

    elif event_type == "payment.failed":
        payment = event["payload"]["payment"]["entity"]
        rz_order_id = payment.get("order_id")
        if rz_order_id:
            order = db.query(BillingOrder).filter_by(razorpay_order_id=rz_order_id).first()
            if order and order.status == "pending":
                order.status = "failed"
                db.commit()
        return {"status": "ok"}

    if rz_order_id:
        order = db.query(BillingOrder).filter_by(razorpay_order_id=rz_order_id).first()
        if order:
            _activate_order(order, rz_payment_id, event_type)

    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — BILLING CONFIG API
# ══════════════════════════════════════════════════════════════════════════════

# ── Shared tree helpers ───────────────────────────────────────────────────────

def get_dept_depth(dept_id, db) -> Optional[int]:
    """Walk up tree counting hops to root. Returns None if dept_id is NULL."""
    if not dept_id:
        return None
    depth, current_id, seen = 0, dept_id, set()
    while current_id:
        if current_id in seen:
            break
        seen.add(current_id)
        dept = db.query(OrgDepartment).filter_by(id=current_id).first()
        if not dept:
            break
        depth += 1
        current_id = dept.parent_department_id
    return depth


def walk_up_tree(dept_id, db, *, is_billing_unit=False):
    """Walk from dept_id toward root. If is_billing_unit=True, return first
    ancestor (inclusive) where dept.is_billing_unit == True."""
    if not dept_id:
        return None
    current_id, seen = dept_id, set()
    while current_id:
        if current_id in seen:
            break
        seen.add(current_id)
        dept = db.query(OrgDepartment).filter_by(id=current_id).first()
        if not dept:
            break
        if is_billing_unit and dept.is_billing_unit:
            return dept
        current_id = dept.parent_department_id
    return None


def recompute_billing_units(org_id, db) -> None:
    """Re-cache User.billing_unit_id for every user in the org.
    Uses a single ancestor-chain CTE instead of per-user walk_up_tree queries."""
    from models import User

    # Build ancestor chain for every dept in the org in one query.
    # For each dept, find the nearest ancestor (or self) that is a billing unit.
    ancestor_rows = db.execute(text("""
        WITH RECURSIVE ancestors AS (
            SELECT id, id AS root_id, is_billing_unit, parent_department_id
            FROM org_departments
            WHERE organization_id = :org_id AND is_active = true
            UNION ALL
            SELECT p.id, a.root_id, p.is_billing_unit, p.parent_department_id
            FROM org_departments p
            JOIN ancestors a ON p.id = a.parent_department_id
            WHERE p.is_active = true
        )
        SELECT DISTINCT ON (root_id) root_id, id AS billing_unit_id
        FROM ancestors
        WHERE is_billing_unit = true
        ORDER BY root_id, id
    """), {"org_id": str(org_id)}).fetchall()

    dept_to_billing_unit = {str(r[0]): str(r[1]) for r in ancestor_rows}

    users = db.query(User).filter_by(organization_id=org_id).all()
    for user in users:
        billing_unit_id = dept_to_billing_unit.get(str(user.department_id)) if user.department_id else None
        user.billing_unit_id = billing_unit_id
    db.flush()


_RECOMPUTE_RETRY_DELAYS = [30, 120, 300]  # seconds


def run_billing_unit_recompute_job(org_id: str, attempt: int = 0) -> None:
    """Background job: recompute billing unit cache, with up to 3 retries."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        org = db.query(Organization).filter_by(id=org_id).first()
        if not org:
            return
        org.billing_unit_recompute_status = "running"
        org.billing_unit_recompute_started = datetime.now(timezone.utc)
        db.commit()

        recompute_billing_units(org_id, db)

        org = db.query(Organization).filter_by(id=org_id).first()
        org.billing_unit_recompute_pending = False
        org.billing_unit_recompute_status = "completed"
        org.billing_unit_recompute_error = None
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            retries = attempt + 1
            err_org = db.query(Organization).filter_by(id=org_id).first()
            if err_org:
                err_org.billing_unit_recompute_retries = retries
                err_org.billing_unit_recompute_status = "failed"
                err_org.billing_unit_recompute_error = str(exc)[:500]
                db.commit()
            if attempt < len(_RECOMPUTE_RETRY_DELAYS):
                _schedule_recompute_retry(org_id, attempt + 1, _RECOMPUTE_RETRY_DELAYS[attempt])
        except Exception:
            pass
    finally:
        db.close()


def _schedule_recompute_retry(org_id: str, attempt: int, delay_seconds: int) -> None:
    import threading
    threading.Timer(delay_seconds, run_billing_unit_recompute_job, args=(org_id, attempt)).start()


def _write_billing_audit(db, *, org_id, actor_user, action, entity_type=None,
                         entity_id=None, before_json=None, after_json=None,
                         billing_order_id=None, notes=None, billing_units_affected=None):
    db.add(BillingAuditLog(
        org_id=org_id,
        actor_user_id=actor_user.id,
        actor_name=f"{actor_user.firstname or ''} {actor_user.lastname or ''}".strip() or actor_user.email,
        actor_usertype=actor_user.usertype or "unknown",
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_json=before_json,
        after_json=after_json,
        billing_order_id=billing_order_id,
        notes=notes,
        billing_units_affected=billing_units_affected,
    ))


def _resolve_billing_scope(code: str, db: Session) -> BillingScope:
    scope = db.query(BillingScope).filter_by(code=code).first()
    if not scope:
        raise HTTPException(status_code=400, detail=f"Unknown billing scope: {code}")
    return scope


def _get_dept_level_label(org: Organization, level: int) -> str:
    if org.dept_level_labels and str(level) in org.dept_level_labels:
        return org.dept_level_labels[str(level)]
    return f"Level {level}"


def _switch_to_dept_level(org: Organization, hierarchy_level: int, plan_id, db: Session):
    """Set all depts at hierarchy_level as billing units.
    Subscription end date is determined by:
      1. Inherit active org.subscription_end_date if present, OR
      2. Auto-activate using the plan's duration_days from now.
    Returns (billing_unit_count, cancelled_order_count, billing_end_date)."""
    now = datetime.now(timezone.utc)

    # Determine end date for all billing units
    resolved_plan_id = plan_id or org.plan_id
    plan = db.query(Plan).filter_by(id=resolved_plan_id, isactive=True).first() if resolved_plan_id else None

    # Trial orgs: depts start as pending_payment — payment activates each unit individually
    if org.is_trial:
        billing_end_date = None
    elif org.subscription_end_date and org.subscription_end_date > now:
        billing_end_date = org.subscription_end_date
    elif plan and plan.duration_days:
        billing_end_date = now + timedelta(days=plan.duration_days)
    else:
        billing_end_date = None

    # Single CTE to compute depth of every dept — avoids N×depth individual queries
    depth_rows = db.execute(text("""
        WITH RECURSIVE dept_depth AS (
            SELECT id, 1 AS depth
            FROM org_departments
            WHERE organization_id = :org_id AND is_active = true
              AND parent_department_id IS NULL
            UNION ALL
            SELECT d.id, dd.depth + 1
            FROM org_departments d
            JOIN dept_depth dd ON d.parent_department_id = dd.id
            WHERE d.organization_id = :org_id AND d.is_active = true
        )
        SELECT id, depth FROM dept_depth
    """), {"org_id": str(org.id)}).fetchall()
    depth_map = {str(r[0]): r[1] for r in depth_rows}

    all_depts = db.query(OrgDepartment).filter_by(
        organization_id=org.id, is_active=True
    ).all()

    dept_level_scope = _resolve_billing_scope("department_level", db)
    billing_units = []
    cleared_dept_ids = []

    for dept in all_depts:
        depth = depth_map.get(str(dept.id))
        if depth == hierarchy_level:
            dept.is_billing_unit = True
            dept.subscription_end_date = billing_end_date
            billing_units.append(dept)
        else:
            if dept.is_billing_unit:
                cleared_dept_ids.append(dept.id)
            dept.is_billing_unit = False
            dept.subscription_end_date = None

    # Cancel pending orders for depts that lost billing-unit status
    cancelled = 0
    for dept_id in cleared_dept_ids:
        stale = db.query(BillingOrder).filter(
            BillingOrder.department_id == dept_id,
            BillingOrder.status == "pending",
        ).all()
        for order in stale:
            order.status = "cancelled"
            order.cancellation_reason = "hierarchy_changed"
            cancelled += 1

    if org.subscription_end_date:
        org.subscription_end_date = None

    org.billing_scope_id = dept_level_scope.id
    org.billing_hierarchy_level = hierarchy_level
    if plan_id:
        org.plan_id = plan_id
    org.billing_unit_recompute_pending = True
    org.billing_unit_recompute_status = "pending"
    org.billing_unit_recompute_retries = 0
    org.billing_unit_recompute_started = None
    org.billing_unit_recompute_error = None
    db.flush()
    return len(billing_units), cancelled, billing_end_date


def _switch_to_org_level(org: Organization, db: Session):
    """Clear all billing unit flags. Org admin must pay fresh."""
    all_depts = db.query(OrgDepartment).filter_by(organization_id=org.id).all()
    for dept in all_depts:
        dept.is_billing_unit = False
        dept.subscription_end_date = None

    org_level_scope = _resolve_billing_scope("org_level", db)
    org.billing_scope_id = org_level_scope.id
    org.billing_hierarchy_level = None
    org.billing_unit_recompute_pending = True
    org.billing_unit_recompute_status = "pending"
    org.billing_unit_recompute_retries = 0
    org.billing_unit_recompute_started = None
    org.billing_unit_recompute_error = None
    db.flush()


# ── Schemas ───────────────────────────────────────────────────────────────────

class BillingConfigPutRequest(BaseModel):
    billing_scope_code: str
    billing_hierarchy_level: Optional[int] = None
    plan_id: Optional[str] = None


class PlanPricingRow(BaseModel):
    plan_id: str
    billing_scope_code: str
    price_paise: int
    duration_days: Optional[int] = None


# ── GET /billing/wizard-config ────────────────────────────────────────────────
# Accepts both regular Bearer tokens and payment tokens (scope=billing).
# Returns everything the setup wizard needs to decide which step to show.

@router.get("/wizard-config")
def get_wizard_config(
    request: Request,
    db: Session = Depends(get_db),
):
    org = _resolve_org_from_request(request, db)

    billing_mode = org.billing_scope.code if org.billing_scope else None

    from models import Plan
    plan = db.query(Plan).filter_by(id=org.plan_id).first() if org.plan_id else None

    from models import OrgPlanPricing, BillingScope
    dept_scope = db.query(BillingScope).filter_by(code="department_level").first()
    dept_pricing_ready = False
    if dept_scope:
        dept_pricing_ready = db.query(OrgPlanPricing).filter_by(
            org_id=org.id, billing_scope_id=dept_scope.id
        ).first() is not None

    return {
        "billing_mode": billing_mode,
        "billing_hierarchy_level": org.billing_hierarchy_level,
        "plan_id": str(org.plan_id) if org.plan_id else None,
        "plan_name": plan.planname if plan else None,
        "is_trial": org.is_trial,
        "dept_pricing_ready": dept_pricing_ready,
    }


# ── GET /billing/config ───────────────────────────────────────────────────────

@router.get("/config")
def get_billing_config(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    billing_mode = org.billing_scope.code if org.billing_scope else "org_level"
    print(f"[BILLING-CONFIG] user={current_user.id} org={org.id} billing_scope={org.billing_scope} billing_mode={billing_mode} is_trial={org.is_trial} plan_id={org.plan_id}")

    # Trial orgs that haven't configured dept billing yet — skip all dept logic
    if org.is_trial and billing_mode != "department_level":
        return {
            "billing_mode": "org_level",
            "billing_hierarchy_level": None,
            "plan_id": None,
            "is_trial": True,
            "available_levels": [],
        }

    current_level = org.billing_hierarchy_level
    current_level_info = []
    if billing_mode == "department_level" and current_level is not None:
        unit_count = db.query(OrgDepartment).filter_by(
            organization_id=org.id, is_billing_unit=True, is_active=True
        ).count()
        current_level_info = [
            {"level": current_level, "label": _get_dept_level_label(org, current_level), "dept_count": unit_count}
        ]

    from models import SystemConfig
    import json as _json
    reminder_cfg = db.query(SystemConfig).filter_by(key="billing_subscription_reminder_days").first()
    reminder_days = _json.loads(reminder_cfg.value) if reminder_cfg else [30, 7]
    alert_days = min(reminder_days) if reminder_days else 7

    return {
        "billing_mode": billing_mode,
        "billing_hierarchy_level": current_level,
        "plan_id": str(org.plan_id) if org.plan_id else None,
        "is_trial": org.is_trial,
        "available_levels": current_level_info,
        "alert_days": alert_days,
    }


# ── PUT /billing/config ───────────────────────────────────────────────────────

@router.get("/levels")
def get_billing_levels(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """On-demand dept counts per level — only called when user opens the level picker."""
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    level_counts = db.execute(text("""
        WITH RECURSIVE dept_depth AS (
            SELECT id, 1 AS depth FROM org_departments
            WHERE organization_id = :org_id AND is_active = true AND parent_department_id IS NULL
            UNION ALL
            SELECT d.id, dd.depth + 1 FROM org_departments d
            JOIN dept_depth dd ON d.parent_department_id = dd.id
            WHERE d.organization_id = :org_id AND d.is_active = true
        )
        SELECT depth, COUNT(*) FROM dept_depth GROUP BY depth ORDER BY depth
    """), {"org_id": str(org.id)}).fetchall()

    return [
        {"level": row[0], "label": _get_dept_level_label(org, row[0]), "dept_count": row[1]}
        for row in level_counts
    ]


@router.put("/config")
def put_billing_config(
    body: BillingConfigPutRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    if org.is_trial:
        raise HTTPException(status_code=400, detail="Cannot change billing mode during active trial.")

    current_mode = org.billing_scope.code if org.billing_scope else "org_level"

    if body.billing_scope_code == "org_level" and current_mode == "department_level":
        raise HTTPException(
            status_code=400,
            detail="Use the Organisation Level payment flow to switch back.",
        )

    if body.billing_scope_code == "department_level":
        if not body.billing_hierarchy_level:
            raise HTTPException(status_code=400, detail="billing_hierarchy_level is required for department-level billing.")
        if not body.plan_id and not org.plan_id:
            raise HTTPException(status_code=400, detail="plan_id is required for department-level billing.")

        before = {"billing_scope": current_mode, "billing_hierarchy_level": org.billing_hierarchy_level}
        units_count, cancelled, _billing_end = _switch_to_dept_level(org, body.billing_hierarchy_level, body.plan_id, db)
        after = {"billing_scope": "department_level", "billing_hierarchy_level": body.billing_hierarchy_level}

        _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                             action="switch_to_dept_level",
                             before_json=before, after_json=after,
                             billing_units_affected=units_count)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown billing scope code: '{body.billing_scope_code}'.")

    org_id_str = str(org.id)
    db.commit()
    background_tasks.add_task(run_billing_unit_recompute_job, org_id_str)
    return {"message": "Billing config updated.", "billing_mode": body.billing_scope_code}


# ── GET /billing/dept-tree-levels ─────────────────────────────────────────────

@router.get("/dept-tree-levels")
def get_dept_tree_levels(
    request: Request,
    db: Session = Depends(get_db),
):
    org = _resolve_org_from_request(request, db)

    rows = db.execute(text("""
        WITH RECURSIVE dept_depth AS (
            SELECT id, 1 AS depth FROM org_departments
            WHERE organization_id = :org_id AND is_active = true AND parent_department_id IS NULL
            UNION ALL
            SELECT d.id, dd.depth + 1 FROM org_departments d
            JOIN dept_depth dd ON d.parent_department_id = dd.id
            WHERE d.organization_id = :org_id AND d.is_active = true
        )
        SELECT depth, COUNT(*) FROM dept_depth GROUP BY depth ORDER BY depth
    """), {"org_id": str(org.id)}).fetchall()

    return [
        {"level": row[0], "label": _get_dept_level_label(org, row[0]), "dept_count": row[1]}
        for row in rows
    ]


# ── GET /billing/dept-billing-units ──────────────────────────────────────────

@router.get("/dept-billing-units")
def get_dept_billing_units(
    request: Request,
    level: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(int(os.getenv("BILLING_DEPT_PAGE_SIZE", "50")), ge=1, le=200),
    db: Session = Depends(get_db),
):
    import math
    org = _resolve_org_from_request(request, db)
    offset = (page - 1) * page_size
    params = {"org_id": str(org.id), "limit": page_size, "offset": offset}

    if level is not None:
        params["level"] = level
        cte = """
            WITH RECURSIVE dept_depth AS (
                SELECT id, 1 AS depth
                FROM org_departments
                WHERE organization_id = :org_id
                  AND is_active = true
                  AND parent_department_id IS NULL
                UNION ALL
                SELECT d.id, dd.depth + 1
                FROM org_departments d
                JOIN dept_depth dd ON d.parent_department_id = dd.id
                WHERE d.organization_id = :org_id
                  AND d.is_active = true
            )
        """
        total = db.execute(text(cte + """
            SELECT COUNT(*) FROM org_departments d
            JOIN dept_depth dd ON d.id = dd.id
            WHERE dd.depth = :level
        """), params).scalar()

        rows = db.execute(text(cte + """
            SELECT d.id, d.name, d.code, d.is_billing_unit, d.subscription_end_date
            FROM org_departments d
            JOIN dept_depth dd ON d.id = dd.id
            WHERE dd.depth = :level
            ORDER BY
                CASE
                    WHEN d.subscription_end_date IS NOT NULL AND d.subscription_end_date > NOW() THEN 0
                    WHEN d.subscription_end_date IS NULL THEN 1
                    ELSE 2
                END,
                d.subscription_end_date DESC NULLS LAST,
                d.name
            LIMIT :limit OFFSET :offset
        """), params).fetchall()
    else:
        total = db.execute(text("""
            SELECT COUNT(*) FROM org_departments
            WHERE organization_id = :org_id AND is_active = true
        """), params).scalar()

        rows = db.execute(text("""
            SELECT id, name, code, is_billing_unit, subscription_end_date
            FROM org_departments
            WHERE organization_id = :org_id AND is_active = true
            ORDER BY
                CASE
                    WHEN subscription_end_date IS NOT NULL AND subscription_end_date > NOW() THEN 0
                    WHEN subscription_end_date IS NULL THEN 1
                    ELSE 2
                END,
                subscription_end_date DESC NULLS LAST,
                name
            LIMIT :limit OFFSET :offset
        """), params).fetchall()

    return {
        "items": [
            {
                "id": str(r[0]),
                "name": r[1],
                "code": r[2],
                "is_billing_unit": r[3],
                "subscription_end_date": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
        "has_more": offset + page_size < total,
    }


# ── GET /admin/orgs/{org_id}/billing-config ───────────────────────────────────

@admin_router.get("/orgs/{org_id}/billing-config")
def admin_get_billing_config(
    org_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    from middleware.org_auth import check_org_permission
    if current_user.usertype != "super_admin":
        orgs_module = db.query(Module).filter_by(name="Organizations").first()
        orgs_module_id = orgs_module.id if orgs_module else None
        if not orgs_module_id or not check_org_permission(current_user.id, orgs_module_id, "can_view", db):
            raise HTTPException(status_code=403, detail="Access denied: Organizations module permission required")

    billing_mode = org.billing_scope.code if org.billing_scope else "org_level"

    # Never run the tree-walk CTE here. available_levels is fetched on-demand
    # via GET /admin/orgs/{org_id}/billing-levels only when user opens the level picker.
    current_level = org.billing_hierarchy_level
    current_level_info = []
    if billing_mode == "department_level" and current_level is not None:
        unit_count = db.query(OrgDepartment).filter_by(
            organization_id=org.id, is_billing_unit=True, is_active=True
        ).count()
        current_level_info = [
            {"level": current_level, "label": _get_dept_level_label(org, current_level), "dept_count": unit_count}
        ]

    return {
        "org_id": str(org.id),
        "org_name": org.name,
        "billing_mode": billing_mode,
        "billing_hierarchy_level": current_level,
        "plan_id": str(org.plan_id) if org.plan_id else None,
        "subscription_end_date": org.subscription_end_date.isoformat() if org.subscription_end_date else None,
        "available_levels": current_level_info,
    }


# ── GET /admin/orgs/{org_id}/billing-levels  (on-demand, runs the tree CTE) ───

@admin_router.get("/orgs/{org_id}/billing-levels")
def admin_get_billing_levels(
    org_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns dept counts per hierarchy level. Called only when user opens the
    level picker — never on initial page load."""
    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    from middleware.org_auth import check_org_permission
    if current_user.usertype != "super_admin":
        orgs_module = db.query(Module).filter_by(name="Organizations").first()
        orgs_module_id = orgs_module.id if orgs_module else None
        if not orgs_module_id or not check_org_permission(current_user.id, orgs_module_id, "can_view", db):
            raise HTTPException(status_code=403, detail="Access denied")

    level_counts = db.execute(text("""
        WITH RECURSIVE dept_depth AS (
            SELECT id, 1 AS depth FROM org_departments
            WHERE organization_id = :org_id AND is_active = true AND parent_department_id IS NULL
            UNION ALL
            SELECT d.id, dd.depth + 1 FROM org_departments d
            JOIN dept_depth dd ON d.parent_department_id = dd.id
            WHERE d.organization_id = :org_id AND d.is_active = true
        )
        SELECT depth, COUNT(*) FROM dept_depth GROUP BY depth ORDER BY depth
    """), {"org_id": str(org.id)}).fetchall()

    return [
        {"level": row[0], "label": _get_dept_level_label(org, row[0]), "dept_count": row[1]}
        for row in level_counts
    ]


# ── PUT /admin/orgs/{org_id}/billing-config ───────────────────────────────────

@admin_router.put("/orgs/{org_id}/billing-config")
def admin_put_billing_config(
    org_id: str,
    body: BillingConfigPutRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from middleware.org_auth import check_org_permission
    if current_user.usertype != "super_admin":
        orgs_module = db.query(Module).filter_by(name="Organizations").first()
        orgs_module_id = orgs_module.id if orgs_module else None
        if not orgs_module_id or not check_org_permission(current_user.id, orgs_module_id, "can_view", db):
            raise HTTPException(status_code=403, detail="Access denied: Organizations module permission required")

    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    current_mode = org.billing_scope.code if org.billing_scope else "org_level"
    before = {"billing_scope": current_mode, "billing_hierarchy_level": org.billing_hierarchy_level}

    if body.billing_scope_code == "org_level":
        _switch_to_org_level(org, db)
        _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                             action="admin_switch_to_org_level",
                             before_json=before,
                             after_json={"billing_scope": "org_level"},
                             notes="Force-switch by super admin")

    elif body.billing_scope_code == "department_level":
        if not body.billing_hierarchy_level:
            raise HTTPException(status_code=400, detail="billing_hierarchy_level is required.")
        if not body.plan_id and not org.plan_id:
            raise HTTPException(status_code=400, detail="plan_id is required for department-level billing.")

        units_count, cancelled, _billing_end = _switch_to_dept_level(org, body.billing_hierarchy_level, body.plan_id, db)
        _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                             action="admin_switch_to_dept_level",
                             before_json=before,
                             after_json={"billing_scope": "department_level",
                                         "billing_hierarchy_level": body.billing_hierarchy_level},
                             billing_units_affected=units_count,
                             notes=f"{cancelled} pending order(s) cancelled due to hierarchy change" if cancelled else None)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown billing scope code: '{body.billing_scope_code}'.")

    db.commit()
    background_tasks.add_task(run_billing_unit_recompute_job, org_id)
    return {"message": "Billing config updated.", "billing_mode": body.billing_scope_code}


# ── GET /admin/orgs/{org_id}/plan-pricing ────────────────────────────────────

@admin_router.get("/orgs/{org_id}/plan-pricing")
def admin_get_plan_pricing(
    org_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from auth_utils import has_org_admin_role
    is_super = current_user.usertype == "super_admin"
    is_own_org_admin = (
        str(current_user.organization_id) == org_id
        and (current_user.department_id is None or has_org_admin_role(current_user, db))
    )
    if not is_super and not is_own_org_admin:
        raise HTTPException(status_code=403, detail="Super admin or org admin privileges required")

    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    plans = db.query(Plan).filter_by(isactive=True).all()
    scopes = db.query(BillingScope).all()
    result = []
    for plan in plans:
        for scope in scopes:
            override = db.query(OrgPlanPricing).filter_by(
                org_id=org.id, plan_id=plan.id, billing_scope_id=scope.id
            ).first()
            result.append({
                "plan_id": str(plan.id),
                "plan_name": plan.planname,
                "billing_scope_code": scope.code,
                "price_paise": override.price_paise if override else plan.price_paise,
                "duration_days": (override.duration_days if override and override.duration_days else plan.duration_days),
                "pricing_source": "org_specific" if override else "global_default",
            })
    return result


# ── PUT /admin/orgs/{org_id}/plan-pricing ────────────────────────────────────

@admin_router.put("/orgs/{org_id}/plan-pricing")
def admin_put_plan_pricing(
    org_id: str,
    body: List[PlanPricingRow],
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from auth_utils import has_org_admin_role
    is_super = current_user.usertype == "super_admin"
    is_own_org_admin = (
        str(current_user.organization_id) == org_id
        and (current_user.department_id is None or has_org_admin_role(current_user, db))
    )
    if not is_super and not is_own_org_admin:
        raise HTTPException(status_code=403, detail="Super admin or org admin privileges required")

    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    updated_rows = []
    for row in body:
        scope = _resolve_billing_scope(row.billing_scope_code, db)
        plan = db.query(Plan).filter_by(id=row.plan_id, isactive=True).first()
        if not plan:
            raise HTTPException(status_code=404, detail=f"Plan {row.plan_id} not found")

        existing = db.query(OrgPlanPricing).filter_by(
            org_id=org.id, plan_id=plan.id, billing_scope_id=scope.id
        ).first()
        if existing:
            existing.price_paise = row.price_paise
            existing.duration_days = row.duration_days
        else:
            existing = OrgPlanPricing(
                org_id=org.id,
                plan_id=plan.id,
                billing_scope_id=scope.id,
                price_paise=row.price_paise,
                duration_days=row.duration_days,
            )
            db.add(existing)
        updated_rows.append((existing, scope))
    db.flush()

    # Cancel stale pending orders for affected plan+scope combinations
    cancelled = 0
    for pricing_row, scope in updated_rows:
        stale_q = db.query(BillingOrder).filter(
            BillingOrder.org_id == org.id,
            BillingOrder.plan_id == pricing_row.plan_id,
            BillingOrder.status == "pending",
        )
        if scope.code == "department_level":
            stale_q = stale_q.filter(BillingOrder.department_id != None)
        else:
            stale_q = stale_q.filter(BillingOrder.department_id == None)
        for order in stale_q.all():
            order.status = "cancelled"
            order.cancellation_reason = "pricing_changed"
            cancelled += 1

    _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                         action="update_plan_pricing",
                         notes=f"{len(body)} row(s) updated; {cancelled} pending order(s) cancelled")
    db.commit()
    return {"message": f"{len(body)} pricing row(s) updated. {cancelled} stale order(s) cancelled."}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — MODE SWITCH PAYMENT API (dept → org, by org admin)
# ══════════════════════════════════════════════════════════════════════════════

class SwitchToOrgCreateOrderRequest(BaseModel):
    plan_id: str


# ── GET /billing/switch-to-org-level/preview ─────────────────────────────────

@router.get("/switch-to-org-level/preview")
def switch_to_org_preview(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    now = datetime.now(timezone.utc)
    active_depts = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org.id,
        OrgDepartment.is_billing_unit == True,
        OrgDepartment.subscription_end_date != None,
        OrgDepartment.subscription_end_date > now,
    ).all()

    return [
        {
            "dept_name": d.name,
            "dept_id": str(d.id),
            "subscription_end_date": d.subscription_end_date.isoformat(),
            "days_remaining": max(0, (d.subscription_end_date - now).days),
        }
        for d in active_depts
    ]


# ── POST /billing/switch-to-org-level/create-order ───────────────────────────

@router.post("/switch-to-org-level/create-order")
def switch_to_org_create_order(
    body: SwitchToOrgCreateOrderRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    if not org.billing_scope or org.billing_scope.code != "department_level":
        raise HTTPException(status_code=400, detail="Organisation is not in department billing mode.")

    plan = db.query(Plan).filter_by(id=body.plan_id, isactive=True).first()
    if not plan or not plan.price_paise:
        raise HTTPException(status_code=404, detail="Plan not found or has no price.")

    # Resolve org-level price override if set
    org_scope = db.query(BillingScope).filter_by(code="org_level").first()
    price_paise = plan.price_paise
    if org_scope:
        override = db.query(OrgPlanPricing).filter_by(
            org_id=org.id, plan_id=plan.id, billing_scope_id=org_scope.id
        ).first()
        if override:
            price_paise = override.price_paise

    client = _rzp()
    rz_order = client.order.create({
        "amount": price_paise,
        "currency": "INR",
        "receipt": f"sw_{str(org.id)[:8]}",
        "notes": {
            "org_id":    str(org.id),
            "org_name":  org.name,
            "plan_id":   str(plan.id),
            "plan_name": plan.planname,
            "switch":    "dept_to_org",
        },
    })

    order = BillingOrder(
        org_id=org.id,
        plan_id=plan.id,
        plan_name=plan.planname,
        razorpay_order_id=rz_order["id"],
        amount=price_paise,
        amount_paise=price_paise,
        currency="INR",
        duration_days=plan.duration_days or 365,
        status="pending",
        # department_id intentionally NULL — this is an org-level order
    )
    db.add(order)
    db.commit()

    return {
        "razorpay_key_id": RAZORPAY_KEY_ID,
        "razorpay_order_id": rz_order["id"],
        "amount": price_paise,
        "currency": "INR",
        "plan_name": plan.planname,
        "org_name": org.name,
        "contact_email": org.primary_email or "",
    }


# ── POST /billing/switch-to-org-level/verify ─────────────────────────────────

@router.post("/switch-to-org-level/verify")
def switch_to_org_verify(
    payload: VerifyRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Verify HMAC signature
    body_str = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        body_str.encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed.")

    order = db.query(BillingOrder).filter_by(
        razorpay_order_id=payload.razorpay_order_id
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if str(order.org_id) != str(current_user.organization_id):
        raise HTTPException(status_code=403, detail="Access denied.")
    if order.status == "paid":
        return {"message": "Already activated.", "status": "paid"}

    org = db.query(Organization).filter_by(id=order.org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found.")

    # Mark order paid
    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    db.flush()

    # Activate org subscription (extend from current end date if any)
    now = datetime.now(timezone.utc)
    base = max(now, org.subscription_end_date or now)
    org.subscription_end_date = base + timedelta(days=order.duration_days)
    if order.plan_id:
        org.plan_id = order.plan_id
    if org.trial_status != "converted":
        org.is_trial = False
        org.trial_status = "converted"
    org.onboarding_complete = True

    # Clear all dept billing data — no proration, no refund
    all_depts = db.query(OrgDepartment).filter_by(organization_id=org.id).all()
    for dept in all_depts:
        dept.is_billing_unit = False
        dept.subscription_end_date = None

    # Switch scope to org_level
    org_scope = db.query(BillingScope).filter_by(code="org_level").first()
    if org_scope:
        org.billing_scope_id = org_scope.id
    org.billing_hierarchy_level = None

    _write_billing_audit(
        db, org_id=org.id, actor_user=current_user,
        action="switch_to_org_level_payment",
        after_json={"billing_scope": "org_level", "subscription_end_date": org.subscription_end_date.isoformat()},
        billing_order_id=order.id,
        notes="Mode switched dept→org via payment",
    )
    db.commit()

    return {"message": "Payment verified. Organisation subscription is now active.", "status": "paid"}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — TRIAL EXPIRY BILLING SETUP WIZARD API
# ══════════════════════════════════════════════════════════════════════════════

class SetupBillingModeRequest(BaseModel):
    billing_scope_code: str
    plan_id: Optional[str] = None
    billing_hierarchy_level: Optional[int] = None


# ── POST /billing/setup-billing-mode ─────────────────────────────────────────

@router.post("/setup-billing-mode")
def setup_billing_mode(
    body: SetupBillingModeRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Called by the trial-expiry wizard (payment_token auth).
    Saves the org admin's billing mode choice without taking payment.
    For dept-level: marks billing units and unblocks the org admin.
    For org-level: no activation — payment follows via /billing/create-order.
    """
    org = _resolve_org_from_request(request, db)

    scope = db.query(BillingScope).filter_by(code=body.billing_scope_code).first()
    if not scope:
        raise HTTPException(status_code=400, detail=f"Unknown billing scope: '{body.billing_scope_code}'.")

    if body.billing_scope_code == "department_level":
        if not body.plan_id:
            raise HTTPException(status_code=400, detail="plan_id is required for department-level billing.")
        if not body.billing_hierarchy_level:
            raise HTTPException(status_code=400, detail="billing_hierarchy_level is required for department-level billing.")

        plan = db.query(Plan).filter_by(id=body.plan_id, isactive=True).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found.")

        # Mark billing units and auto-activate with plan duration
        _switch_to_dept_level(org, body.billing_hierarchy_level, plan.id, db)  # return value unused here

        # End the trial — org has committed to dept-level billing.
        # Dept users stay blocked (SUBSCRIPTION_PENDING_DEPT) until their dept pays.
        # Root user can now log in and manage department payments.
        org.onboarding_complete = True
        org.is_trial = False
        org.trial_status = "converted"

    else:
        # org_level — just save the scope choice; payment follows separately
        org.billing_scope_id = scope.id
        org.billing_hierarchy_level = None

    org_id_str = str(org.id)
    db.commit()
    if body.billing_scope_code == "department_level":
        background_tasks.add_task(run_billing_unit_recompute_job, org_id_str)
    return {"message": f"Billing mode set to '{body.billing_scope_code}'."}


# ══════════════════════════════════════════════════════════════════════════════
# POST /billing/renew-all-depts  — org admin renews all dept subscriptions
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/renew-all-depts")
def renew_all_depts(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Extend all billing-unit department subscriptions by one plan billing cycle.
    If a dept already has a future end date, the extension stacks from that date.
    If expired/null, the new cycle starts from now."""
    from auth_utils import has_org_admin_role
    if not has_org_admin_role(current_user, db):
        raise HTTPException(status_code=403, detail="Org admin role required")

    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    if not org.billing_scope or org.billing_scope.code != "department_level":
        raise HTTPException(status_code=400, detail="Organisation is not in department-level billing mode")

    plan = db.query(Plan).filter_by(id=org.plan_id, isactive=True).first() if org.plan_id else None
    if not plan or not plan.duration_days:
        raise HTTPException(status_code=400, detail="No active plan configured for this organisation")

    now = datetime.now(timezone.utc)
    billing_units = db.query(OrgDepartment).filter_by(
        organization_id=org.id, is_billing_unit=True, is_active=True
    ).all()

    renewed = 0
    for dept in billing_units:
        base = max(now, dept.subscription_end_date or now)
        dept.subscription_end_date = base + timedelta(days=plan.duration_days)
        renewed += 1

    new_end = (max(now, billing_units[0].subscription_end_date) if billing_units else now)
    _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                         action="renew_all_depts",
                         notes=f"{renewed} billing unit(s) renewed for {plan.duration_days} days",
                         billing_units_affected=renewed)
    db.commit()
    return {
        "message": f"{renewed} department subscription(s) renewed.",
        "renewed_count": renewed,
        "new_end_date": new_end.isoformat(),
        "plan_name": plan.planname,
        "duration_days": plan.duration_days,
    }


# ══════════════════════════════════════════════════════════════════════════════
# POST /billing/reset-dept-subscriptions  — clear all dept billing unit flags
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/reset-dept-subscriptions")
def reset_dept_subscriptions(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reset org to a clean slate: clears all dept billing unit flags and switches
    billing mode back to org_level so the setup wizard can be re-run from scratch."""
    from auth_utils import has_org_admin_role
    if not has_org_admin_role(current_user, db):
        raise HTTPException(status_code=403, detail="Org admin role required")

    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    # Clear all dept billing unit flags
    cleared = db.query(OrgDepartment).filter_by(
        organization_id=org.id, is_active=True
    ).update({"is_billing_unit": False, "subscription_end_date": None})

    # Reset billing mode back to org_level
    org_scope = db.query(BillingScope).filter_by(code="org_level").first()
    if org_scope:
        org.billing_scope_id = org_scope.id
    org.billing_hierarchy_level = None

    _write_billing_audit(db, org_id=org.id, actor_user=current_user,
                         action="reset_billing",
                         notes=f"Full billing reset: cleared {cleared} dept(s), switched back to org_level",
                         billing_units_affected=cleared)
    db.commit()
    return {"message": f"Billing reset. Cleared {cleared} department(s) and switched back to Organisation Level.", "cleared_count": cleared}


# ══════════════════════════════════════════════════════════════════════════════
# GET /billing/dept-billing-summary  — org admin paginated dept billing units
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/dept-billing-summary")
def get_dept_billing_summary(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    import math
    from sqlalchemy import case, func

    org = db.query(Organization).filter_by(id=current_user.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    now = datetime.now(timezone.utc)

    # Build base query
    q = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org.id,
        OrgDepartment.is_billing_unit == True,
    )

    # Server-side status filter using SQL
    if status_filter == "pending_payment":
        q = q.filter(OrgDepartment.subscription_end_date == None)
    elif status_filter == "expired":
        q = q.filter(
            OrgDepartment.subscription_end_date != None,
            OrgDepartment.subscription_end_date < now,
        )
    elif status_filter == "active":
        q = q.filter(
            OrgDepartment.subscription_end_date != None,
            OrgDepartment.subscription_end_date >= now,
        )

    # Counts across all depts (unfiltered by status_filter)
    all_q = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org.id,
        OrgDepartment.is_billing_unit == True,
    )
    active_count = all_q.filter(
        OrgDepartment.subscription_end_date != None,
        OrgDepartment.subscription_end_date >= now,
    ).count()
    expired_count = all_q.filter(
        OrgDepartment.subscription_end_date != None,
        OrgDepartment.subscription_end_date < now,
    ).count()
    pending_count = all_q.filter(OrgDepartment.subscription_end_date == None).count()

    total = q.count()
    offset = (page - 1) * page_size
    units = q.order_by(OrgDepartment.name).offset(offset).limit(page_size).all()

    def dept_status(d):
        if not d.subscription_end_date:
            return "pending_payment"
        if d.subscription_end_date < now:
            return "expired"
        return "active"

    items = []
    for d in units:
        st = dept_status(d)
        items.append({
            "dept_id": str(d.id),
            "dept_name": d.name,
            "subscription_end_date": d.subscription_end_date.isoformat() if d.subscription_end_date else None,
            "status":       st,
            "status_label": BillingStatusLabels.get(st),
            "status_color": BillingStatusColors.get(st),
            "status_icon":  BillingStatusIcons.get(st),
            "days_remaining": max(0, (d.subscription_end_date - now).days)
                              if d.subscription_end_date and d.subscription_end_date >= now else None,
            "alert_active": bool(d.subscription_end_date and 0 < (d.subscription_end_date - now).days <= 7),
        })

    total_pages = math.ceil(total / page_size) if total else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "active_count": active_count,
        "expired_count": expired_count,
        "pending_count": pending_count,
        "total_pages": total_pages,
        "has_more": page < total_pages,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/orgs/{org_id}/billing-audit  — audit log for an org
# ══════════════════════════════════════════════════════════════════════════════

@admin_router.get("/orgs/{org_id}/billing-audit")
def admin_get_billing_audit(
    org_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    import math
    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")

    q = db.query(BillingAuditLog).filter_by(org_id=org.id).order_by(BillingAuditLog.created_at.desc())
    total = q.count()
    logs = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "id": str(log.id),
                "actor_name": log.actor_name,
                "actor_usertype": log.actor_usertype,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": str(log.entity_id) if log.entity_id else None,
                "before_json": log.before_json,
                "after_json": log.after_json,
                "billing_order_id": str(log.billing_order_id) if log.billing_order_id else None,
                "billing_units_affected": log.billing_units_affected,
                "notes": log.notes,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
        "has_more": (page - 1) * page_size + page_size < total,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/billing-anomalies  — all anomalous orders (super admin)
# PATCH /admin/billing-anomalies/{order_id}/resolve  — resolve an anomaly
# ══════════════════════════════════════════════════════════════════════════════

class AnomalyResolveRequest(BaseModel):
    resolution: str  # "refund_issued" | "no_action_needed" | "pending_review"
    notes: Optional[str] = None


@admin_router.get("/billing-anomalies")
def admin_get_billing_anomalies(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    resolved: Optional[bool] = Query(None, description="true=resolved only, false=unresolved only, omit=all"),
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    import math
    q = db.query(BillingOrder).filter(BillingOrder.anomaly_flag == True)
    if resolved is not None:
        if resolved:
            q = q.filter(BillingOrder.anomaly_resolution != None)
        else:
            q = q.filter(BillingOrder.anomaly_resolution == None)
    q = q.order_by(BillingOrder.created_at.desc())
    total = q.count()
    orders = q.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "id": str(o.id),
                "org_id": str(o.org_id),
                "department_id": str(o.department_id) if o.department_id else None,
                "plan_name": o.plan_name,
                "amount_paise": o.amount_paise or o.amount,
                "status": o.status,
                "razorpay_order_id": o.razorpay_order_id,
                "razorpay_payment_id": o.razorpay_payment_id,
                "anomaly_reason": o.anomaly_reason,
                "anomaly_resolution": o.anomaly_resolution,
                "anomaly_resolved_at": o.anomaly_resolved_at.isoformat() if o.anomaly_resolved_at else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "paid_at": o.paid_at.isoformat() if o.paid_at else None,
            }
            for o in orders
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total / page_size) if total else 0,
        "has_more": (page - 1) * page_size + page_size < total,
    }


@admin_router.patch("/billing-anomalies/{order_id}/resolve")
def admin_resolve_billing_anomaly(
    order_id: str,
    body: AnomalyResolveRequest,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    order = db.query(BillingOrder).filter_by(id=order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order.anomaly_flag:
        raise HTTPException(status_code=404, detail="This order has no anomaly flag")

    valid_resolutions = {"refund_issued", "no_action_needed", "pending_review"}
    if body.resolution not in valid_resolutions:
        raise HTTPException(status_code=400, detail=f"Invalid resolution. Must be one of: {', '.join(valid_resolutions)}")

    now = datetime.now(timezone.utc)
    order.anomaly_resolution = body.resolution
    order.anomaly_resolved_at = now
    order.anomaly_resolved_by = current_user.id

    _write_billing_audit(
        db, org_id=order.org_id, actor_user=current_user,
        action="resolve_anomaly",
        entity_type="BillingOrder", entity_id=order.id,
        after_json={"anomaly_resolution": body.resolution},
        billing_order_id=order.id,
        notes=body.notes,
    )
    db.commit()
    return {"status": "ok", "order_id": order_id, "resolution": body.resolution}


# ══════════════════════════════════════════════════════════════════════════════
# GET /admin/orgs/{org_id}/billing-unit-recompute-status
# POST /admin/orgs/{org_id}/billing-unit-recompute
# ══════════════════════════════════════════════════════════════════════════════

@admin_router.get("/orgs/{org_id}/billing-unit-recompute-status")
def admin_get_recompute_status(
    org_id: str,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    return {
        "org_id": str(org.id),
        "recompute_pending": getattr(org, "billing_unit_recompute_pending", False),
        "recompute_status": getattr(org, "billing_unit_recompute_status", None),
        "recompute_started": getattr(org, "billing_unit_recompute_started", None),
        "recompute_error": getattr(org, "billing_unit_recompute_error", None),
        "recompute_retries": getattr(org, "billing_unit_recompute_retries", 0),
    }


@admin_router.post("/orgs/{org_id}/billing-unit-recompute")
def admin_trigger_recompute(
    org_id: str,
    background_tasks: BackgroundTasks,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Manually trigger a billing unit recompute for an org."""
    org = db.query(Organization).filter_by(id=org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organisation not found")
    org.billing_unit_recompute_pending = True
    org.billing_unit_recompute_status = "pending"
    org.billing_unit_recompute_retries = 0
    org.billing_unit_recompute_error = None
    db.commit()
    background_tasks.add_task(run_billing_unit_recompute_job, org_id)
    return {"message": "Recompute job dispatched.", "org_id": org_id}


# ══════════════════════════════════════════════════════════════════════════════
# Billing Reports (super admin)
# ══════════════════════════════════════════════════════════════════════════════

@admin_router.get("/reports/billing/active-departments")
def report_active_departments(
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """All dept billing units with an active (non-expired) subscription."""
    now = datetime.now(timezone.utc)
    q = db.query(OrgDepartment, Organization).join(
        Organization, Organization.id == OrgDepartment.organization_id
    ).filter(
        OrgDepartment.is_billing_unit == True,
        OrgDepartment.subscription_end_date != None,
        OrgDepartment.subscription_end_date > now,
    ).order_by(OrgDepartment.subscription_end_date.asc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "dept_id": str(dept.id),
                "dept_name": dept.name,
                "org_id": str(org.id),
                "org_name": org.name,
                "subscription_end_date": dept.subscription_end_date.isoformat() if dept.subscription_end_date else None,
                "days_remaining": max(0, (dept.subscription_end_date.date() - now.date()).days) if dept.subscription_end_date else None,
            }
            for dept, org in rows
        ],
    }


@admin_router.get("/reports/billing/unpaid-departments")
def report_unpaid_departments(
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Dept billing units with expired or no subscription."""
    now = datetime.now(timezone.utc)
    q = db.query(OrgDepartment, Organization).join(
        Organization, Organization.id == OrgDepartment.organization_id
    ).filter(
        OrgDepartment.is_billing_unit == True,
        db.query(Organization).filter(
            Organization.id == OrgDepartment.organization_id,
            Organization.billing_scope_id != None,
        ).exists(),
    ).filter(
        (OrgDepartment.subscription_end_date == None) |
        (OrgDepartment.subscription_end_date <= now)
    ).order_by(OrgDepartment.subscription_end_date.asc().nullsfirst())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "dept_id": str(dept.id),
                "dept_name": dept.name,
                "org_id": str(org.id),
                "org_name": org.name,
                "subscription_end_date": dept.subscription_end_date.isoformat() if dept.subscription_end_date else None,
                "days_overdue": max(0, (now.date() - dept.subscription_end_date.date()).days) if dept.subscription_end_date else None,
            }
            for dept, org in rows
        ],
    }


@admin_router.get("/reports/billing/revenue-by-org")
def report_revenue_by_org(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Total revenue (paid orders) grouped by organisation."""
    from sqlalchemy import func as sql_func

    q = db.query(
        Organization.id,
        Organization.name,
        sql_func.count(BillingOrder.id).label("order_count"),
        sql_func.sum(BillingOrder.amount_paise).label("total_paise"),
    ).join(BillingOrder, BillingOrder.org_id == Organization.id).filter(
        BillingOrder.status == "paid"
    )

    if from_date:
        try:
            q = q.filter(BillingOrder.paid_at >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            q = q.filter(BillingOrder.paid_at <= datetime.fromisoformat(to_date))
        except ValueError:
            pass

    q = q.group_by(Organization.id, Organization.name).order_by(
        sql_func.sum(BillingOrder.amount_paise).desc()
    )
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "org_id": str(r.id),
                "org_name": r.name,
                "order_count": r.order_count,
                "total_paise": int(r.total_paise or 0),
                "total_display": f"₹{int((r.total_paise or 0) / 100):,}",
            }
            for r in rows
        ],
    }


@admin_router.get("/reports/billing/revenue-by-dept")
def report_revenue_by_dept(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """Total revenue (paid dept orders) grouped by department."""
    from sqlalchemy import func as sql_func

    q = db.query(
        OrgDepartment.id,
        OrgDepartment.name,
        Organization.id.label("org_id"),
        Organization.name.label("org_name"),
        sql_func.count(BillingOrder.id).label("order_count"),
        sql_func.sum(BillingOrder.amount_paise).label("total_paise"),
    ).join(BillingOrder, BillingOrder.department_id == OrgDepartment.id).join(
        Organization, Organization.id == OrgDepartment.organization_id
    ).filter(BillingOrder.status == "paid")

    if from_date:
        try:
            q = q.filter(BillingOrder.paid_at >= datetime.fromisoformat(from_date))
        except ValueError:
            pass
    if to_date:
        try:
            q = q.filter(BillingOrder.paid_at <= datetime.fromisoformat(to_date))
        except ValueError:
            pass

    q = q.group_by(
        OrgDepartment.id, OrgDepartment.name, Organization.id, Organization.name
    ).order_by(sql_func.sum(BillingOrder.amount_paise).desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "dept_id": str(r.id),
                "dept_name": r.name,
                "org_id": str(r.org_id),
                "org_name": r.org_name,
                "order_count": r.order_count,
                "total_paise": int(r.total_paise or 0),
                "total_display": f"₹{int((r.total_paise or 0) / 100):,}",
            }
            for r in rows
        ],
    }


@admin_router.get("/reports/billing/renewal-forecast")
def report_renewal_forecast(
    days_ahead: int = 30,
    current_user=Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    """
    Lists subscriptions (org-level and dept-level) expiring in the next N days,
    along with the plan amount for renewal-revenue forecasting.
    """
    from sqlalchemy import func as sql_func

    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)

    # Dept-level upcoming renewals
    dept_rows = db.query(OrgDepartment, Organization).join(
        Organization, Organization.id == OrgDepartment.organization_id
    ).filter(
        OrgDepartment.is_billing_unit == True,
        OrgDepartment.subscription_end_date != None,
        OrgDepartment.subscription_end_date > now,
        OrgDepartment.subscription_end_date <= cutoff,
    ).order_by(OrgDepartment.subscription_end_date.asc()).all()

    # Org-level upcoming renewals
    org_rows = db.query(Organization).filter(
        Organization.subscription_end_date != None,
        Organization.subscription_end_date > now,
        Organization.subscription_end_date <= cutoff,
    ).order_by(Organization.subscription_end_date.asc()).all()

    items = []
    for dept, org in dept_rows:
        items.append({
            "type": "department",
            "dept_id": str(dept.id),
            "dept_name": dept.name,
            "org_id": str(org.id),
            "org_name": org.name,
            "expiry_date": dept.subscription_end_date.isoformat(),
            "days_until_expiry": (dept.subscription_end_date.date() - now.date()).days,
        })
    for org in org_rows:
        items.append({
            "type": "org",
            "org_id": str(org.id),
            "org_name": org.name,
            "expiry_date": org.subscription_end_date.isoformat(),
            "days_until_expiry": (org.subscription_end_date.date() - now.date()).days,
        })

    # Sort combined list by expiry
    items.sort(key=lambda x: x["expiry_date"])

    return {
        "days_ahead": days_ahead,
        "total": len(items),
        "items": items,
    }
