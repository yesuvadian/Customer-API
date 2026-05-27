#!/usr/bin/env python3
"""Rename duplicate test templates using category from category_details"""
from database import get_db
from sqlalchemy import text
import json

db = next(get_db())

# Get templates with category info from category_details
templates = db.execute(text("""
    SELECT
        ott.id,
        ott.template_key,
        ott.template_data,
        ott.test_type_id,
        cd.name as test_type_name
    FROM org_test_templates ott
    LEFT JOIN "CategoryDetails" cd ON ott.test_type_id = cd.id
    ORDER BY ott.template_data->>'name'
""")).fetchall()

print("=" * 80)
print("DUPLICATE TEMPLATE RENAMING")
print("=" * 80)

# Group by name to find duplicates
from collections import defaultdict
templates_by_name = defaultdict(list)

for t in templates:
    data = t.template_data
    name = data.get('name')
    if name:
        templates_by_name[name].append(t)

# Find and rename duplicates
updates = []
for name, template_list in templates_by_name.items():
    if len(template_list) > 1:
        print(f"\nFound {len(template_list)} duplicates for: {name}")
        for t in template_list:
            data = dict(t.template_data)
            test_type = t.test_type_name or 'Unknown Type'
            old_name = data.get('name')

            # Create new name with test type
            if test_type and test_type not in old_name:
                new_name = f"{old_name} - {test_type}"
                data['name'] = new_name

                updates.append({
                    'id': t.id,
                    'old_name': old_name,
                    'new_name': new_name,
                    'test_type': test_type,
                    'new_data': data
                })

                print(f"  [RENAME] {old_name}")
                print(f"      TO: {new_name}")

if not updates:
    print("\nNo duplicates found that need renaming.")
    db.close()
    exit(0)

print("\n" + "=" * 80)
print(f"Found {len(updates)} templates to rename")
print("=" * 80)
print("\nProceeding with renaming...")

# Apply updates
print("\nApplying updates...")
for update in updates:
    db.execute(
        text("UPDATE org_test_templates SET template_data = :data WHERE id = :id"),
        {"id": update['id'], "data": json.dumps(update['new_data'])}
    )
    print(f"[OK] {update['old_name']} -> {update['new_name']}")

db.commit()
print(f"\n[DONE] Successfully renamed {len(updates)} templates")
db.close()
