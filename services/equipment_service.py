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

from models import Equipment, EquipmentStatus, OrgDepartment, CategoryMaster


import re
from datetime import datetime  # add this import if not already present at top

class EquipmentService:

    # ── Equipment Type Code Mapping — kept in sync with migrate_ueic_add_make_serial.py ──
    EQUIPMENT_TYPE_CODES = {
        "Power Transformer":             "TR",
        "Circuit Breaker":               "CB",
        "Current Transformer":           "CT",
        "Potential Transformer":         "PT",
        "Voltage Transformer":           "PT",
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
        "Control Valve":                 "CV",
    }

    @staticmethod
    def _normalize_voltage_class(raw: Optional[str]) -> Optional[str]:
        """
        Multi-voltage nameplate values like '400/220/33' or '220/66/11' get
        collapsed to the single highest voltage ('400', '220') so filtering,
        grouping, and UEIC generation stay consistent. Also strips 'kV'/'KV'
        suffixes and whitespace.
        """
        if not raw:
            return None
        s = re.sub(r"kV", "", str(raw), flags=re.IGNORECASE).strip()
        if not s:
            return None
        if "/" not in s:
            return s

        values = []
        for part in s.split("/"):
            part = part.strip()
            try:
                values.append(float(part))
            except ValueError:
                continue
        if not values:
            return s

        top = max(values)
        return str(int(top)) if top.is_integer() else str(top)

    @staticmethod
    def _strip_voltage_prefix(name: str) -> str:
        """Remove a leading voltage prefix like '110kV ', '220kV '."""
        if not name:
            return ""
        return re.sub(r"^\d+\s*kV\s*", "", name, flags=re.IGNORECASE).strip()

    @staticmethod
    def _make_4char_code(name: str) -> str:
        """4-char uppercase code from a name, padded with X."""
        if not name:
            return "XXXX"
        cleaned = re.sub(r"[^A-Za-z0-9]", "", name)
        return cleaned[:4].upper().ljust(4, "X")

    @staticmethod
    def _make_code_upto4(name: str) -> str:
        """Up to 4 alpha-numeric chars, uppercase, NOT padded."""
        if not name:
            return ""
        cleaned = re.sub(r"[^A-Za-z0-9]", "", name)
        return cleaned[:4].upper()

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
        """Return all descendant department IDs including the root itself.

        Delegates to the shared utils.common_service.get_dept_subtree_ids
        (previously the same recursive CTE copy-pasted here independently)
        and keeps this method's own UUID-object normalization on top, since
        the 4 call sites in routers/equipment.py rely on real UUID objects
        rather than whatever raw type the driver happens to return.
        """
        from utils.common_service import get_dept_subtree_ids
        rows = get_dept_subtree_ids(db, department_id)
        return [
            r if isinstance(r, UUID) else UUID(str(r))
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
    def generate_ueic(
        cls,
        db: Session,
        department_id: UUID,
        equipment_type_name: str,
        voltage_class: str,
        bay_number: str,
        manufacturer: Optional[str] = None,
        factory_serial_number: Optional[str] = None,
        year_of_manufacture: Optional[int] = None,
    ) -> str:
        """
        Generate UEIC: {zone}-{substation}-{bay}-{voltage_class}-{type_code}-{make}-{serial_no}
        Example: BN-BBXX-Begur-Vidyanagar line-66-CT-KAPE-HT1690/122569
        Falls back to {make}{year}-{counter} when factory_serial_number is missing.

        Requires:
          - Zone department (depth=0) must have a 2-char code
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

        zone_code = zone_dept.code.upper()[:2]

        # Always derive fresh from the department name — don't trust a stored
        # substation code, which can be stale (matches migrate_ueic_add_make_serial.py)
        substation_code = cls._make_4char_code(cls._strip_voltage_prefix(substation.name or ""))

        type_code = cls.EQUIPMENT_TYPE_CODES.get(equipment_type_name, "XX")

        bay = str(bay_number).strip() if bay_number else ""
        v_class = cls._normalize_voltage_class(voltage_class)
        make_code = cls._make_code_upto4(manufacturer or "") or "Unknown"

        serial_no = (factory_serial_number or "").strip()
        if not serial_no:
            yom = year_of_manufacture or datetime.now().year
            prefix = f"{zone_code}-{substation_code}-{bay}-{v_class}-{type_code}-{make_code}"
            # DB-driven counter (script used an in-memory dict since it ran once over
            # all rows at once; live requests need to check existing UEICs instead)
            existing_count = db.query(func.count(Equipment.id)).filter(
                Equipment.ueic.like(f"{prefix}-%")
            ).scalar() or 0
            serial_no = f"{make_code}{yom}-{existing_count + 1}"

        parts = [zone_code, substation_code, bay, v_class, type_code, make_code, serial_no]
        return "-".join(p for p in parts if p)
    
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
        
        voltage_class = cls._normalize_voltage_class(voltage_class)

        ueic = cls.generate_ueic(
            db, department_id, eq_type.name, voltage_class, bay_number,
            manufacturer=manufacturer,
            factory_serial_number=factory_serial_number,
            year_of_manufacture=year_of_manufacture,
        )

        if db.query(Equipment).filter(Equipment.ueic == ueic).first():
            base_ueic = ueic
            suffix = 2
            while db.query(Equipment).filter(Equipment.ueic == ueic).first():
                ueic = f"{base_ueic}-{suffix}"
                suffix += 1

        equipment = Equipment(
            ueic=ueic,
            organization_id=organization_id,
            department_id=department_id,
            equipment_type_id=equipment_type_id,
            voltage_class=voltage_class,
            bay_number=bay_number,
            serial_in_bay=(factory_serial_number or "").strip() or ueic.rsplit("-", 1)[-1],
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
        # ── registration date range (Equipment.cts) ───────────────────────────
        date_from=None,
        date_to=None,
        has_tests: bool = False,
    ) -> List[Equipment]:
        from sqlalchemy import extract
        from datetime import datetime, timedelta

        query = (
            db.query(Equipment)
            .join(CategoryMaster, Equipment.equipment_type_id == CategoryMaster.id)
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
        query = query.filter(CategoryMaster.name != "Testing Kit")

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

        # ── Registration date range filters ──────────────────────────────────
        if date_from:
            query = query.filter(Equipment.cts >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            query = query.filter(Equipment.cts < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))

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
            if key == "voltage_class" and value is not None:
                value = cls._normalize_voltage_class(value)
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
        if equipment.status not in (EquipmentStatus.active, EquipmentStatus.under_repair):
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
    def set_equipment_status(
        cls,
        db: Session,
        equipment_id: UUID,
        new_status: str,
        reason: Optional[str] = None,
        modified_by: Optional[UUID] = None,
    ) -> Equipment:
        """Manually transition equipment status (active <-> under_repair, or either -> retired).

        Retirement is terminal — once retired, equipment cannot be moved back to
        active or under_repair.
        """
        valid_statuses = {"active", "under_repair", "retired"}
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of: {', '.join(sorted(valid_statuses))}",
            )

        if new_status == "retired":
            if not reason or not reason.strip():
                raise HTTPException(status_code=422, detail="Reason is required to retire equipment")
            return cls.retire_equipment(db, equipment_id, reason, modified_by=modified_by)

        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=404, detail="Equipment not found")

        current = equipment.status.value if equipment.status else "active"
        if current == "retired":
            raise HTTPException(status_code=400, detail="Retired equipment cannot be reactivated")
        if current == new_status:
            raise HTTPException(status_code=400, detail=f"Equipment is already {new_status}")

        equipment.status = EquipmentStatus(new_status)
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
    def get_applicable_tests(cls, db: Session, equipment_id: UUID, org_id=None) -> list:
        """Return only test types that have a template (canonical, same logic as TR form)."""
        from models import CategoryDetails
        from services.org_test_template_service import OrgTestTemplateService

        equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise HTTPException(status_code=404, detail="Equipment not found")

        canonical = OrgTestTemplateService(db).canonical_templates_for_org(org_id=org_id)

        all_types = (
            db.query(CategoryDetails)
            .filter(
                CategoryDetails.category_master_id == equipment.equipment_type_id,
                CategoryDetails.is_active == True,
            )
            .order_by(CategoryDetails.name)
            .all()
        )

        return [t for t in all_types if t.id in canonical]

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

    @staticmethod
    def _mtbf_days_from_dates(dates: list) -> Optional[float]:
        """
        Mean Time Between Failures, in days, from a sorted-or-not list of
        failure-event dates. A real interval needs >= 2 events (1 date has
        no gap to measure), so with fewer this returns None — not 0, not a
        manufactured number off a sample too small to mean anything.

        Single source for this formula: previously computed independently
        in both compute_failure_stats (per-unit) and
        compute_failure_cohort_stats (per-unit-within-cohort) — identical
        logic, copy-pasted, now called from both instead.
        """
        if len(dates) < 2:
            return None
        ordered = sorted(dates)
        span_days = (ordered[-1] - ordered[0]).total_seconds() / 86400.0
        return span_days / (len(ordered) - 1)

    @classmethod
    def compute_failure_stats(cls, db: Session, equipment_id: UUID) -> dict:
        """
        Per-unit cumulative failure count + MTBF (KPTCL spec §2: "maintain
        cumulative failure count, failure rate, and mean time between
        failures (MTBF) per equipment unit").

        A failure event is the same definition already used by the seeded
        "Equipment Performance Report" / "Equipment Failure Performance
        Analysis" reports (seed.py): a TestingRequest whose
        request_category is 'failure_registry', OR any of its TestResults
        carrying evaluation_result->>'overall' == 'CRITICAL'. Event date is
        COALESCE(completed_at, requested_date, cts), matching those same
        reports.

        MTBF is the mean gap, in days, between consecutive failure-event
        dates — a real interval needs at least 2 events, so with 0 or 1
        failures mtbf_days is None (not 0, not "N/A" hidden as a number)
        rather than a manufactured statistic off a sample too small to mean
        anything.
        """
        from models import TestingRequest, TestResult

        rows = (
            db.query(TestingRequest.id, TestingRequest.completed_at,
                      TestingRequest.requested_date, TestingRequest.cts,
                      TestingRequest.request_category)
            .filter(TestingRequest.equipment_id == equipment_id)
            .all()
        )
        if not rows:
            return {
                "cumulative_failure_count": 0,
                "mtbf_days": None,
                "first_failure_date": None,
                "last_failure_date": None,
            }

        tr_ids = [r.id for r in rows]
        critical_tr_ids = {
            tid for (tid,) in (
                db.query(TestResult.testing_request_id)
                .filter(TestResult.testing_request_id.in_(tr_ids))
                .filter(TestResult.evaluation_result["overall"].astext == "CRITICAL")
                .distinct()
                .all()
            )
        }

        event_dates = []
        for r in rows:
            is_failure = (
                (r.request_category is not None and r.request_category.value == "failure_registry")
                or r.id in critical_tr_ids
            )
            if not is_failure:
                continue
            event_date = r.completed_at or r.requested_date or r.cts
            if event_date is not None:
                event_dates.append(event_date)

        event_dates.sort()
        mtbf_raw = cls._mtbf_days_from_dates(event_dates)
        mtbf_days = round(mtbf_raw, 1) if mtbf_raw is not None else None

        return {
            "cumulative_failure_count": len(event_dates),
            "mtbf_days": mtbf_days,
            "first_failure_date": event_dates[0].isoformat() if event_dates else None,
            "last_failure_date": event_dates[-1].isoformat() if event_dates else None,
        }

    @classmethod
    def compute_failure_cohort_stats(cls, db: Session, organization_id: UUID) -> list:
        """
        Fleet-wide failure count / failure rate / MTBF per make/model cohort
        (KPTCL spec §2: "... per make/model cohort").

        Cohort key is (equipment_type, manufacturer, model_number) when
        model_number is recorded — a literal make/model reading, finer than
        the existing "Equipment Failure Performance Analysis" report's own
        voltage_class/age_band grouping. In the real fleet, model_number is
        rarely captured for field equipment (CT/PT/Power Transformers) even
        though manufacturer almost always is, so a unit with no
        model_number falls back to a coarser (equipment_type, manufacturer)
        cohort instead of being dropped — model_number is None for exactly
        those, and every model_precision=False row is a "make-only" cohort
        for that reason, not a data error.

        cohort MTBF = the mean of each cohort MEMBER's own per-unit MTBF,
        averaged only over members with >= 2 failure events of their own
        (same materiality rule as compute_failure_stats). This is
        deliberately NOT one pooled failure timeline across every unit in
        the cohort — units installed years apart would otherwise produce
        artificially short gaps between unrelated units' failures. A cohort
        with too few units (FAILURE_COHORT_MIN_UNITS) is skipped entirely —
        a 1-2 unit "cohort" isn't a real reliability signal yet.
        """
        import config as _config
        from models import TestingRequest, TestResult, CategoryMaster

        min_units = _config.FAILURE_COHORT_MIN_UNITS
        limit     = _config.FAILURE_COHORT_DASHBOARD_LIMIT

        equip_rows = (
            db.query(Equipment.id, Equipment.manufacturer, Equipment.model_number,
                      CategoryMaster.name.label("equipment_type"))
            .outerjoin(CategoryMaster, CategoryMaster.id == Equipment.equipment_type_id)
            .filter(Equipment.organization_id == organization_id,
                    Equipment.status != EquipmentStatus.retired,
                    Equipment.manufacturer.isnot(None))
            .all()
        )
        if not equip_rows:
            return []

        cohorts: dict = {}
        equip_to_cohort: dict = {}
        for eq_id, manufacturer, model_number, equipment_type in equip_rows:
            # None model_number groups every such unit of this type/make
            # into one coarser cohort (dict keys with a None component
            # still compare/hash consistently) rather than being excluded.
            key = (equipment_type, manufacturer, model_number)
            entry = cohorts.setdefault(key, {
                "equipment_type": equipment_type or "Unknown",
                "manufacturer": manufacturer,
                "model_number": model_number,
                "model_precision": model_number is not None,
                "unit_ids": set(),
            })
            entry["unit_ids"].add(eq_id)
            equip_to_cohort[eq_id] = key

        eq_ids = list(equip_to_cohort.keys())
        tr_rows = (
            db.query(TestingRequest.id, TestingRequest.equipment_id,
                      TestingRequest.completed_at, TestingRequest.requested_date,
                      TestingRequest.cts, TestingRequest.request_category)
            .filter(TestingRequest.equipment_id.in_(eq_ids))
            .all()
        )
        tr_ids = [r.id for r in tr_rows]
        critical_tr_ids = set()
        if tr_ids:
            critical_tr_ids = {
                tid for (tid,) in (
                    db.query(TestResult.testing_request_id)
                    .filter(TestResult.testing_request_id.in_(tr_ids))
                    .filter(TestResult.evaluation_result["overall"].astext == "CRITICAL")
                    .distinct()
                    .all()
                )
            }

        # equipment_id -> list of (event_date, is_failure_registry, is_critical_result)
        # source flags kept per-event (not just a bare date) so cohorts can
        # report how much of their failure_count is manually-filed Failure
        # Registry entries vs. a routine test simply coming back CRITICAL —
        # a real distinction management should see, not just a raw total.
        events_by_unit: dict = {}
        for r in tr_rows:
            is_fr = r.request_category is not None and r.request_category.value == "failure_registry"
            is_crit = r.id in critical_tr_ids
            if not (is_fr or is_crit):
                continue
            event_date = r.completed_at or r.requested_date or r.cts
            if event_date is None:
                continue
            events_by_unit.setdefault(r.equipment_id, []).append((event_date, is_fr, is_crit))

        # Yearly failure trend per cohort — real failure history here spans
        # decades (checked against this fleet: as far back as 2001), so a
        # 12-month window (the calibration trend's convention) would show
        # almost nothing. Years are zero-filled across the whole window so
        # a line chart doesn't skip gaps between sparse years.
        trend_years = _config.FAILURE_COHORT_TREND_YEARS
        current_year = datetime.now(timezone.utc).year
        trend_start_year = current_year - trend_years + 1
        trend_year_range = list(range(trend_start_year, current_year + 1))

        for key, entry in cohorts.items():
            failure_count = 0
            fr_count = 0
            critical_only_count = 0
            unit_mtbfs = []
            yearly_counts = {y: 0 for y in trend_year_range}
            for unit_id in entry["unit_ids"]:
                events = sorted(events_by_unit.get(unit_id, []), key=lambda e: e[0])
                dates = [e[0] for e in events]
                failure_count += len(events)
                unit_mtbf = cls._mtbf_days_from_dates(dates)
                if unit_mtbf is not None:
                    unit_mtbfs.append(unit_mtbf)
                for event_date, is_fr, is_crit in events:
                    if is_fr:
                        fr_count += 1
                    elif is_crit:
                        critical_only_count += 1
                    if event_date.year in yearly_counts:
                        yearly_counts[event_date.year] += 1
            entry["failure_count"] = failure_count
            # fr_count + critical_only_count == failure_count always — every
            # event is either a manually-filed Failure Registry entry (fr_count,
            # which also covers the rare case where a CRITICAL result *also*
            # had an FR filed) or a CRITICAL test result with no FR filed
            # (critical_only_count). No double-counting either way.
            entry["fr_count"] = fr_count
            entry["critical_only_count"] = critical_only_count
            entry["unit_count"] = len(entry["unit_ids"])
            entry["mtbf_days"] = round(sum(unit_mtbfs) / len(unit_mtbfs), 1) if unit_mtbfs else None
            entry["yearly_trend"] = [
                {"year": y, "failure_count": yearly_counts[y]} for y in trend_year_range
            ]
            del entry["unit_ids"]

        results = [
            {
                **entry,
                "failure_rate_per_unit": round(entry["failure_count"] / entry["unit_count"], 3),
            }
            for entry in cohorts.values()
            if entry["unit_count"] >= min_units
        ]
        results.sort(key=lambda e: e["failure_rate_per_unit"], reverse=True)
        results = results[:limit]

        # Trend lines are capped to the worst N cohorts so the chart stays
        # readable — everything still gets a rate/MTBF row in the table,
        # just not a line on the trend chart.
        trend_max_series = _config.FAILURE_COHORT_TREND_MAX_SERIES
        for i, entry in enumerate(results):
            if i >= trend_max_series:
                entry["yearly_trend"] = None

        return results