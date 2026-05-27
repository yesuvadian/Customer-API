from database import get_db
from sqlalchemy import text

db = next(get_db())

result = db.execute(text("""
    SELECT id, template_name, template_key, activity_category
    FROM org_test_templates
    WHERE template_name LIKE '%Routine Maintenance%'
    AND template_name LIKE '%Battery%'
    ORDER BY template_name
""")).fetchall()

print("Duplicate Battery Maintenance templates:")
for r in result:
    print(f"  ID: {r.id}")
    print(f"  Name: {r.template_name}")
    print(f"  Key: {r.template_key}")
    print(f"  Category: {r.activity_category}")
    print()

db.close()
