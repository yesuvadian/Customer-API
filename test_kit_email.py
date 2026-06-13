"""
Test: tester_assigned email with kit availability section.

Usage:
    python test_kit_email.py
    python test_kit_email.py --to override@email.com
    python test_kit_email.py --request-id <uuid>

What it does:
  1. Finds the most recent TestingRequest that has an assigned_tester_id
     (or uses --request-id if supplied).
  2. Calls NotificationService.notify_tester_assigned() directly.
  3. The notification dispatcher sends a real email via SMTP.
"""
import sys
import argparse
from uuid import UUID

from database import SessionLocal
from models import TestingRequest
from services.notification_service import NotificationService


def run(request_id: str | None, override_email: str | None):
    db = SessionLocal()
    try:
        if request_id:
            tr = db.query(TestingRequest).filter(
                TestingRequest.id == UUID(request_id)
            ).first()
            if not tr:
                print(f"[ERROR] TestingRequest {request_id} not found")
                sys.exit(1)
        else:
            # Pick the most recent request that has an assigned tester
            tr = (
                db.query(TestingRequest)
                .filter(TestingRequest.assigned_tester_id.isnot(None))
                .order_by(TestingRequest.cts.desc())
                .first()
            )
            if not tr:
                print("[ERROR] No TestingRequest with an assigned tester found in DB.")
                print("        Assign a tester via the app first, then re-run.")
                sys.exit(1)

        print(f"[INFO] Using request: {tr.request_number or tr.id}")
        print(f"       Equipment    : {tr.equipment.ueic if tr.equipment else 'N/A'}")
        print(f"       Tester       : {tr.assigned_tester.email if tr.assigned_tester else 'N/A'}")
        print(f"       Dept         : {tr.department_id}")

        # If override email is given, temporarily patch the tester email
        original_email = None
        if override_email and tr.assigned_tester:
            original_email = tr.assigned_tester.email
            tr.assigned_tester.email = override_email
            print(f"[INFO] Email overridden -> {override_email}")

        # Build kit data preview before firing
        svc = NotificationService(db)
        kit_data = svc._build_kit_availability(tr)
        kits = kit_data.get("required_kits", [])
        if kits:
            print(f"\n[INFO] Kit availability ({len(kits)} kit type(s)):")
            for k in kits:
                status = "at station" if k["available_at_station"] else (
                    f"nearest: {k['nearest_location']}" if k["nearest_location"] else "not available"
                )
                print(f"       - {k['kit_type']} ({'required' if k['is_required'] else 'optional'}) -> {status}")
        else:
            print("\n[INFO] No kit requirements mapped for this equipment type.")
            print("       The email will still be sent without a kit table.")

        print("\n[INFO] Firing notify_tester_assigned ...")
        svc.notify_tester_assigned(tr)

        # Flush pending notifications immediately
        print("[INFO] Running notification dispatch ...")
        svc.process_pending_notifications()

        print("\n[OK] Done — check the tester's inbox.")
        if override_email:
            print(f"     Email was directed to: {override_email}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test kit availability email")
    parser.add_argument("--request-id", help="UUID of a specific TestingRequest")
    parser.add_argument("--to", help="Override recipient email (for testing)")
    args = parser.parse_args()
    run(args.request_id, args.to)
