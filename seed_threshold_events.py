#!/usr/bin/env python3
"""Seed threshold event types for notification system"""
from database import get_db
from models import NotificationEventCatalogue
import uuid

db = next(get_db())

events = [
    {
        "event_type": "test_result_normal",
        "label": "Test Result - Normal",
        "description": "Test completed successfully with all values in normal range",
        "group_name": "Testing",
        "organization_id": None,  # Global event
        "is_active": True,
        "context_vars": ["equipment_name", "equipment_type", "test_type_name", "request_number", "tester_name", "substation_name"],
        "default_roles": []
    },
    {
        "event_type": "test_result_alert",
        "label": "Test Result - Alert",
        "description": "Test completed with one or more values in alert/warning range",
        "group_name": "Testing",
        "organization_id": None,
        "is_active": True,
        "context_vars": ["equipment_name", "equipment_type", "test_type_name", "request_number", "tester_name", "substation_name"],
        "default_roles": ["EE TLSS"]
    },
    {
        "event_type": "test_result_critical",
        "label": "Test Result - Critical",
        "description": "Test completed with one or more values in critical/failure range",
        "group_name": "Testing",
        "organization_id": None,
        "is_active": True,
        "context_vars": ["equipment_name", "equipment_type", "test_type_name", "request_number", "tester_name", "substation_name"],
        "default_roles": ["EE TLSS", "Department Head"]
    }
]

print("Seeding threshold event types...")
for event_data in events:
    # Check if exists
    existing = db.query(NotificationEventCatalogue).filter(
        NotificationEventCatalogue.event_type == event_data["event_type"],
        NotificationEventCatalogue.organization_id.is_(None)
    ).first()

    if existing:
        print(f"  [SKIP] {event_data['event_type']} already exists")
    else:
        event = NotificationEventCatalogue(
            id=uuid.uuid4(),
            **event_data
        )
        db.add(event)
        print(f"  [ADD] {event_data['event_type']}")

db.commit()
print("\n[DONE] Event types seeded successfully!")

# Verify
result = db.query(NotificationEventCatalogue).filter(
    NotificationEventCatalogue.event_type.in_([
        'test_result_normal', 'test_result_alert', 'test_result_critical'
    ])
).all()

print(f"\nVerification: {len(result)} event types in catalogue")
for r in result:
    print(f"  - {r.event_type}: {r.label}")

db.close()
