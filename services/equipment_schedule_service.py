
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import Equipment, TestRequestSchedule, TestingRequest


class EquipmentScheduleInstantiationService:

    @staticmethod
    def instantiate_schedules(
        db: Session,
        equipment: Equipment,
        user_id: UUID,
    ):

        templates = (
            db.query(TestRequestSchedule)
            .join(TestingRequest)
            .filter(
                TestRequestSchedule.is_active.is_(True),

                # template schedules only
                TestRequestSchedule.equipment_id.is_(None),

                TestingRequest.is_schedule_template.is_(True),

                TestingRequest.equipment_type_id
                    == equipment.equipment_type_id,
            )
            .all()
        )

        created_count = 0

        for template in templates:

            existing = (
                db.query(TestRequestSchedule)
                .filter(
                    TestRequestSchedule.test_request_id
                        == template.test_request_id,

                    TestRequestSchedule.equipment_id
                        == equipment.id,
                )
                .first()
            )

            if existing:
                continue

            operational_schedule = TestRequestSchedule(
                test_request_id=template.test_request_id,

                equipment_id=equipment.id,

                organization_id=equipment.organization_id,

                frequency=template.frequency,

                start_date=datetime.now(timezone.utc),

                next_run_date=template.next_run_date,

                end_date=template.end_date,

                advance_days=template.advance_days,

                revised_periodicity_days=template.revised_periodicity_days,

                oem_reference=template.oem_reference,

                is_active=True,

                created_by=user_id,
            )

            db.add(operational_schedule)

            created_count += 1

        db.commit()

        return {
            "equipment_id": str(equipment.id),
            "schedules_created": created_count,
        }
