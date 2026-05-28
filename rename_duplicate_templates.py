#!/usr/bin/env python3
"""Rename duplicate test templates to be more specific"""
from database import get_db
from sqlalchemy import text
import json

db = next(get_db())

# Get all templates
templates = db.execute(text("""
    SELECT id, template_key, template_data
    FROM org_test_templates
    ORDER BY template_data->>'equipment_type', template_data->>'name'
""")).fetchall()

print("=" * 80)
print("DUPLICATE TEMPLATE RENAMING")
print("=" * 80)

# Group by name to find duplicates
from collections import defaultdict
templates_by_name = defaultdict(list)

for t in templates:
    data = t.template_data
    name = data.get('name', 'Unknown')
    templates_by_name[name].append(t)

# Find and rename duplicates
updates = []
for name, template_list in templates_by_name.items():
    if len(template_list) > 1:
        print(f"\nFound {len(template_list)} duplicates for: {name}")
        for t in template_list:
            data = t.template_data
            category = data.get('category', 'Unknown')
            old_name = data.get('name')

            # Create new name with category
            if category and category not in old_name:
                new_name = f"{old_name} - {category}"
                data['name'] = new_name

                updates.append({
                    'id': t.id,
                    'old_name': old_name,
                    'new_name': new_name,
                    'category': category,
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

# Ask for confirmation
response = input("\nProceed with renaming? (yes/no): ")

if response.lower() != 'yes':
    print("Aborted.")
    db.close()
    exit(0)

# Apply updates
print("\nApplying updates...")
for update in updates:
    db.execute(
        text("UPDATE org_test_templates SET template_data = :data WHERE id = :id"),
        {"id": update['id'], "data": json.dumps(update['new_data'])}
    )
    print(f"✓ Renamed: {update['old_name']} → {update['new_name']}")

db.commit()
print(f"\n✓ Successfully renamed {len(updates)} templates")
db.close()
