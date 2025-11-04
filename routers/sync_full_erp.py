# erp_sync.py
import base64
import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from config import ERP_API_KEY, ERP_RETRY_COUNT, ERP_RETRY_DELAY, ERP_TIMEOUT, ERP_URL
import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from database import get_db
from models import (
    User,
    UserAddress,
    CompanyBankInfo,
    CompanyBankDocument,
    CompanyTaxInfo,
    CompanyTaxDocument,
)

router = APIRouter(prefix="/erp")


def build_vendor_payload(user: User) -> Dict[str, Any]:
    """
    Build payload: vendor + addresses + tax_info + banks (all) + documents (base64).
    Includes both bank and tax documents.
    """
    vendor = {
        "local_id": str(user.id),
        "external_id": user.erp_external_id,
        "email": user.email,
        "firstname": user.firstname,
        "lastname": user.lastname,
        "phone_number": user.phone_number,
        "plan_id": str(user.plan_id) if user.plan_id else None,
        "isactive": bool(user.isactive),
    }

    # === Addresses ===
    addresses = []
    for a in user.addresses:
        addresses.append({
            "local_id": str(a.id),
            "external_id": a.erp_external_id,
            "type": getattr(a.address_type, "value", str(a.address_type)),
            "address_line1": a.address_line1,
            "address_line2": a.address_line2,
            "city": a.city,
            "state_id": a.state_id,
            "country_id": a.country_id,
            "postal_code": a.postal_code,
            "latitude": float(a.latitude) if a.latitude is not None else None,
            "longitude": float(a.longitude) if a.longitude is not None else None,
            "is_primary": bool(a.is_primary),
        })

    # === Tax Info + Documents ===
    taxes = []
    for t in getattr(user, "tax_info", []) or []:
        tax_docs = []
        for doc in getattr(t, "documents", []) or []:
            base64_str = None
            if doc.file_data:
                base64_str = base64.b64encode(doc.file_data).decode("utf-8")
            tax_docs.append({
                "local_id": str(doc.id),
                "external_id": doc.erp_external_id,
                "filename": doc.file_name,
                "file_type": doc.file_type,
                "document_type": "TAX_DOC",
                "base64": base64_str,
            })

        taxes.append({
            "local_id": str(t.id),
            "external_id": t.erp_external_id,
            "pan": t.pan,
            "gstin": t.gstin,
            "tan": t.tan,
            "financial_year": t.financial_year,
            "documents": tax_docs,
        })

    # === Banks + Documents ===
    banks = []
    for b in getattr(user, "bank_info", []) or []:
        bank_docs = []
        for doc in getattr(b, "documents", []) or []:
            base64_str = None
            if doc.file_data:
                base64_str = base64.b64encode(doc.file_data).decode("utf-8")
            bank_docs.append({
                "local_id": str(doc.id),
                "external_id": doc.erp_external_id,
                "filename": doc.file_name,
                "file_type": doc.file_type,
                "document_type": getattr(doc.document_type, "name", str(doc.document_type)),
                "base64": base64_str,
            })

        banks.append({
            "local_id": str(b.id),
            "external_id": b.erp_external_id,
            "account_holder_name": b.account_holder_name,
            "account_number": b.account_number,
            "account_type": b.account_type,
            "ifsc": b.ifsc,
            "bank_name": b.bank_name,
            "branch_name": b.branch_name,
            "is_primary": bool(b.is_primary),
            "status": getattr(b.status, "name", str(b.status)),
            "documents": bank_docs,
        })

    payload = {
        "vendor": vendor,
        "addresses": addresses,
        "tax_info": taxes,
        "banks": banks,
    }
    return payload


async def post_to_erp(payload: Dict[str, Any]) -> httpx.Response:
    headers = {"Content-Type": "application/json"}
    if ERP_API_KEY:
        headers["Authorization"] = f"Bearer {ERP_API_KEY}"
    async with httpx.AsyncClient(timeout=ERP_TIMEOUT) as client:
        return await client.post(ERP_URL, json=payload, headers=headers)


