"""
surveillance_hooks.py
─────────────────────
Post-commissioning surveillance workflow automation.

Listens for repair workflow completion and automatically creates a 24-month
surveillance workflow with 5 stages (Q1-Q4 quarterly reviews + final evaluation).

Hook registration happens at module import time (called from main.py startup).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from models import (
    Equipment,
    RepairWorkflow,
    RepairWorkflowDefinition,
    RepairStageDefinition,
    RepairStageInstance,
    SurveillanceTestConfig,
    TestRequestSchedule,
    ScheduleFrequency,
)
from services.surveillance_config_service import SurveillanceConfigService

if TYPE_CHECKING:
    from models import User

logger = logging.getLogger(__name__)


def _on_repair_workflow_completed(
    db: Session,
    workflow: RepairWorkflow,
    user_id: UUID,
    **kwargs
) -> None:
    """
    Hook handler for repair workflow completion.

    Triggers surveillance workflow creation when a repair workflow completes
    its final stage (regardless of stage number - could be stage 8, 10, or 15).

    Args:
        db: Database session
        workflow: Completed repair workflow
        user_id: User who completed the final stage
        **kwargs: Additional arguments (unused)
    """
    try:
        # Only create surveillance for repair-type workflows
        # Check workflow_type field (case-insensitive: 'BREAKDOWN', 'OVERHAUL', 'REPAIR')
        workflow_type_upper = (workflow.workflow_type or "").upper()
        if workflow_type_upper not in ['REPAIR', 'BREAKDOWN', 'OVERHAUL']:
            logger.info(
                "[SurveillanceHook] Skipping surveillance for workflow_type=%s (workflow_id=%s)",
                workflow.workflow_type, workflow.id
            )
            return

        # Check if surveillance workflow already exists (idempotency)
        existing_surveillance = (
            db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.parent_workflow_id == workflow.id,
                RepairWorkflow.workflow_type == 'surveillance'
            )
            .first()
        )
        if existing_surveillance:
            logger.info(
                "[SurveillanceHook] Surveillance workflow already exists: %s (parent: %s)",
                existing_surveillance.id, workflow.id
            )
            return

        # Get surveillance configuration
        config = SurveillanceConfigService.get_config(
            db,
            organization_id=workflow.organization_id,
            department_id=workflow.department_id
        )
        surveillance_period_months = config['surveillance_period_months']

        # Get surveillance workflow definition (must exist from seed script)
        surveillance_def = (
            db.query(RepairWorkflowDefinition)
            .filter(RepairWorkflowDefinition.workflow_code == 'SURVEILLANCE')
            .first()
        )

        if not surveillance_def:
            logger.error(
                "[SurveillanceHook] SURVEILLANCE workflow definition not found. "
                "Run migration seed script: python run_migration_008_seed.py"
            )
            return

        # Create surveillance workflow
        # Calculate surveillance period (used for stage/schedule calculations)
        start_date = datetime.now(timezone.utc)
        # Note: We don't store end_date on workflow - it's calculated from surveillance_period_months

        # Generate workflow number
        from services.repair_workflow_service import RepairWorkflowService
        wf_service = RepairWorkflowService(db)
        workflow_number = wf_service.generate_workflow_number()

        surveillance_workflow = RepairWorkflow(
            workflow_number=workflow_number,
            workflow_code='SURVEILLANCE',
            equipment_id=workflow.equipment_id,
            organization_id=workflow.equipment.organization_id if workflow.equipment else None,
            workflow_type='surveillance',
            parent_workflow_id=workflow.id,  # Link back to parent repair workflow
            status='active',
            created_by=user_id,
            modified_by=user_id,
        )
        db.add(surveillance_workflow)
        db.flush()  # Get workflow ID

        # Create 5 stage instances (Q1-Q4 + Final Evaluation)
        stages = _create_surveillance_stages(
            db,
            surveillance_def.id,
            surveillance_workflow.id,
            start_date,
            surveillance_period_months,
            user_id
        )

        # Set first stage as current
        if stages:
            surveillance_workflow.current_stage_id = stages[0].stage_id
            surveillance_workflow.current_stage_instance_id = stages[0].id
            stages[0].status = 'in_progress'
            stages[0].started_at = start_date

        # Create test request schedules for all quarters
        # This will be picked up by the daily scheduler to create testing requests
        schedules_created = _create_surveillance_test_schedules(
            db,
            surveillance_workflow=surveillance_workflow,
            start_date=start_date,
            quarter_months=surveillance_period_months // 4,
            user_id=user_id
        )

        db.commit()

        logger.info(
            "[SurveillanceHook] Created surveillance workflow %s for parent %s "
            "(equipment_id=%s, %d months, %d stages, %d test schedules)",
            surveillance_workflow.id,
            workflow.id,
            workflow.equipment_id,
            surveillance_period_months,
            len(stages),
            schedules_created
        )

    except Exception as exc:
        logger.error(
            "[SurveillanceHook] Failed to create surveillance workflow for %s: %s",
            workflow.id, exc, exc_info=True
        )
        db.rollback()
        # Don't raise — hook failures should not block workflow completion


def _create_surveillance_test_schedules(
    db: Session,
    surveillance_workflow: RepairWorkflow,
    start_date: datetime,
    quarter_months: int,
    user_id: UUID
) -> int:
    """
    Create TestRequestSchedule records for all surveillance quarters.

    The existing TestRequestScheduleService.run_daily_scheduler() will automatically
    create testing requests from these schedules at the appropriate times.

    Args:
        db: Database session
        surveillance_workflow: Surveillance workflow instance
        start_date: Surveillance start date
        quarter_months: Months per quarter (e.g., 6 for 24-month / 4 quarters)
        user_id: User creating the workflow

    Returns:
        Number of schedules created
    """
    # Get equipment
    equipment = db.query(Equipment).filter(
        Equipment.id == surveillance_workflow.equipment_id
    ).first()

    if not equipment:
        logger.warning(
            "[SurveillanceHook] Equipment not found: %s",
            surveillance_workflow.equipment_id
        )
        return 0

    # Get test types from surveillance_test_config
    test_configs = (
        db.query(SurveillanceTestConfig)
        .filter(
            SurveillanceTestConfig.equipment_type_id == equipment.equipment_type_id,
            SurveillanceTestConfig.is_active == True
        )
        .all()
    )

    if not test_configs:
        logger.warning(
            "[SurveillanceHook] No surveillance test config for equipment_type=%s",
            equipment.equipment_type_id
        )
        return 0

    created_count = 0

    # Create schedules for each quarter (1-4)
    for quarter in range(1, 5):
        # Calculate quarter start date
        quarter_start = start_date + relativedelta(months=(quarter - 1) * quarter_months)

        # Create schedule for each test type
        for test_config in test_configs:
            try:
                from models import CategoryDetails
                test_type = db.query(CategoryDetails).filter(
                    CategoryDetails.id == test_config.test_type_id
                ).first()

                if not test_type:
                    logger.warning(
                        "[SurveillanceHook] Test type %s not found",
                        test_config.test_type_id
                    )
                    continue

                # Generate title
                equipment_name = (
                    equipment.name or
                    equipment.nameplate_data.get('substation_name') if equipment.nameplate_data else None or
                    str(equipment.id)
                )
                title = f"{test_type.name} - Q{quarter} Surveillance - {equipment_name}"

                # Create schedule record
                schedule = TestRequestSchedule(
                    organization_id=surveillance_workflow.organization_id,
                    department_id=surveillance_workflow.department_id,
                    equipment_id=equipment.id,
                    equipment_type_id=equipment.equipment_type_id,
                    test_type_id=test_config.test_type_id,
                    title=title,
                    description=f"Auto-scheduled surveillance test for Quarter {quarter}",
                    request_category='test',
                    priority=test_config.default_priority or 'high',
                    frequency=ScheduleFrequency.semi_annual,  # 6 months for surveillance
                    start_date=quarter_start,
                    next_run_date=quarter_start,  # Create immediately at quarter start
                    advance_days=1,  # Create 1 day in advance
                    is_active=True,
                    created_by=user_id,
                    # Surveillance linkage - will be copied to testing_requests
                    surveillance_workflow_id=surveillance_workflow.id,
                    surveillance_quarter=quarter,
                    notes=f"Auto-created for surveillance workflow {surveillance_workflow.id}",
                )
                db.add(schedule)
                created_count += 1

                logger.debug(
                    "[SurveillanceHook] Created schedule for %s Q%d (next_run: %s)",
                    test_type.name, quarter, quarter_start.isoformat()
                )

            except Exception as exc:
                logger.error(
                    "[SurveillanceHook] Failed creating schedule for test_type=%s Q%d: %s",
                    test_config.test_type_id, quarter, exc
                )
                # Continue with other schedules even if one fails

    db.flush()
    logger.info(
        "[SurveillanceHook] Created %d test schedules for surveillance workflow %s",
        created_count, surveillance_workflow.id
    )
    return created_count


def _create_surveillance_stages(
    db: Session,
    definition_id: UUID,
    workflow_id: UUID,
    start_date: datetime,
    surveillance_period_months: int,
    user_id: UUID
) -> list[RepairStageInstance]:
    """
    Create stage instances for surveillance workflow.

    Args:
        db: Database session
        definition_id: Surveillance workflow definition ID
        workflow_id: Surveillance workflow ID
        start_date: Surveillance start date
        surveillance_period_months: Total surveillance period (e.g., 24 months)
        user_id: User creating the workflow

    Returns:
        List of created RepairStageInstance objects
    """
    # Get stage definitions
    stage_defs = (
        db.query(RepairStageDefinition)
        .filter(
            RepairStageDefinition.workflow_definition_id == definition_id,
            RepairStageDefinition.is_active == True
        )
        .order_by(RepairStageDefinition.stage_number)
        .all()
    )

    # Calculate quarter duration (total period / 4 quarters)
    quarter_months = surveillance_period_months // 4

    instances = []
    for stage_def in stage_defs:
        # Derive quarter number from stage code (Q1_SURVEILLANCE → 1, Q2_SURVEILLANCE → 2, etc.)
        quarter_number = None
        if stage_def.code.startswith('Q') and len(stage_def.code) > 1:
            try:
                quarter_number = int(stage_def.code[1])  # Extract digit from Q1, Q2, Q3, Q4
            except (ValueError, IndexError):
                quarter_number = None

        # Calculate stage date range based on quarter number
        if quarter_number:
            stage_start = start_date + relativedelta(months=(quarter_number - 1) * quarter_months)
            stage_end = start_date + relativedelta(months=quarter_number * quarter_months)
        else:
            # Final evaluation stage - covers entire period
            stage_start = start_date
            stage_end = start_date + relativedelta(months=surveillance_period_months)

        instance = RepairStageInstance(
            workflow_id=workflow_id,
            stage_id=stage_def.id,
            status='not_started',
            quarter_number=quarter_number,  # Store quarter for easy filtering
            created_by=user_id,
            modified_by=user_id,
        )
        db.add(instance)
        instances.append(instance)

    db.flush()
    return instances


# ═══════════════════════════════════════════════════════════════════════════
# Hook Registration (called at module import time)
# ═══════════════════════════════════════════════════════════════════════════

def register_surveillance_hooks():
    """
    Register surveillance hooks with the workflow hook registry.

    Called from main.py at application startup.
    """
    from workflow_hooks import register

    # Listen for repair workflow completion (final stage, regardless of number)
    # workflow_code will be checked dynamically for 'repair' or 'breakdown'
    # Register for common repair workflow codes
    for workflow_code in ['REPAIR', 'BREAKDOWN', 'OVERHAUL']:
        register(workflow_code, 'completed', _on_repair_workflow_completed)

    logger.info("[SurveillanceHook] Hooks registered for workflow completion events")


# Auto-register hooks when module is imported
register_surveillance_hooks()
