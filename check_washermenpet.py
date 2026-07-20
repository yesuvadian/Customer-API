import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from database import SessionLocal
from models import OrgDepartment, User, BillingOrder

db = SessionLocal()
try:
    user = db.query(User).filter_by(email="aeje.washermenpet@utility.com").first()

    # Walk the user's dept chain upward
    print(f"Dept chain for user (dept_id={user.department_id}):")
    dept_id = user.department_id
    seen = set()
    while dept_id and dept_id not in seen:
        seen.add(dept_id)
        d = db.query(OrgDepartment).filter_by(id=dept_id).first()
        if not d:
            break
        print(f"  {d.name} | depth? | is_billing_unit={d.is_billing_unit} | sub_end={d.subscription_end_date}")
        dept_id = d.parent_department_id

    # Check the two dept IDs from orders
    print(f"\nDept 6969847e (first 3 orders):")
    d = db.query(OrgDepartment).filter_by(id="6969847e-b77b-45fa-bedf-9883064be55d").first()
    print(f"  {d.name if d else 'NOT FOUND'} | is_billing_unit={d.is_billing_unit if d else '-'} | sub_end={d.subscription_end_date if d else '-'}")

    print(f"\nDept 2f00a996 (4th order - likely Washermenpet SS):")
    d = db.query(OrgDepartment).filter_by(id="2f00a996-3a0e-478c-aec1-1532552b339a").first()
    print(f"  {d.name if d else 'NOT FOUND'} | is_billing_unit={d.is_billing_unit if d else '-'} | sub_end={d.subscription_end_date if d else '-'}")

finally:
    db.close()
