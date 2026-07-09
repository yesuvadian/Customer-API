"""
OrgTestTemplate service — provision, fetch and update per-org test templates.

Global defaults (org_id=NULL) are seeded from test_templates.py.
Org-specific rows clone global defaults and can be customised via the designer.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import CategoryDetails, OrgTestTemplate


def active_template_filter():
    """SQLAlchemy filter clause: keep templates where is_active is missing or true."""
    return or_(
        ~OrgTestTemplate.template_data.has_key("is_active"),  # noqa: W601
        OrgTestTemplate.template_data["is_active"].astext == "true",
    )


class OrgTestTemplateService:

    def __init__(self, db: Session):
        self.db = db

    # ─── Read ────────────────────────────────────────────────

    def get_by_id(self, template_id: UUID) -> OrgTestTemplate:
        tmpl = self.db.query(OrgTestTemplate).filter(OrgTestTemplate.id == template_id).first()
        if not tmpl:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
        return tmpl

    @staticmethod
    def _is_active(tpl: OrgTestTemplate) -> bool:
        """Return False only when is_active is explicitly set to false in template_data."""
        td = tpl.template_data
        if not isinstance(td, dict):
            return True
        return td.get("is_active", True) is not False

    def list_templates(self, org_id: Optional[UUID] = None, active_only: bool = False) -> List[OrgTestTemplate]:
        """List global defaults (org_id=None) or org-specific rows.
        Deduplicates by template_key — keeps the most recently updated row
        when the same key was accidentally provisioned twice.
        """
        q = self.db.query(OrgTestTemplate)
        if org_id is None:
            q = q.filter(OrgTestTemplate.org_id == None)  # noqa: E711
        else:
            q = q.filter(OrgTestTemplate.org_id == org_id)
        if active_only:
            q = q.filter(active_template_filter())
        rows = q.order_by(OrgTestTemplate.template_key, OrgTestTemplate.version.desc()).all()
        # Deduplicate: keep first (highest version) occurrence per key
        seen_keys: set = set()
        unique = []
        for r in rows:
            if r.template_key in seen_keys:
                continue
            seen_keys.add(r.template_key)
            unique.append(r)
        return unique

    def canonical_templates_for_org(self, org_id: Optional[UUID] = None) -> dict[int, "OrgTestTemplate"]:
        """Return a test_type_id → template mapping that mirrors what the Template
        Designer renders: system templates as base, org-specific templates override
        where they exist.  Only test types with a template in this map should appear
        in the TR form (no template = no testing).
        """
        # Start with system (global) templates
        system = self.list_templates(org_id=None)
        merged: dict[int, OrgTestTemplate] = {
            t.test_type_id: t for t in system if t.test_type_id is not None
        }
        # Org templates override system for the same test_type_id
        if org_id:
            org_tpls = self.list_templates(org_id=org_id)
            for t in org_tpls:
                if t.test_type_id is not None:
                    merged[t.test_type_id] = t
        return merged

    OVERALL_KEY = "overall_assessment"

    def get_overall_assessment(self, org_id: Optional[UUID] = None) -> OrgTestTemplate:
        """Return the overall assessment template (org-specific → global fallback)."""
        if org_id:
            tmpl = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.org_id == org_id,
                    OrgTestTemplate.template_key == self.OVERALL_KEY,
                )
                .first()
            )
            if tmpl:
                return tmpl
        tmpl = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.org_id == None,  # noqa: E711
                OrgTestTemplate.template_key == self.OVERALL_KEY,
            )
            .first()
        )
        if tmpl:
            return tmpl
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Overall assessment template not found — run /provision/global first",
        )

    def get_for_test_type(self, test_type_id: int, org_id: Optional[UUID] = None) -> OrgTestTemplate:
        """
        Return the best-match template:
          1. org-specific row (if org_id given)
          2. global default
          3. 404 if nothing found
        """
        if org_id:
            tmpl = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.org_id == org_id,
                    OrgTestTemplate.test_type_id == test_type_id,
                )
                .first()
            )
            if tmpl:
                return tmpl

        # fallback → global default
        tmpl = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.org_id == None,  # noqa: E711
                OrgTestTemplate.test_type_id == test_type_id,
            )
            .first()
        )
        if tmpl:
            return tmpl

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No template found for test_type_id={test_type_id}",
        )

    def get_by_template_key(self, template_key: str, respect_active: bool = True) -> OrgTestTemplate:
        """Lookup an org template by its template_key (any org or global)."""
        tmpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == template_key)
            .first()
        )
        if tmpl:
            if respect_active and not self._is_active(tmpl):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Template '{template_key}' is disabled. Enable it in the Template Designer to use it.",
                )
            return tmpl
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No template found for key={template_key}",
        )

    # ─── Write ───────────────────────────────────────────────

    def create_template(
        self,
        template_key: str,
        template_data: dict,
        test_type_id: Optional[int],
        org_id: Optional[UUID],
        created_by: Optional[UUID],
    ) -> OrgTestTemplate:
        existing = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.org_id == org_id,
                OrgTestTemplate.template_key == template_key,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template with this key already exists for this org",
            )
        tmpl = OrgTestTemplate(
            org_id=org_id,
            template_key=template_key,
            test_type_id=test_type_id,
            template_data=template_data,
            is_system=False,
            version=1,
        )
        self.db.add(tmpl)
        self.db.commit()
        self.db.refresh(tmpl)
        return tmpl

    def update_template(
        self,
        template_id: UUID,
        template_data: dict,
        modified_by: Optional[UUID],
    ) -> OrgTestTemplate:
        from sqlalchemy.orm.attributes import flag_modified

        tmpl = self.get_by_id(template_id)
        tmpl.template_data = template_data
        flag_modified(tmpl, "template_data")
        tmpl.version = (tmpl.version or 1) + 1
        tmpl.modified_by = modified_by

        # When a global (system) template is updated, cascade the new
        # template_data to ALL other rows with the same template_key so
        # that the tester always sees the latest definition regardless of
        # which test_type_id or org_id it resolves to.
        # This covers two cases:
        #   1. Org-specific clones (same key, non-null org_id)
        #   2. Other global rows with the same key but a different test_type_id
        #      (e.g. "Capacitance & Tan Delta Test (Transformer)" exists under
        #      both Power Transformer and Feeder Protection Relays masters)
        if tmpl.org_id is None:
            siblings = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.template_key == tmpl.template_key,
                    OrgTestTemplate.id != tmpl.id,
                )
                .all()
            )
            for sibling in siblings:
                sibling.template_data = template_data
                flag_modified(sibling, "template_data")
                sibling.version = tmpl.version

        self.db.commit()
        self.db.refresh(tmpl)
        return tmpl

    def reset_to_global(
        self,
        template_id: UUID,
        modified_by: Optional[UUID],
    ) -> OrgTestTemplate:
        """Reset an org template back to the global default's template_data."""
        tmpl = self.get_by_id(template_id)
        if tmpl.org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot reset a global default template",
            )
        global_tmpl = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.org_id == None,  # noqa: E711
                OrgTestTemplate.template_key == tmpl.template_key,
            )
            .first()
        )
        if not global_tmpl:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No global default found for this template key",
            )
        from sqlalchemy.orm.attributes import flag_modified
        tmpl.template_data = global_tmpl.template_data
        flag_modified(tmpl, "template_data")
        tmpl.version = global_tmpl.version
        tmpl.modified_by = modified_by
        self.db.commit()
        self.db.refresh(tmpl)
        return tmpl

    def delete_template(self, template_id: UUID) -> None:
        tmpl = self.get_by_id(template_id)
        if tmpl.is_system and tmpl.org_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete a system global template",
            )
        self.db.delete(tmpl)
        self.db.commit()

    # ─── Provisioning ────────────────────────────────────────

    def provision_overall_assessment(self) -> bool:
        """Seed or update the global 'overall_assessment' template. Returns True if inserted, False if updated."""
        existing = (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.org_id == None,  # noqa: E711
                OrgTestTemplate.template_key == self.OVERALL_KEY,
            )
            .first()
        )

        default_data = {
            "name": "Overall Assessment",
            "sections": [
                {
                    "title": "Overall Assessment",
                    "fields": [
                        {
                            "key": "overall_result",
                            "label": "Result",
                            "type": "dropdown",
                            "required": True,
                            "read_only": False,
                            "options": ["Pass", "Fail", "Conditional Pass", "Refer for Retesting"],
                        },
                        {
                            "key": "overall_remarks",
                            "label": "Remarks",
                            "type": "textarea",
                            "required": False,
                            "read_only": False,
                        },
                        {
                            "key": "overall_recommendation",
                            "label": "Recommendation",
                            "type": "textarea",
                            "required": False,
                            "read_only": False,
                        },
                        {
                            "key": "tested_by",
                            "label": "Tested By",
                            "type": "text",
                            "required": False,
                            "read_only": False,
                        },
                        {
                            "key": "date_of_testing",
                            "label": "Date of Testing",
                            "type": "date",
                            "required": False,
                            "read_only": False,
                        },
                    ],
                },
                {
                    "title": "Outcome & Scheduling",
                    "fields": [
                        {
                            "key": "recommendation_type",
                            "label": "Recommendation Type",
                            "type": "dropdown",
                            "required": True,
                            "read_only": False,
                            "options": ["Pass", "Fail", "Conditional", "Retest"],
                        },
                        {
                            "key": "next_action",
                            "label": "Next Action",
                            "type": "dropdown",
                            "required": True,
                            "read_only": False,
                            "options": ["None", "Test", "Maintenance", "Inspection", "Repair", "Procurement"],
                        },
                        {
                            "key": "outcome_schedule",
                            "label": "Schedule",
                            "type": "outcome_schedule",
                            "required": False,
                            "read_only": False,
                            "depends_on": {
                                "field": "next_action",
                                "value_in": ["Maintenance", "Inspection", "Repair"],
                            },
                        },
                        {
                            "key": "outcome_summary",
                            "label": "Summary",
                            "type": "textarea",
                            "required": True,
                            "read_only": False,
                        },
                        {
                            "key": "outcome_notes",
                            "label": "Detailed Notes",
                            "type": "textarea",
                            "required": False,
                            "read_only": False,
                        },
                    ],
                },
            ],
        }

        if existing:
            # Update to pick up any new sections/fields added to the definition
            existing.template_data = default_data
            existing.version = (existing.version or 1) + 1
            self.db.commit()
            return False  # False = updated (not a fresh insert)

        self.db.add(OrgTestTemplate(
            template_key=self.OVERALL_KEY,
            org_id=None,
            test_type_id=None,
            template_data=default_data,
            is_system=True,
            version=1,
        ))
        self.db.commit()
        return True  # True = inserted fresh

    def provision_global_defaults(self) -> int:
        """
        Seed global default templates from test_templates.py and nameplate_templates.py.
        Creates one OrgTestTemplate row per test_type_id that maps to a template.
        Safe to call multiple times — skips already-existing rows.
        Returns the count of newly inserted rows.
        """
        from test_templates import TEST_TEMPLATES, TEST_TYPE_TO_TEMPLATE
        from models import CategoryMaster

        inserted = 0
        from sqlalchemy.orm.attributes import flag_modified

        # ── Test / maintenance / inspection / repair templates ────────────────
        # One OrgTestTemplate row per unique template_key (org_id=None).
        # The first CategoryDetail whose name maps to a given key wins; subsequent
        # details with the same name (other equipment masters) are intentionally
        # skipped — they share the same template design.
        # seen_keys tracks in-memory to avoid the flush-gap bug where multiple
        # rows were created for the same key within a single session.
        seen_keys: set = set()

        # Pre-load existing system rows keyed by template_key for fast lookup
        existing_by_key: dict = {
            r.template_key: r
            for r in self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.org_id == None)  # noqa: E711
            .all()
        }

        for type_name, template_key in TEST_TYPE_TO_TEMPLATE.items():
            template_data = TEST_TEMPLATES.get(template_key)
            if not template_data:
                continue

            if template_key in seen_keys:
                continue  # already handled this key in this run

            detail = (
                self.db.query(CategoryDetails)
                .filter(CategoryDetails.name == type_name)
                .first()
            )
            if not detail:
                continue

            existing = existing_by_key.get(template_key)
            if existing:
                existing.template_data = template_data
                existing.version = (existing.version or 1) + 1
                flag_modified(existing, "template_data")
                # Cascade to org-specific copies
                for copy in (
                    self.db.query(OrgTestTemplate)
                    .filter(
                        OrgTestTemplate.template_key == template_key,
                        OrgTestTemplate.org_id != None,  # noqa: E711
                    )
                    .all()
                ):
                    copy.template_data = template_data
                    copy.version = existing.version
                    flag_modified(copy, "template_data")
            else:
                new_row = OrgTestTemplate(
                    org_id=None,
                    template_key=template_key,
                    test_type_id=detail.id,
                    template_data=template_data,
                    is_system=True,
                    version=1,
                )
                self.db.add(new_row)
                existing_by_key[template_key] = new_row
                inserted += 1

            seen_keys.add(template_key)

        # ── Nameplate templates ───────────────────────────────────────────────
        from seed import NAMEPLATE_TEMPLATES, NAMEPLATE_TYPE_TO_TEMPLATE

        for eq_type_name, template_key in NAMEPLATE_TYPE_TO_TEMPLATE.items():
            template_data = NAMEPLATE_TEMPLATES.get(template_key)
            if not template_data:
                continue

            # "Nameplate" CategoryDetails under this equipment's CategoryMaster
            detail = (
                self.db.query(CategoryDetails)
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(
                    CategoryDetails.name == "Nameplate",
                    CategoryDetails.category_type == "nameplate",
                    CategoryMaster.name == eq_type_name,
                )
                .first()
            )
            if not detail:
                continue

            existing = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.org_id == None,  # noqa: E711
                    OrgTestTemplate.test_type_id == detail.id,
                )
                .first()
            )
            if existing:
                existing.template_data = template_data
                existing.template_key = template_key
                continue

            self.db.add(OrgTestTemplate(
                org_id=None,
                template_key=template_key,
                test_type_id=detail.id,
                template_data=template_data,
                is_system=True,
                version=1,
            ))
            inserted += 1

        self.db.commit()
        return inserted

    def provision_for_org(self, org_id: UUID, created_by: Optional[UUID] = None) -> int:
        """
        Clone all global defaults for a specific org (skip if already exists).
        Call this when a new org / customer user is registered.
        Returns the count of newly inserted rows.
        """
        globals_ = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.org_id == None)  # noqa: E711
            .all()
        )
        inserted = 0
        for g in globals_:
            exists = (
                self.db.query(OrgTestTemplate)
                .filter(
                    OrgTestTemplate.org_id == org_id,
                    OrgTestTemplate.template_key == g.template_key,
                )
                .first()
            )
            if exists:
                continue
            clone = OrgTestTemplate(
                org_id=org_id,
                template_key=g.template_key,
                test_type_id=g.test_type_id,
                template_data=g.template_data,
                is_system=False,
                version=g.version,
            )
            self.db.add(clone)
            inserted += 1

        self.db.commit()
        return inserted
