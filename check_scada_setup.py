from database import get_db
from sqlalchemy import text

db = next(get_db())

# Check equipment
eq = db.execute(text("SELECT id, name, organization_id FROM public.equipment LIMIT 10")).fetchall()
print(f"\nEquipment ({len(eq)} shown):")
for r in eq:
    print(f"  {r.id}  {r.name}  org={r.organization_id}")

# Check scada_tag_map
tags = db.execute(text("SELECT * FROM public.scada_tag_map LIMIT 20")).fetchall()
print(f"\nScada tag map ({len(tags)} rows):")
for r in tags:
    print(f"  {r}")

# Check organizations
orgs = db.execute(text("SELECT id, name FROM public.organizations LIMIT 5")).fetchall()
print(f"\nOrganizations:")
for r in orgs:
    print(f"  {r.id}  {r.name}")

db.close()
