"""
Notification Event Emitter Service

Provides a simple API for application code to emit notification events
without directly calling the notification service.

Events are persisted to the notification_events table and processed
asynchronously by the notification worker.

Usage:
    from services.notification_event_emitter import emit_notification_event

    emit_notification_event(
        db=db,
        organization_id=request.organization_id,
        event_type="test_submitted",
        event_source="testing_service",
        workflow_type="testing_request",
        equipment_type=request.equipment_type,
        payload={
            "request_id": str(request.id),
            "request_number": request.request_number,
            ...
        }
    )
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import UUID
import logging

from models import NotificationEvent

logger = logging.getLogger(__name__)


def emit_notification_event(
    db: Session,
    organization_id: UUID | str,
    event_type: str,
    payload: Dict[str, Any],
    event_source: Optional[str] = None,
    workflow_type: Optional[str] = None,
    equipment_type: Optional[str] = None,
    test_category: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    delay_seconds: int = 0,
) -> UUID:
    """
    Emit a notification event to be processed asynchronously.

    This is a fire-and-forget operation - the function returns immediately
    without waiting for notification delivery.

    Args:
        db: Database session
        organization_id: Organization UUID
        event_type: Event type (e.g., 'test_submitted', 'status_changed')
        payload: Dict with all template variables and context data
        event_source: Optional source identifier (e.g., 'testing_service')
        workflow_type: Optional workflow type for routing rules
        equipment_type: Optional equipment type for routing rules
        test_category: Optional test category for routing rules
        status_from: Optional source status for routing rules
        status_to: Optional destination status for routing rules
        delay_seconds: Optional delay before processing (for scheduled notifications)

    Returns:
        UUID of the created event

    Example:
        event_id = emit_notification_event(
            db=db,
            organization_id=org_id,
            event_type="test_submitted",
            event_source="testing_service",
            workflow_type="testing_request",
            equipment_type="Circuit Breaker",
            test_category="test",
            status_to="submitted",
            payload={
                "request_id": "uuid",
                "request_number": "TR-2024-001",
                "tester_name": "John Doe",
                "equipment_name": "CB-01",
                "substation_name": "Substation A",
                "scheduled_date": "2024-05-26",
            }
        )
    """
    # Calculate scheduled_for timestamp
    scheduled_for = datetime.utcnow()
    if delay_seconds > 0:
        scheduled_for += timedelta(seconds=delay_seconds)

    # Create event
    event = NotificationEvent(
        organization_id=organization_id,
        event_type=event_type,
        event_source=event_source,
        workflow_type=workflow_type,
        equipment_type=equipment_type,
        test_category=test_category,
        status_from=status_from,
        status_to=status_to,
        payload=payload,
        scheduled_for=scheduled_for,
    )

    db.add(event)
    db.commit()
    db.refresh(event)

    logger.info(
        f"Emitted notification event: {event_type} "
        f"(id={event.id}, org={organization_id}, workflow={workflow_type})"
    )

    return event.id


def emit_test_submitted_event(
    db: Session,
    organization_id: UUID | str,
    request_id: UUID | str,
    request_number: str,
    tester_name: str,
    equipment_name: str,
    equipment_type: str,
    substation_name: str,
    test_category: str,
    scheduled_date: str,
    additional_payload: Optional[Dict[str, Any]] = None,
) -> UUID:
    """
    Convenience function for emitting test_submitted events.

    Args:
        db: Database session
        organization_id: Organization UUID
        request_id: Testing request UUID
        request_number: Request number (e.g., "TR-2024-001")
        tester_name: Name of the tester
        equipment_name: Equipment name
        equipment_type: Equipment type (for routing)
        substation_name: Substation/department name
        test_category: Test category (test/maintenance/inspection)
        scheduled_date: Scheduled date string
        additional_payload: Optional additional template variables

    Returns:
        UUID of the created event
    """
    payload = {
        "request_id": str(request_id),
        "request_number": request_number,
        "tester_name": tester_name,
        "equipment_name": equipment_name,
        "substation_name": substation_name,
        "scheduled_date": scheduled_date,
    }

    if additional_payload:
        payload.update(additional_payload)

    return emit_notification_event(
        db=db,
        organization_id=organization_id,
        event_type="test_submitted",
        event_source="testing_service",
        workflow_type="testing_request",
        equipment_type=equipment_type,
        test_category=test_category,
        status_to="submitted",
        payload=payload,
    )


def emit_status_changed_event(
    db: Session,
    organization_id: UUID | str,
    workflow_type: str,
    record_id: UUID | str,
    record_number: str,
    status_from: str,
    status_to: str,
    changed_by: str,
    equipment_type: Optional[str] = None,
    test_category: Optional[str] = None,
    additional_payload: Optional[Dict[str, Any]] = None,
) -> UUID:
    """
    Convenience function for emitting status_changed events.

    Args:
        db: Database session
        organization_id: Organization UUID
        workflow_type: Workflow type (testing_request, taqc_inspection, etc.)
        record_id: Record UUID
        record_number: Record number (e.g., "TR-2024-001")
        status_from: Previous status
        status_to: New status
        changed_by: User who made the change
        equipment_type: Optional equipment type
        test_category: Optional test category
        additional_payload: Optional additional template variables

    Returns:
        UUID of the created event
    """
    payload = {
        "record_id": str(record_id),
        "record_number": record_number,
        "status_from": status_from,
        "status_to": status_to,
        "changed_by": changed_by,
    }

    if additional_payload:
        payload.update(additional_payload)

    return emit_notification_event(
        db=db,
        organization_id=organization_id,
        event_type="status_changed",
        event_source=f"{workflow_type}_service",
        workflow_type=workflow_type,
        equipment_type=equipment_type,
        test_category=test_category,
        status_from=status_from,
        status_to=status_to,
        payload=payload,
    )


def emit_test_result_event(
    db: Session,
    organization_id: UUID | str,
    request_id: UUID | str,
    request_number: str,
    equipment_name: str,
    equipment_type: str,
    test_category: str,
    test_type_name: str,
    result_threshold: str,  # 'NORMAL', 'ALERT', 'CRITICAL'
    tester_name: str,
    additional_payload: Optional[Dict[str, Any]] = None,
) -> UUID:
    """
    Convenience function for emitting test result events with threshold evaluation.

    Args:
        db: Database session
        organization_id: Organization UUID
        request_id: Testing request UUID
        request_number: Request number
        equipment_name: Equipment name
        equipment_type: Equipment type
        test_category: Test category
        test_type_name: Test type name
        result_threshold: NORMAL, ALERT, or CRITICAL
        tester_name: Tester name
        additional_payload: Optional additional template variables

    Returns:
        UUID of the created event
    """
    # Determine event type based on threshold
    event_type_map = {
        'NORMAL': 'test_result_normal',
        'ALERT': 'test_result_alert',
        'CRITICAL': 'test_result_critical',
    }
    event_type = event_type_map.get(result_threshold, 'test_result_normal')

    payload = {
        "request_id": str(request_id),
        "request_number": request_number,
        "equipment_name": equipment_name,
        "test_type_name": test_type_name,
        "result_threshold": result_threshold,
        "tester_name": tester_name,
    }

    if additional_payload:
        payload.update(additional_payload)

    return emit_notification_event(
        db=db,
        organization_id=organization_id,
        event_type=event_type,
        event_source="testing_service",
        workflow_type="testing_request",
        equipment_type=equipment_type,
        test_category=test_category,
        status_to="under_approval",
        payload=payload,
    )