def apply_erp_mapping(db: Session, user: User, resp_json: Dict[str, Any]) -> None:
    """Apply ERP response mapping to local records."""
    now = datetime.now(timezone.utc)

    vendor_id = resp_json.get("vendor_external_id") or resp_json.get("external_id")
    if vendor_id:
        user.erp_external_id = vendor_id

    user.erp_sync_status = "success"
    user.erp_last_sync_at = now
    user.erp_error_message = None
    db.add(user)

    # addresses
    for addr_map in resp_json.get("addresses", []):
        local_id = str(addr_map.get("local_id"))
        ext = addr_map.get("external_id")
        for a in user.addresses:
            if str(a.id) == local_id:
                a.erp_external_id = ext
                a.erp_sync_status = "success"
                a.erp_last_sync_at = now
                db.add(a)

    # banks
    bank_maps = resp_json.get("banks")
    if isinstance(bank_maps, dict):
        bank_maps = [bank_maps]
    for bm in bank_maps or []:
        local_id = str(bm.get("local_id"))
        ext = bm.get("external_id")
        for b in user.bank_info:
            if str(b.id) == local_id:
                b.erp_external_id = ext
                b.erp_sync_status = "success"
                b.erp_last_sync_at = now
                db.add(b)

    # tax info
    for tax_map in resp_json.get("tax_info", []):
        local_id = str(tax_map.get("local_id"))
        ext = tax_map.get("external_id")
        for t in user.tax_info:
            if str(t.id) == local_id:
                t.erp_external_id = ext
                t.erp_sync_status = "success"
                t.erp_last_sync_at = now
                db.add(t)

    # documents (both tax + bank)
    for doc_map in resp_json.get("documents", []):
        local_doc = str(doc_map.get("local_id"))
        ext_doc = doc_map.get("external_id")
        # bank docs
        for b in user.bank_info:
            for d in b.documents:
                if str(d.id) == local_doc:
                    d.erp_external_id = ext_doc
                    d.erp_sync_status = "success"
                    d.erp_last_sync_at = now
                    db.add(d)
        # tax docs
        for t in user.tax_info:
            for d in t.documents:
                if str(d.id) == local_doc:
                    d.erp_external_id = ext_doc
                    d.erp_sync_status = "success"
                    d.erp_last_sync_at = now
                    db.add(d)


@router.post("/sync/vendors")
async def sync_vendors_to_erp(db: Session = Depends(get_db)):
    """Sync vendors (users where plan_id IS NOT NULL) with ERP."""
    pending_users: List[User] = db.query(User).filter(
        User.plan_id.isnot(None),
        User.erp_sync_status == "pending"
    ).all()

    if not pending_users:
        return {"message": "No pending vendors to sync"}

    synced = 0
    for user in pending_users:
        payload = build_vendor_payload(user)
        resp = None
        last_exc = None

        for attempt in range(max(1, ERP_RETRY_COUNT or 1)):
            try:
                resp = await post_to_erp(payload)
                break
            except Exception as e:
                last_exc = e
                await asyncio.sleep(ERP_RETRY_DELAY or 1)

        now = datetime.now(timezone.utc)

        if resp is None:
            user.erp_sync_status = "failed"
            user.erp_error_message = str(last_exc) or "No response"
            user.erp_last_sync_at = now
            db.add(user)
            db.commit()
            continue

        try:
            if 200 <= resp.status_code < 300:
                resp_json = {}
                try:
                    resp_json = resp.json()
                except Exception:
                    pass
                apply_erp_mapping(db, user, resp_json)
                db.commit()
                synced += 1
            else:
                user.erp_sync_status = "failed"
                user.erp_error_message = f"ERP HTTP {resp.status_code}: {resp.text}"
                user.erp_last_sync_at = now
                db.add(user)
                db.commit()
        except Exception as e:
            db.rollback()
            user.erp_sync_status = "failed"
            user.erp_error_message = str(e)
            user.erp_last_sync_at = now
            db.add(user)
            db.commit()

    return {"attempted": len(pending_users), "synced": synced}
