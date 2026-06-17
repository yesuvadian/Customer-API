"""
trigger_tester_assignment_email.py
====================================
End-to-end trigger: creates a real testing request, submits it, assigns a
tester via the live API, then immediately flushes the notification queue so
the tester-assigned email (with kit availability) is dispatched right away.

Usage:
    python trigger_tester_assignment_email.py
    python trigger_tester_assignment_email.py --tester-email yesu@cogniwatt.com

Flow:
    1. Login as org admin
    2. Pick equipment + tester from the DB
    3. POST /testing_requests/  → create draft
    4. PUT  /{id}/submit        → move to "submitted"
    5. PUT  /{id}/assign        → assign tester  (fires notify_tester_assigned)
    6. Flush notification queue → email sent immediately
"""
import sys
import argparse
import requests

from database import SessionLocal
from models import Equipment, User, NotificationLog
from services.notification_service import NotificationService
from sqlalchemy import desc

API_BASE = "http://localhost:8000"
HEADERS  = {"Content-Type": "application/json"}


def step(msg): print(f"\n[STEP] {msg}")
def ok(msg):   print(f"[OK]   {msg}")
def info(msg): print(f"[INFO] {msg}")
def warn(msg): print(f"[WARN] {msg}")
def fail(msg): print(f"[ERROR] {msg}"); sys.exit(1)


# ── 1. Login ─────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> str:
    step(f"Login as {email}")
    r = requests.post(f"{API_BASE}/auth/login",
                      json={"email": email, "password": password}, timeout=10)
    if r.status_code != 200:
        fail(f"Login failed ({r.status_code}): {r.text[:200]}")
    token = r.json().get("access_token")
    if not token:
        fail(f"No access_token in response: {r.text[:200]}")
    ok("Logged in")
    return token


# ── 2. Resolve equipment + tester from DB ─────────────────────────────────────

def resolve_subjects(tester_email: str):
    step("Resolving equipment and tester from DB")
    db = SessionLocal()
    try:
        # Pick first active equipment that isn't a testing kit
        eq = db.query(Equipment).filter(
            Equipment.status == "active",
            Equipment.equipment_type_id != 42,  # exclude Testing Kit type
        ).first()
        if not eq:
            fail("No active equipment found in DB")

        tester = db.query(User).filter(User.email == tester_email).first()
        if not tester:
            fail(f"User {tester_email} not found in DB")

        info(f"Equipment : {eq.ueic} (type_id={eq.equipment_type_id}, dept={eq.department_id})")
        info(f"Tester    : {tester.email} (id={tester.id})")

        return {
            "equipment_id":    str(eq.id),
            "equipment_type_id": eq.equipment_type_id,
            "department_id":   str(eq.department_id) if eq.department_id else None,
            "organization_id": str(eq.organization_id) if eq.organization_id else None,
            "tester_id":       str(tester.id),
            "tester_email":    tester.email,
        }
    finally:
        db.close()


# ── 3. Create draft testing request ──────────────────────────────────────────

def create_request(token: str, subjects: dict) -> str:
    step("Creating testing request (draft)")
    auth = {**HEADERS, "Authorization": f"Bearer {token}"}
    payload = {
        "title":           "Kit Email Test Request",
        "description":     "Auto-generated to test tester-assignment email with kit availability",
        "equipment_id":    subjects["equipment_id"],
        "equipment_type_id": subjects["equipment_type_id"],
        "organization_id": subjects["organization_id"],
        "department_id":   subjects["department_id"],
        "request_category": "test",
    }
    r = requests.post(f"{API_BASE}/testing_requests/", json=payload, headers=auth, timeout=15)
    if r.status_code not in (200, 201):
        fail(f"Create failed ({r.status_code}): {r.text[:300]}")
    tr_id = r.json()["id"]
    ok(f"Created TR id={tr_id[:8]}…  status={r.json().get('status')}")
    return tr_id


# ── 4. Submit ─────────────────────────────────────────────────────────────────

