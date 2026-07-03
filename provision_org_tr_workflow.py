"""
Provision TR workflow engine for an existing org that was registered
before auto-provisioning was added.

Usage:
    python provision_org_tr_workflow.py <org_id>
    python provision_org_tr_workflow.py a5c9b736-ea20-44b2-b21a-b79cc7677bc9
"""
import sys
from database import SessionLocal
from services.organization_service import OrganizationService


def run(org_id: str):
    db = SessionLocal()
    try:
        svc = OrganizationService(db)
        svc._provision_tr_workflow(org_id)
        db.commit()
        print(f"Done — TR workflow provisioned for org {org_id}")
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python provision_org_tr_workflow.py <org_id>")
        sys.exit(1)
    run(sys.argv[1])
