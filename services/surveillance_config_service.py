"""
surveillance_config_service.py
───────────────────────────────
Hierarchical configuration resolution for post-commissioning surveillance workflows.

Resolution Order (fallback chain):
  1. Department-specific config (surveillance_config WHERE department_id = X)
  2. Organization-specific config (surveillance_config WHERE organization_id = X, department_id = NULL)
  3. System-wide default (surveillance_config WHERE organization_id = NULL, department_id = NULL)
  4. Hard-coded fallback (.env or constants)

Usage:
    config = SurveillanceConfigService.get_config(
        session, organization_id, department_id
    )
    period_months = config["surveillance_period_months"]  # 24
    frequency_mult = config["frequency_multiplier"]        # 2.0
    abnormal_statuses = config["abnormal_statuses"]        # ["FAIL", "MARGINAL", ...]
"""

from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from models import SurveillanceConfig


class SurveillanceConfigService:
    """Service for resolving surveillance configuration with hierarchical fallback."""

    # Hard-coded system defaults (used when no database config exists)
    DEFAULT_SURVEILLANCE_PERIOD_MONTHS = int(os.getenv("SURVEILLANCE_PERIOD_MONTHS", "24"))
    DEFAULT_FREQUENCY_MULTIPLIER = float(os.getenv("SURVEILLANCE_FREQUENCY_MULTIPLIER", "2.0"))
    DEFAULT_ABNORMAL_STATUSES = ["FAIL", "MARGINAL", "CRITICAL", "ALERT"]
    DEFAULT_QUALITY_THRESHOLD_FAIR = 20.0  # ≥20% abnormal = POOR

    @classmethod
    def get_config(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> dict:
        """
        Resolve surveillance configuration using hierarchical fallback.

        Args:
            session: Database session
            organization_id: Organization UUID (optional)
            department_id: Department UUID (optional)

        Returns:
            dict with keys:
                - surveillance_period_months: int
                - frequency_multiplier: float
                - abnormal_statuses: list[str]
                - quality_threshold_fair: float
                - config_source: str ("department" | "organization" | "system" | "hardcoded")

        Resolution order:
            1. Department-specific (if department_id provided)
            2. Organization-specific (if organization_id provided)
            3. System-wide default (NULL org + dept)
            4. Hard-coded fallback
        """
        config_source = "hardcoded"

        # 1. Try department-specific config
        if department_id:
            dept_config = (
                session.query(SurveillanceConfig)
                .filter(
                    and_(
                        SurveillanceConfig.department_id == department_id,
                        SurveillanceConfig.is_active == True,
                    )
                )
                .first()
            )
            if dept_config:
                return cls._build_config_dict(dept_config, "department")

        # 2. Try organization-specific config
        if organization_id:
            org_config = (
                session.query(SurveillanceConfig)
                .filter(
                    and_(
                        SurveillanceConfig.organization_id == organization_id,
                        SurveillanceConfig.department_id.is_(None),
                        SurveillanceConfig.is_active == True,
                    )
                )
                .first()
            )
            if org_config:
                return cls._build_config_dict(org_config, "organization")

        # 3. Try system-wide default
        system_config = (
            session.query(SurveillanceConfig)
            .filter(
                and_(
                    SurveillanceConfig.organization_id.is_(None),
                    SurveillanceConfig.department_id.is_(None),
                    SurveillanceConfig.is_active == True,
                )
            )
            .first()
        )
        if system_config:
            return cls._build_config_dict(system_config, "system")

        # 4. Fall back to hard-coded defaults
        return {
            "surveillance_period_months": cls.DEFAULT_SURVEILLANCE_PERIOD_MONTHS,
            "frequency_multiplier": cls.DEFAULT_FREQUENCY_MULTIPLIER,
            "abnormal_statuses": cls.DEFAULT_ABNORMAL_STATUSES,
            "quality_threshold_fair": cls.DEFAULT_QUALITY_THRESHOLD_FAIR,
            "config_source": "hardcoded",
        }

    @staticmethod
    def _build_config_dict(config: SurveillanceConfig, source: str) -> dict:
        """Build config dictionary from SurveillanceConfig model."""
        return {
            "surveillance_period_months": config.surveillance_period_months,
            "frequency_multiplier": float(config.frequency_multiplier),
            "abnormal_statuses": config.abnormal_statuses or ["FAIL", "MARGINAL", "CRITICAL", "ALERT"],
            "quality_threshold_fair": float(config.quality_threshold_fair),
            "config_source": source,
        }

    @classmethod
    def get_surveillance_period_months(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> int:
        """Get surveillance period in months (default: 24)."""
        config = cls.get_config(session, organization_id, department_id)
        return config["surveillance_period_months"]

    @classmethod
    def get_frequency_multiplier(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> float:
        """
        Get test frequency multiplier (default: 2.0).

        Example:
            Normal DGA schedule: 12 months
            Surveillance DGA: 12 / 2.0 = 6 months
        """
        config = cls.get_config(session, organization_id, department_id)
        return config["frequency_multiplier"]

    @classmethod
    def get_abnormal_statuses(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> list[str]:
        """Get list of result statuses that trigger abnormal flagging."""
        config = cls.get_config(session, organization_id, department_id)
        return config["abnormal_statuses"]

    @classmethod
    def get_quality_threshold_fair(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> float:
        """
        Get quality rating threshold for FAIR rating (default: 20.0%).

        Quality rating logic:
            GOOD: 0% abnormal
            FAIR: 1% - threshold% abnormal
            POOR: ≥ threshold% abnormal
        """
        config = cls.get_config(session, organization_id, department_id)
        return config["quality_threshold_fair"]

    @classmethod
    def calculate_surveillance_periodicity_days(
        cls,
        session: Session,
        normal_periodicity_days: int,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> int:
        """
        Calculate surveillance test frequency based on normal schedule.

        Args:
            normal_periodicity_days: Normal test frequency (e.g., 365 days for annual DGA)
            organization_id: Organization UUID
            department_id: Department UUID

        Returns:
            Surveillance periodicity in days

        Example:
            Normal DGA: 365 days (12 months)
            Multiplier: 2.0
            Surveillance: 365 / 2.0 = 182 days (~6 months)
        """
        multiplier = cls.get_frequency_multiplier(session, organization_id, department_id)
        return int(normal_periodicity_days / multiplier)

    @classmethod
    def is_result_abnormal(
        cls,
        session: Session,
        result_status: str,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> bool:
        """
        Check if a test result status should be flagged as abnormal.

        Args:
            result_status: Test result status (e.g., "PASS", "FAIL", "MARGINAL")
            organization_id: Organization UUID
            department_id: Department UUID

        Returns:
            True if result_status is in abnormal_statuses list
        """
        if not result_status:
            return False

        abnormal_statuses = cls.get_abnormal_statuses(session, organization_id, department_id)
        return result_status.upper() in [s.upper() for s in abnormal_statuses]

    @classmethod
    def calculate_quality_rating(
        cls,
        session: Session,
        total_tests: int,
        abnormal_tests: int,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
    ) -> str:
        """
        Calculate quality rating based on abnormal test percentage.

        Args:
            total_tests: Total number of tests conducted
            abnormal_tests: Number of abnormal results
            organization_id: Organization UUID
            department_id: Department UUID

        Returns:
            "GOOD" | "FAIR" | "POOR"

        Logic:
            GOOD: 0% abnormal
            FAIR: 1% - threshold% abnormal
            POOR: ≥ threshold% abnormal
        """
        if total_tests == 0:
            return "GOOD"  # No tests = default to GOOD

        abnormal_rate = (abnormal_tests / total_tests) * 100

        if abnormal_rate == 0:
            return "GOOD"

        threshold = cls.get_quality_threshold_fair(session, organization_id, department_id)
        if abnormal_rate < threshold:
            return "FAIR"
        else:
            return "POOR"

    @classmethod
    def create_or_update_config(
        cls,
        session: Session,
        organization_id: Optional[UUID] = None,
        department_id: Optional[UUID] = None,
        surveillance_period_months: int = 24,
        frequency_multiplier: float = 2.0,
        abnormal_statuses: Optional[list[str]] = None,
        quality_threshold_fair: float = 20.0,
        user_id: Optional[UUID] = None,
    ) -> SurveillanceConfig:
        """
        Create or update surveillance configuration.

        Args:
            session: Database session
            organization_id: Organization UUID (NULL for system-wide)
            department_id: Department UUID (NULL for org-wide)
            surveillance_period_months: Surveillance duration in months
            frequency_multiplier: Test frequency multiplier
            abnormal_statuses: List of abnormal status values
            quality_threshold_fair: Threshold for FAIR rating
            user_id: User creating/modifying config

        Returns:
            SurveillanceConfig instance
        """
        if abnormal_statuses is None:
            abnormal_statuses = cls.DEFAULT_ABNORMAL_STATUSES

        # Check if config already exists
        existing = (
            session.query(SurveillanceConfig)
            .filter(
                and_(
                    SurveillanceConfig.organization_id == organization_id,
                    SurveillanceConfig.department_id == department_id,
                )
            )
            .first()
        )

        if existing:
            # Update existing config
            existing.surveillance_period_months = surveillance_period_months
            existing.frequency_multiplier = frequency_multiplier
            existing.abnormal_statuses = abnormal_statuses
            existing.quality_threshold_fair = quality_threshold_fair
            existing.modified_by = user_id
            existing.is_active = True
            session.commit()
            return existing
        else:
            # Create new config
            new_config = SurveillanceConfig(
                organization_id=organization_id,
                department_id=department_id,
                surveillance_period_months=surveillance_period_months,
                frequency_multiplier=frequency_multiplier,
                abnormal_statuses=abnormal_statuses,
                quality_threshold_fair=quality_threshold_fair,
                created_by=user_id,
                modified_by=user_id,
                is_active=True,
            )
            session.add(new_config)
            session.commit()
            return new_config