def submit_request(token: str, tr_id: str):
    step("Submitting testing request")
    auth = {**HEADERS, "Authorization": f"Bearer {token}"}
    r = requests.put(f"{API_BASE}/testing_requests/{tr_id}/submit", headers=auth, timeout=15)
    if r.status_code not in (200, 201):
        fail(f"Submit failed ({r.status_code}): {r.text[:300]}")
    ok(f"Submitted — status={r.json().get('status')}")


# ── 5. Assign tester ──────────────────────────────────────────────────────────

def assign_tester(token: str, tr_id: str, tester_id: str):
    step(f"Assigning tester {tester_id[:8]}…")
    auth = {**HEADERS, "Authorization": f"Bearer {token}"}
    r = requests.put(
        f"{API_BASE}/testing_requests/{tr_id}/assign",
        json={"tester_id": tester_id},
        headers=auth,
        timeout=15,
    )
    if r.status_code not in (200, 201):
        fail(f"Assign failed ({r.status_code}): {r.text[:300]}")
    ok(f"Tester assigned — status={r.json().get('status')}")


# ── 6. Flush queue + show result ──────────────────────────────────────────────

def flush_and_report(tr_id: str):
    step("Flushing notification queue")
    from uuid import UUID
    from models import TestingRequest, NotificationLog as NL
    db = SessionLocal()
    try:
        tr = db.query(TestingRequest).filter(TestingRequest.id == UUID(tr_id)).first()
        if not tr:
            warn("Could not reload TR for kit preview")
        else:
            svc = NotificationService(db)
            kit_data = svc._build_kit_availability(tr)
            kits = kit_data.get("required_kits", [])
            if kits:
                info(f"Kit availability ({len(kits)} type(s)):")
                for k in kits:
                    if k["available_at_station"]:
                        status = f"{k['count_at_station']} unit(s) at station"
                    elif k["nearest_location"]:
                        status = f"nearest: {k['nearest_location']}"
                    else:
                        status = "not available nearby"
                    print(f"         [{'req' if k['is_required'] else 'opt'}] {k['kit_type']} -> {status}")
            else:
                info("No kit mappings for this equipment type — email will omit kit table")

            # Check whether the server-side notify already created recipient rows.
            # If not (server ran old buggy code), fire it locally from the fixed module.
            existing_email_logs = (
                db.query(NL)
                .filter(
                    NL.source_id == UUID(tr_id),
                    NL.event_type == "tester_assigned",
                    NL.channel == "email",
                )
                .all()
            )
            has_pending_recipients = any(
                r.delivery_status == "pending"
                for log in existing_email_logs
                for r in (log.recipients or [])
            )
            if not has_pending_recipients:
                info("Server-side notify had no recipients — firing tester_assigned locally")
                try:
                    svc.notify_tester_assigned(tr)
                    db.commit()
                    info("Local notify_tester_assigned() succeeded")
                except Exception as _ne:
                    warn(f"Local notify_tester_assigned() failed: {_ne}")

            svc.process_pending_notifications()

        # Report on the notification logs for this TR
        logs = (
            db.query(NotificationLog)
            .filter(NotificationLog.source_id == UUID(tr_id))
            .order_by(desc(NotificationLog.cts))
            .all()
        )
        print()
        info("Notification log:")
        for l in logs:
            print(f"  channel={l.channel:6s}  status={l.status:10s}  "
                  f"to={l.recipient_email or '(batch)'}  err={l.error_message or '-'}")

    finally:
        db.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create TR and trigger tester-assigned email")
    parser.add_argument("--tester-email",    default="yesu@cogniwatt.com", help="Tester's email (must exist in DB)")
    parser.add_argument("--admin-email",     default="orgadmin@utility.com")
    parser.add_argument("--admin-password",  default="Kptcl@2026")
    args = parser.parse_args()

    print("=" * 60)
    print("  Tester Assignment Email — Full API Flow")
    print("=" * 60)

    token    = login(args.admin_email, args.admin_password)
    subjects = resolve_subjects(args.tester_email)
    tr_id    = create_request(token, subjects)
    submit_request(token, tr_id)
    assign_tester(token, tr_id, subjects["tester_id"])
    flush_and_report(tr_id)

    print()
    print("=" * 60)
    print(f"  Done — check inbox: {args.tester_email}")
    print("=" * 60)


if __name__ == "__main__":
    main()
