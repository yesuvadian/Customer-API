"""
Cleanup a partial/test org registration by removing all related data in FK-safe order.

Usage:
    python cleanup_org.py <org_id>
    python cleanup_org.py <org_id> --dry-run
    python cleanup_org.py <org_id> --reprovision   # cleanup + re-provision TR workflows
"""

import sys
from sqlalchemy import text
from database import SessionLocal


def cleanup_org(org_id: str, dry_run: bool = False) -> None:
    db = SessionLocal()
    try:
        print(f"{'[DRY RUN] ' if dry_run else ''}Cleaning org: {org_id}\n")

        # Each step: count via SELECT, then DELETE FROM (same WHERE clause)
        steps = [
            # ── TR Workflow runtime (audit_logs & stage_instances cascade from instances) ──
            ("tr_wf_audit_logs",
             "SELECT id FROM tr_wf_audit_logs WHERE wf_instance_id IN "
             "(SELECT id FROM tr_wf_instances WHERE org_id = :oid)"),

            ("tr_wf_stage_instances",
             "SELECT id FROM tr_wf_stage_instances WHERE wf_instance_id IN "
             "(SELECT id FROM tr_wf_instances WHERE org_id = :oid)"),

            ("tr_wf_instances",
             "SELECT id FROM tr_wf_instances WHERE org_id = :oid"),

            ("tr_wf_stage_roles",
             "SELECT id FROM tr_wf_stage_roles WHERE stage_id IN "
             "(SELECT s.id FROM tr_wf_stages s "
             "JOIN tr_wf_definitions d ON s.wf_definition_id = d.id WHERE d.org_id = :oid)"),

            ("tr_wf_stage_transitions",
             "SELECT id FROM tr_wf_stage_transitions WHERE from_stage_id IN "
             "(SELECT s.id FROM tr_wf_stages s "
             "JOIN tr_wf_definitions d ON s.wf_definition_id = d.id WHERE d.org_id = :oid)"),

            ("tr_wf_stages",
             "SELECT id FROM tr_wf_stages WHERE wf_definition_id IN "
             "(SELECT id FROM tr_wf_definitions WHERE org_id = :oid)"),

            ("tr_wf_statuses",
             "SELECT id FROM tr_wf_statuses WHERE wf_definition_id IN "
             "(SELECT id FROM tr_wf_definitions WHERE org_id = :oid)"),

            ("tr_wf_routing_rules",    "SELECT id FROM tr_wf_routing_rules WHERE org_id = :oid"),
            ("tr_wf_routing_defaults", "SELECT id FROM tr_wf_routing_defaults WHERE org_id = :oid"),
            ("tr_wf_definitions",      "SELECT id FROM tr_wf_definitions WHERE org_id = :oid"),

            # ── Testing requests & children (before equipment & departments) ──
            ("test_session_reading_images",
             "SELECT id FROM test_session_reading_images WHERE reading_id IN "
             "(SELECT id FROM test_session_readings WHERE test_session_id IN "
             "(SELECT id FROM test_sessions WHERE testing_request_id IN "
             "(SELECT id FROM testing_requests WHERE organization_id = :oid)))"),

            ("test_session_readings",
             "SELECT id FROM test_session_readings WHERE test_session_id IN "
             "(SELECT id FROM test_sessions WHERE testing_request_id IN "
             "(SELECT id FROM testing_requests WHERE organization_id = :oid))"),

            ("test_result_images",
             "SELECT id FROM test_result_images WHERE test_result_id IN "
             "(SELECT id FROM test_results WHERE testing_request_id IN "
             "(SELECT id FROM testing_requests WHERE organization_id = :oid))"),

            ("test_results",
             "SELECT id FROM test_results WHERE testing_request_id IN "
             "(SELECT id FROM testing_requests WHERE organization_id = :oid)"),

            ("test_sessions",
             "SELECT id FROM test_sessions WHERE testing_request_id IN "
             "(SELECT id FROM testing_requests WHERE organization_id = :oid)"),

            ("testing_requests",       "SELECT id FROM testing_requests WHERE organization_id = :oid"),

            # ── Equipment & kits ──────────────────────────────────────────────
            ("equipment",              "SELECT id FROM equipment WHERE organization_id = :oid"),

            # ── Org RBAC ──────────────────────────────────────────────────────
            ("org_user_roles",
             "SELECT id FROM org_user_roles WHERE org_role_id IN "
             "(SELECT id FROM org_roles WHERE organization_id = :oid)"),

            ("org_role_permissions",
             "SELECT id FROM org_role_permissions WHERE org_role_id IN "
             "(SELECT id FROM org_roles WHERE organization_id = :oid)"),

            ("org_roles",              "SELECT id FROM org_roles WHERE organization_id = :oid"),

            # ── Onboarding & departments ──────────────────────────────────────
            ("org_onboarding_steps",   "SELECT id FROM org_onboarding_steps WHERE organization_id = :oid"),
            ("org_departments",        "SELECT id FROM org_departments WHERE organization_id = :oid"),

            # ── Document requests & imports ───────────────────────────────────
            ("document_requests",      "SELECT id FROM document_requests WHERE org_id = :oid"),
            ("pending_data_imports",   "SELECT id FROM pending_data_imports WHERE organization_id = :oid"),

            # ── Users & org ───────────────────────────────────────────────────
            ("notification_log",       "SELECT id FROM notification_log WHERE organization_id = :oid"),
            ("users",                  "SELECT id FROM users WHERE organization_id = :oid"),
            ("organizations",          "SELECT id FROM organizations WHERE id = :oid"),
        ]

        for label, select_sql in steps:
            count = db.execute(text(f"SELECT COUNT(*) FROM ({select_sql}) _c"), {"oid": org_id}).scalar()
            print(f"  {label}: {count} row(s)")
            if not dry_run and count:
                if label == "users":
                    # Null FK back-references on org before deleting users
                    db.execute(
                        text("UPDATE organizations SET created_by = NULL, modified_by = NULL WHERE id = :oid"),
                        {"oid": org_id},
                    )
                delete_sql = select_sql.replace("SELECT id FROM ", "DELETE FROM ", 1)
                db.execute(text(delete_sql), {"oid": org_id})

        if not dry_run:
            db.commit()
            print("\nDone — all rows deleted and committed.")
        else:
            db.rollback()
            print("\n[DRY RUN] No changes made.")

    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        raise
    finally:
        db.close()


def reprovision_org(org_id: str) -> None:
    from services.organization_service import OrganizationService
    db = SessionLocal()
    try:
        svc = OrganizationService(db)
        svc._provision_tr_workflow(org_id)
        db.commit()
        print(f"\nDone — TR workflows re-provisioned for org {org_id}")
    except Exception as e:
        db.rollback()
        print(f"\nERROR during re-provision: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cleanup_org.py <org_id> [--dry-run] [--reprovision]")
        sys.exit(1)

    oid       = sys.argv[1]
    dry       = "--dry-run" in sys.argv
    reprovision = "--reprovision" in sys.argv

    if not dry:
        confirm = input(f"Delete ALL data for org {oid}? Type YES to confirm: ")
        if confirm.strip() != "YES":
            print("Aborted.")
            sys.exit(0)

    cleanup_org(oid, dry_run=dry)

    if reprovision and not dry:
        print("\nRe-provisioning TR workflows...")
        reprovision_org(oid)
