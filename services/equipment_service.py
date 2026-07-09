"""
Equipment Asset Register Service
Handles UEIC generation, CRUD, lifecycle management, and department-based querying.
"""
import re
from uuid import UUID
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, text

from models import Equipment, EquipmentStatus, OrgDepartment, CategoryMaster, BaySequence, EquipmentSerialCounter


class EquipmentService:

    # ── Equipment Type Code Mapping (from SRS Appendix A) ──
    EQUIPMENT_TYPE_CODES = {
        "Power Transformer":             "PT",
        "Circuit Breaker":               "CB",
        "Current Transformer":           "CT",
        "Potential Transformer":         "VT",
        "Voltage Transformer":           "VT",
        "Capacitor Voltage Transformer": "VT",
        "CVT":                           "VT",
        "Surge Arrestor":                "SA",
        "Isolator":                      "IS",
        "Isolator / Disconnector":       "IS",
        "Disconnector":                  "IS",
        "Control & Relay Panel":         "CR",
        "Battery Set":                   "BS",
        "Battery Charger":               "BC",
        "Wave Trap":                     "WT",
        "Station Auxiliary Transformer": "AT",
        "LTAC Panel":                    "LP",
        "Fire Fighting System":          "FF",
        "PLCC Panel":                    "PL",
        "Digital Communication Panel":   "DC",
        "Diesel Generator Set":          "DG",
        "Electronic Tri-vector Meter":   "EM",
        "ETV Meter":                     "EM",
        "Protection Relay":              "RL",
        "Distribution Transformer":      "DT",
        "Bus Bar":                       "BB",
        "Cable":                         "CA",
        "Capacitor Bank":                "CP",
        "Reactor":                       "RC",
        "Lightning Arrester":            "LA",
    }

    @classmethod
    def _get_department_ancestor(
        cls, db: Session, department_id: UUID, target_level: int
    ) -> Optional[OrgDepartment]:
        """Walk up the department tree to find ancestor at a given depth (0=root)."""
        dept = db.query(OrgDepartment).filter(OrgDepartment.id == department_id).first()
        if not dept:
            return None

        path = [dept]
        current = dept
        while current.parent_department_id:
            current = db.query(OrgDepartment).filter(
                OrgDepartment.id == current.parent_department_id
            ).first()
            if not current:
                break
            path.append(current)

        path.reverse()  # root first
        if target_level < len(path):
            return path[target_level]
        return None

    @classmethod
    def _get_department_subtree_ids(
        cls, db: Session, department_id: UUID
    ) -> List[UUID]:
        """Return all descendant department IDs including the root itself."""
        sql = text("""
            WITH RECURSIVE dept_tree AS (
                SELECT id
                FROM org_departments
                WHERE id = :root_id
                  AND is_active = true

                UNION ALL

                SELECT d.id
                FROM org_departments d
                INNER JOIN dept_tree dt ON d.parent_department_id = dt.id
                WHERE d.is_active = true
            )
            SELECT id FROM dept_tree
        """)
        rows = db.execute(sql, {"root_id": str(department_id)}).fetchall()
        return [
            r[0] if isinstance(r[0], UUID) else UUID(str(r[0]))
            for r in rows
        ]

    @classmethod
    def _get_descendants_of_named(
        cls, db: Session, org_id, area_name: str
    ) -> List[UUID]:
        """
        Find every department whose name matches area_name inside this org,
        then return that department + ALL its descendants.
        Used for zone / circle / division hierarchical filters.
        """
        sql = text("""
            WITH RECURSIVE dept_tree AS (
                SELECT id
                FROM org_departments
                WHERE organization_id = :org_id
                  AND is_active        = true
                  AND LOWER(name)      = LOWER(:area_name)

                UNION ALL

                SELECT d.id
                FROM org_departments d
                INNER JOIN dept_tree dt ON d.parent_department_id = dt.id
                WHERE d.is_active = true
            )
            SELECT id FROM dept_tree
        """)
        rows = db.execute(
            sql, {"org_id": str(org_id), "area_name": area_name}
        ).fetchall()
        return [UUID(str(r[0])) for r in rows]

    @classmethod
    def _get_department_ancestry_names(cls, db: Session, department_id: UUID) -> dict:
        """Walk up department tree and return hierarchy names for auto-fill."""
        dept = db.query(OrgDepartment).filter(OrgDepartment.id == department_id).first()
        if not dept:
            return {}

        path = [dept]
        current = dept
        while current.parent_department_id:
            current = db.query(OrgDepartment).filter(
                OrgDepartment.id == current.parent_department_id
            ).first()
            if not current:
                break
            path.append(current)

        path.reverse()  # root first

        level_names = ["zone", "ce_circle", "se_division", "ee_subdivision", "aee_section", "ae_je"]
        result = {}
        for i, dept_node in enumerate(path):
            if i < len(level_names):
                result[level_names[i]] = dept_node.name
        return result

    @classmethod
    def _get_or_create_bay_sequence(cls, db: Session, department_id: UUID, bay_name: str) -> int:
        """
        Return the permanent 2-digit bay sequence number for this bay name at this
        substation, assigning the next number (in order of first registration) the
        first time this bay name is seen here. Uses a transaction-scoped advisory
        lock keyed to the department so concurrent registrations for two different
        new bays at the same substation can't race to the same sequence number.
        """
        bay_name = bay_name or "UNSPECIFIED"

        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"bay_seq:{department_id}"},
        )

        existing = db.query(BaySequence).filter(
            BaySequence.department_id == department_id,
            BaySequence.bay_name == bay_name,
        ).first()
        if existing:
            return existing.sequence_number

        next_seq = (
            db.query(func.coalesce(func.max(BaySequence.sequence_number), 0))
            .filter(BaySequence.department_id == department_id)
            .scalar() or 0
        ) + 1

        row = BaySequence(department_id=department_id, bay_name=bay_name, sequence_number=next_seq)
        db.add(row)
        db.flush()
        return next_seq

    @classmethod
    def _get_or_increment_serial(
        cls, db: Session, department_id: UUID, voltage_class: str, bay_sequence: int, equipment_type_id: int,
    ) -> int:
        """
        Atomically increment (or create at 1) the persistent serial counter for
        this (substation, voltage class, bay sequence, equipment type) key.
        This never decreases, so a serial number already issued is never
        reused — even if the equipment row it was issued to is later removed.
        """
        row = db.execute(
            text("""
                INSERT INTO public.equipment_serial_counters
                    (id, department_id, voltage_class, bay_sequence, equipment_type_id, last_serial)
                VALUES (gen_random_uuid(), :department_id, :voltage_class, :bay_sequence, :equipment_type_id, 1)
                ON CONFLICT (department_id, voltage_class, bay_sequence, equipment_type_id)
                DO UPDATE SET last_serial = public.equipment_serial_counters.last_serial + 1,
                              updated_at = now()
                RETURNING last_serial
            """),
            {
                "department_id": str(department_id),
                "voltage_class": voltage_class or "000",
                "bay_sequence": bay_sequence,
                "equipment_type_id": equipment_type_id,
            },
        ).first()
        return row[0]

    @classmethod
    def generate_ueic(
        cls,
        db: Session,
        department_id: UUID,
        equipment_type_id: int,
        equipment_type_name: str,
        voltage_class: str,
        bay_number: str,
    ) -> str:
        """
        Generate UEIC: {zone_code}-{substation_code}-{voltage}-{bay}-{type_code}-{serial}
        Example: NZ-BLRY-220-04-CB-01  (SRS §3.1.1)

        Requires:
          - Zone department (depth=0) must have a 2-char code
          - Substation department (the department passed in) must have a curated
            code set. This is NOT derived from the department name: real
            substation abbreviations (e.g. "Bellary" -> "BLRY") are a deliberate
            editorial choice, not something that can be produced reliably by
            string-mangling the name, and UEICs are permanent once issued — so a
            missing code is a hard error rather than a best-effort guess.
        """
        zone_dept = cls._get_department_ancestor(db, department_id, target_level=0)
        if not zone_dept or not zone_dept.code:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Zone department has no code set. Update OrgDepartment.code before registering equipment.",
            )

        substation = db.query(OrgDepartment).filter(OrgDepartment.id == department_id).first()
        if not substation:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Department '{department_id}' not found.",
            )

        if not substation.code or substation.code.strip().upper() in ("TODO", "XXXX", "TBD"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Substation '{substation.name}' has no valid code set. UEICs require a curated "
                    f"4-character substation abbreviation (e.g. 'BLRY' for Bellary) — set "
                    f"OrgDepartment.code for this substation before registering equipment."
                ),
            )

        zone_code = zone_dept.code.upper()[:2]
        substation_code = substation.code.upper()[:4].ljust(4, "X")

        type_code = cls.EQUIPMENT_TYPE_CODES.get(equipment_type_name, "XX")

        v_class = str(voltage_class).zfill(3) if voltage_class else "000"

        bay_seq = cls._get_or_create_bay_sequence(db, department_id, bay_number)
        bay = str(bay_seq).zfill(2)

        serial_num = cls._get_or_increment_serial(db, department_id, voltage_class, bay_seq, equipment_type_id)
        serial = str(serial_num).zfill(2)

        return f"{zone_code}-{substation_code}-{v_class}-{bay}-{type_code}-{serial}"

    @classmethod
    def create_equipment(
        cls,
        db: Session,
        organization_id: UUID,
        department_id: UUID,
        equipment_type_id: int,
        voltage_class: Optional[str] = None,
        bay_number: Optional[str] = None,
        nameplate_data: Optional[dict] = None,
        commissioned_date: Optional[datetime] = None,
        manufacturer: Optional[str] = None,
        model_number: Optional[str] = None,
        factory_serial_number: Optional[str] = None,
        year_of_manufacture: Optional[int] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        phase: Optional[str] = None,
        ct_ratio_actual: Optional[str] = None,
        ct_ratio_current: Optional[str] = None,
        pt_ratio: Optional[str] = None,
        vector_group: Optional[str] = None,
        impedance_pct: Optional[float] = None,
        scada_tag: Optional[str] = None,
        created_by: Optional[UUID] = None,
    ) -> Equipment:
        """Register a new equipment unit with auto-generated UEIC."""
        eq_type = db.query(CategoryMaster).filter(CategoryMaster.id == equipment_type_id).first()
        if not eq_type:
            raise HTTPException(status_code=404, detail="Equipment type not found")

        dept = db.query(OrgDepartment).filter(OrgDepartment.id == department_id).first()
        if not dept:
            raise HTTPException(status_code=404, detail="Department/substation not found")

        ueic = cls.generate_ueic(db, department_id, equipment_type_id, eq_type.name, voltage_class, bay_number)

        # Collisions should be structurally impossible now that the serial segment
        # comes from an atomic, monotonically-increasing counter — this is a defensive
        # integrity check, not a recovery path. Silently bumping the serial here (as the
        # old logic did) would desync the UEIC from the counter table and risk reuse.
        if db.query(Equipment).filter(Equipment.ueic == ueic).first():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Generated UEIC '{ueic}' already exists. This indicates a data integrity issue with the serial counter — investigate before retrying.",
            )

        equipment = Equipment(
            ueic=ueic,
            organization_id=organization_id,
            department_id=department_id,
            equipment_type_id=equipment_type_id,
            voltage_class=voltage_class,
            bay_number=bay_number,
            serial_in_bay=ueic.rsplit("-", 1)[-1],
            nameplate_data=nameplate_data,
            status=EquipmentStatus.active,
            commissioned_date=commissioned_date,
            manufacturer=manufacturer,
            model_number=model_number,
            factory_serial_number=factory_serial_number,
            year_of_manufacture=year_of_manufacture,
            latitude=latitude,
            longitude=longitude,
            phase=phase,
            ct_ratio_actual=ct_ratio_actual,
            ct_ratio_current=ct_ratio_current,
            pt_ratio=pt_ratio,
            vector_group=vector_group,
            impedance_pct=impedance_pct,
            scada_tag=scada_tag,
            created_by=created_by,
        )
        db.add(equipment)
        db.flush()
        return equipment

    @classmethod
    def get_equipment(cls, db: Session, equipment_id: UUID) -> Optional[Equipment]:
        """Get single equipment by ID with relationships."""
        return (
            db.query(Equipment)
            .options(
                joinedload(Equipment.equipment_type),
                joinedload(Equipment.department),
                joinedload(Equipment.organization),
            )
            .filter(Equipment.id == equipment_id)
            .first()
        )

    @classmethod
    def get_equipment_by_ueic(cls, db: Session, ueic: str) -> Optional[Equipment]:
        """Get equipment by UEIC code."""
        return db.query(Equipment).filter(Equipment.ueic == ueic).first()

    @classmethod
    def list_equipment(
        cls,
        db: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        equipment_type_id: Optional[int] = None,
        status: Optional[str] = None,
        voltage_class: Optional[str] = None,
        manufacturer: Optional[str] = None,
        model_number: Optional[str] = None,
        substation_ids: Optional[str] = None,
        tlss_division: Optional[str] = None,
        wm_circle: Optional[str] = None,
        transmission_zone: Optional[str] = None,
        search: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        # ── year filters ────────────────────────────────────────────────────
        commission_year: Optional[int] = None,
        commission_year_from: Optional[int] = None,
        commission_year_to: Optional[int] = None,
        failure_year: Optional[int] = None,
        failure_year_from: Optional[int] = None,
        failure_year_to: Optional[int] = None,
        replacement_year: Optional[int] = None,
        replacement_year_from: Optional[int] = None,
        replacement_year_to: Optional[int] = None,
        has_tests: bool = False,
    ) -> List[Equipment]:
        from sqlalchemy import extract

        query = (
            db.query(Equipment)
            .options(
                joinedload(Equipment.equipment_type),
                joinedload(Equipment.department),
            )
        )

        if organization_id:
            query = query.filter(Equipment.organization_id == organization_id)

        if department_id:
            dept_ids = cls._get_department_subtree_ids(db, department_id)
            query = query.filter(Equipment.department_id.in_(dept_ids))

        if equipment_type_id:
            query = query.filter(Equipment.equipment_type_id == equipment_type_id)
        if status:
            query = query.filter(Equipment.status == status)
        if voltage_class:
            query = query.filter(Equipment.voltage_class == voltage_class)
        if manufacturer:
            query = query.filter(Equipment.manufacturer.ilike(f"%{manufacturer}%"))
        if model_number:
            query = query.filter(Equipment.model_number.ilike(f"%{model_number}%"))
        if search:
            query = query.filter(
                (Equipment.ueic.ilike(f"%{search}%")) |
                (Equipment.bay_number.ilike(f"%{search}%")) |
                (Equipment.manufacturer.ilike(f"%{search}%")) |
                (Equipment.model_number.ilike(f"%{search}%")) |
                (Equipment.factory_serial_number.ilike(f"%{search}%"))
            )

        if substation_ids:
            id_list = [s.strip() for s in substation_ids.split(",") if s.strip()]
            if id_list:
                try:
                    parsed = [UUID(i) for i in id_list]
                    query = query.filter(Equipment.department_id.in_(parsed))
                except ValueError:
                    pass

        if transmission_zone:
            dept_ids = cls._get_descendants_of_named(db, organization_id, transmission_zone)
            if not dept_ids:
                return []
            query = query.filter(Equipment.department_id.in_(dept_ids))
        if wm_circle:
            dept_ids = cls._get_descendants_of_named(db, organization_id, wm_circle)
            if not dept_ids:
                return []
            query = query.filter(Equipment.department_id.in_(dept_ids))
        if tlss_division:
            dept_ids = cls._get_descendants_of_named(db, organization_id, tlss_division)
            if not dept_ids:
                return []
            query = query.filter(Equipment.department_id.in_(dept_ids))

        # ── Commission year filters ──────────────────────────────────────────
        if commission_year:
            query = query.filter(
                extract('year', Equipment.commissioned_date) == commission_year
            )
        if commission_year_from:
            query = query.filter(
                extract('year', Equipment.commissioned_date) >= commission_year_from
            )
        if commission_year_to:
            query = query.filter(
                extract('year', Equipment.commissioned_date) <= commission_year_to
            )

        # ── Failure year filters (retired_date = when the equipment failed/was retired) ──
        if failure_year:
            query = query.filter(
                extract('year', Equipment.retired_date) == failure_year
            )
        if failure_year_from:
            query = query.filter(
                extract('year', Equipment.retired_date) >= failure_year_from
            )
        if failure_year_to:
            query = query.filter(
                extract('year', Equipment.retired_date) <= failure_year_to
            )

        # ── Replacement year filters (commissioned_date of units that ARE replacements) ──
        if replacement_year:
            query = query.filter(
                Equipment.replaces_equipment_id.isnot(None),
                extract('year', Equipment.commissioned_date) == replacement_year
            )
        if replacement_year_from:
            query = query.filter(
                Equipment.replaces_equipment_id.isnot(None),
                extract('year', Equipment.commissioned_date) >= replacement_year_from
            )
        if replacement_year_to:
            query = query.filter(
                Equipment.replaces_equipment_id.isnot(None),
                extract('year', Equipment.commissioned_date) <= replacement_year_to
            )

        if has_tests:
            from models import TestingRequest
            from sqlalchemy import exists as sa_exists
            query = query.filter(
                sa_exists().where(TestingRequest.equipment_id == Equipment.id)
            )

        return (
            query
            .order_by(desc(Equipment.cts))
            .offset(skip)
            .limit(limit)
            .all()
        )
        # NOTE: dead code (print + second return) that was here has been removed.

    @classmethod
    def update_equipment(
        cls,
        db: Session,
        equipment_id: UUID,
        modified_by: Optional[UUID] = None,
        **kwargs,
    ) -> Equipment:
        """Update equipment fields."""
        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=404, detail="Equipment not found")

        allowed_fields = [
            "nameplate_data", "voltage_class", "bay_number", "manufacturer",
            "model_number", "factory_serial_number", "year_of_manufacture",
            "commissioned_date", "retirement_reason",
            "latitude", "longitude",
            "phase", "ct_ratio_actual", "ct_ratio_current",
            "pt_ratio", "vector_group", "impedance_pct",
        ]
        for key, value in kwargs.items():
            if key in allowed_fields and value is not None:
                setattr(equipment, key, value)

        if modified_by:
            equipment.modified_by = modified_by

        db.flush()
        return equipment

    @classmethod
    def retire_equipment(
        cls,
        db: Session,
        equipment_id: UUID,
        reason: str,
        modified_by: Optional[UUID] = None,
    ) -> Equipment:
        """Retire an equipment unit (soft-delete). UEIC remains for historical records."""
        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=404, detail="Equipment not found")
        if equipment.status != EquipmentStatus.active:
            raise HTTPException(
                status_code=400,
                detail=f"Equipment is already {equipment.status.value}",
            )

        equipment.status = EquipmentStatus.retired
        equipment.retired_date = datetime.now(timezone.utc)
        equipment.retirement_reason = reason
        if modified_by:
            equipment.modified_by = modified_by

        db.flush()
        return equipment

    @classmethod
    def replace_equipment(
        cls,
        db: Session,
        old_equipment_id: UUID,
        reason: str,
        created_by: Optional[UUID] = None,
        reason_type: str = "other",
        recommendation_id: Optional[UUID] = None,
        analysis_report_path: Optional[str] = None,
        **new_equipment_kwargs,
    ) -> tuple:
        """Retire old equipment and register a new replacement. Returns (old, new)."""
        old = cls.retire_equipment(db, old_equipment_id, reason, modified_by=created_by)

        if reason_type == "recommendation_compliance" and recommendation_id:
            try:
                from models import Recommendation
                rec = db.query(Recommendation).filter(
                    Recommendation.id == recommendation_id
                ).first()
                if rec:
                    rec.approval_status = "fulfilled"
                    db.flush()
            except Exception:
                pass

        new_kwargs = {
            "organization_id": old.organization_id,
            "department_id": old.department_id,
            "equipment_type_id": old.equipment_type_id,
            "voltage_class": old.voltage_class,
            "bay_number": old.bay_number,
            "created_by": created_by,
        }
        new_kwargs.update(new_equipment_kwargs)

        new_equipment = cls.create_equipment(db, **new_kwargs)
        new_equipment.replaces_equipment_id = old.id
        new_equipment.replacement_reason_type = reason_type
        if recommendation_id:
            new_equipment.replacement_recommendation_id = recommendation_id
        if analysis_report_path:
            new_equipment.analysis_report_path = analysis_report_path
        old.replaced_by_id = new_equipment.id
        db.flush()

        return old, new_equipment

    @classmethod
    def get_equipment_for_department(
        cls, db: Session, department_id: UUID
    ) -> List[Equipment]:
        """
        Get all active equipment for a department INCLUDING subtree departments.
        Used by Testing Request form auto-populate.
        """
        department_ids = cls._get_department_subtree_ids(db, department_id)
        return (
            db.query(Equipment)
            .options(joinedload(Equipment.equipment_type))
            .filter(
                Equipment.department_id.in_(department_ids),
                Equipment.status == EquipmentStatus.active,
            )
            .order_by(Equipment.ueic)
            .all()
        )

    @classmethod
    def get_applicable_tests(cls, db: Session, equipment_id: UUID) -> list:
        """Get test types applicable to an equipment's type."""
        from models import CategoryDetails
        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=404, detail="Equipment not found")

        return (
            db.query(CategoryDetails)
            .filter(
                CategoryDetails.category_master_id == equipment.equipment_type_id,
                CategoryDetails.is_active == True,
            )
            .order_by(CategoryDetails.name)
            .all()
        )

    @classmethod
    def get_equipment_count(
        cls,
        db: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> dict:
        """Get equipment counts by status, optionally scoped to department subtree."""
        query = db.query(Equipment.status, func.count(Equipment.id))
        if organization_id:
            query = query.filter(Equipment.organization_id == organization_id)
        if department_id:
            # Include descendant departments
            dept_ids = cls._get_department_subtree_ids(db, department_id)
            query = query.filter(Equipment.department_id.in_(dept_ids))

        rows = query.group_by(Equipment.status).all()
        counts = {s.value: 0 for s in EquipmentStatus}
        for s, c in rows:
            counts[s.value] = c
        counts["total"] = sum(counts.values())
        return counts