"""
surveillance_template_service.py
─────────────────────────────────
Pre-populates surveillance stage forms with actual test data.

Queries testing_requests and repair_surveillance_tests to fill form fields
with real data when officers open quarterly review or final evaluation forms.

Usage:
    # In RepairWorkflowService when loading stage form
    if stage.template_key == 'surveillance_quarter_review':
        pre_populated = SurveillanceTemplateService.get_quarter_review_data(
            db, workflow_id, quarter_number
        )
    elif stage.template_key == 'surveillance_final_evaluation':
        pre_populated = SurveillanceTemplateService.get_final_evaluation_data(
            db, workflow_id
        )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from models import (
    RepairSurveillanceTest,
    RepairWorkflow,
    TestingRequest,
)
from services.surveillance_config_service import SurveillanceConfigService

logger = logging.getLogger(__name__)


class SurveillanceTemplateService:
    """Service for pre-populating surveillance stage forms with test data."""

    @staticmethod
    def get_quarter_review_data(
        db: Session,
        workflow_id: UUID,
        quarter_number: int
    ) -> dict:
        """
        Pre-populate quarterly review form with test results.

        Args:
            db: Database session
            workflow_id: Surveillance workflow ID
            quarter_number: Quarter number (1-4)

        Returns:
            dict with pre-populated form fields
        """
        workflow = db.query(RepairWorkflow).filter(
            RepairWorkflow.id == workflow_id
        ).first()

        if not workflow:
            return {}

        # Get testing requests for this quarter
        testing_requests = (
            db.query(TestingRequest)
            .filter(
                and_(
                    TestingRequest.surveillance_workflow_id == workflow_id,
                    TestingRequest.surveillance_quarter == quarter_number
                )
            )
            .all()
        )

        # Build test summary table
        test_summary_rows = []
        abnormal_count = 0
        completed_count = 0

        for tr in testing_requests:
            is_abnormal = SurveillanceConfigService.is_result_abnormal(
                db, tr.form_data.get('result_status') if tr.form_data else None,
                organization_id=workflow.organization_id,
                department_id=workflow.department_id
            ) if tr.form_data else False

            if tr.status == 'completed':
                completed_count += 1
                if is_abnormal:
                    abnormal_count += 1

            test_summary_rows.append({
                'test_type': tr.test_type.name if tr.test_type else 'Unknown',
                'status': tr.status,
                'tested_at': tr.completed_at.isoformat() if tr.completed_at else None,
                'result_status': tr.form_data.get('result_status') if tr.form_data else None,
                'is_abnormal': is_abnormal,
            })

        # Calculate statistics
        total_tests = len(testing_requests)
        abnormal_rate = (abnormal_count / completed_count * 100) if completed_count > 0 else 0

        # Pre-populated form data
        return {
            'quarter_number': quarter_number,
            'date_range': f'Q{quarter_number} ({workflow.start_date.strftime("%b %Y") if workflow.start_date else "N/A"})',
            'parent_repair_workflow': str(workflow.parent_workflow_id) if workflow.parent_workflow_id else 'N/A',
            'equipment_name': workflow.equipment.name if workflow.equipment else 'N/A',
            'test_summary_table': test_summary_rows,
            'total_tests_planned': total_tests,
            'tests_completed': completed_count,
            'abnormal_count': abnormal_count,
            'abnormal_rate': round(abnormal_rate, 1),
        }

    @staticmethod
    def get_final_evaluation_data(
        db: Session,
        workflow_id: UUID
    ) -> dict:
        """
        Pre-populate final evaluation form with 24-month summary.

        Args:
            db: Database session
            workflow_id: Surveillance workflow ID

        Returns:
            dict with pre-populated form fields
        """
        workflow = db.query(RepairWorkflow).filter(
            RepairWorkflow.id == workflow_id
        ).first()

        if not workflow:
            return {}

        # Get all surveillance tests across all quarters
        all_tests = (
            db.query(RepairSurveillanceTest)
            .filter(RepairSurveillanceTest.surveillance_workflow_id == workflow_id)
            .all()
        )

        # Calculate overall statistics
        total_tests = len(all_tests)
        completed_tests = [t for t in all_tests if t.test_status == 'completed']
        abnormal_tests = [t for t in all_tests if t.is_abnormal]

        # Calculate quality rating
        quality_rating = SurveillanceConfigService.calculate_quality_rating(
            db,
            total_tests=len(completed_tests),
            abnormal_tests=len(abnormal_tests),
            organization_id=workflow.organization_id,
            department_id=workflow.department_id
        )

        # Calculate surveillance duration
        surveillance_duration = '24 months'
        if workflow.start_date and workflow.end_date:
            months = (workflow.end_date.year - workflow.start_date.year) * 12 + \
                     (workflow.end_date.month - workflow.start_date.month)
            surveillance_duration = f'{months} months'

        # Build quarterly breakdown
        quarter_breakdown = []
        for quarter in range(1, 5):
            quarter_tests = [t for t in all_tests if t.quarter_number == quarter]
            quarter_completed = [t for t in quarter_tests if t.test_status == 'completed']
            quarter_abnormal = [t for t in quarter_tests if t.is_abnormal]
            quarter_rate = (len(quarter_abnormal) / len(quarter_completed) * 100) if quarter_completed else 0

            quarter_breakdown.append({
                'quarter': f'Q{quarter}',
                'tests_completed': len(quarter_completed),
                'abnormal_count': len(quarter_abnormal),
                'abnormal_rate': round(quarter_rate, 1),
                'quarter_status': 'approved',  # From stage_instance data if available
            })

        # Calculate trends (simplified - could be enhanced with actual trend analysis)
        trends = SurveillanceTemplateService._calculate_trends(db, workflow_id, all_tests)

        # Pre-populated form data
        return {
            'surveillance_duration': surveillance_duration,
            'start_date': workflow.start_date.isoformat() if workflow.start_date else None,
            'end_date': workflow.end_date.isoformat() if workflow.end_date else None,
            'parent_repair_workflow': str(workflow.parent_workflow_id) if workflow.parent_workflow_id else 'N/A',
            'equipment_name': workflow.equipment.name if workflow.equipment else 'N/A',
            'vendor_name': workflow.vendor_name if hasattr(workflow, 'vendor_name') else 'N/A',
            'total_tests_conducted': len(completed_tests),
            'abnormal_tests_count': len(abnormal_tests),
            'abnormal_rate': round((len(abnormal_tests) / len(completed_tests) * 100), 1) if completed_tests else 0,
            'quality_rating': quality_rating,
            'quarter_breakdown_table': quarter_breakdown,
            'dga_trend': trends.get('DGA', 'Stable'),
            'bdv_trend': trends.get('BDV', 'Stable'),
            'ir_trend': trends.get('IR', 'Stable'),
            'oil_quality_trend': trends.get('Oil Quality', 'Stable'),
        }

    @staticmethod
    def _calculate_trends(
        db: Session,
        workflow_id: UUID,
        all_tests: list
    ) -> dict:
        """
        Calculate test result trends (Improving / Stable / Deteriorating).

        Simplified implementation - could be enhanced with actual numerical
        analysis of test values over time.

        Args:
            db: Database session
            workflow_id: Surveillance workflow ID
            all_tests: List of all surveillance tests

        Returns:
            dict mapping test type names to trend strings
        """
        trends = {}

        # Group tests by test type
        test_types = {}
        for test in all_tests:
            if test.test_type_id:
                test_type_name = test.test_type.name if test.test_type else 'Unknown'
                if test_type_name not in test_types:
                    test_types[test_type_name] = []
                test_types[test_type_name].append(test)

        # Analyze each test type
        for test_type_name, tests in test_types.items():
            # Sort by quarter
            sorted_tests = sorted(tests, key=lambda t: t.quarter_number or 0)
            completed_tests = [t for t in sorted_tests if t.test_status == 'completed']

            if len(completed_tests) < 2:
                trends[test_type_name] = 'Stable'
                continue

            # Simple trend: compare Q1 vs Q4 abnormal rate
            q1_tests = [t for t in completed_tests if t.quarter_number == 1]
            q4_tests = [t for t in completed_tests if t.quarter_number == 4]

            if q1_tests and q4_tests:
                q1_abnormal = sum(1 for t in q1_tests if t.is_abnormal)
                q4_abnormal = sum(1 for t in q4_tests if t.is_abnormal)

                if q4_abnormal < q1_abnormal:
                    trends[test_type_name] = 'Improving'
                elif q4_abnormal > q1_abnormal:
                    trends[test_type_name] = 'Deteriorating'
                else:
                    trends[test_type_name] = 'Stable'
            else:
                # Check overall abnormal rate trend
                early_tests = completed_tests[:len(completed_tests)//2]
                late_tests = completed_tests[len(completed_tests)//2:]

                early_abnormal_rate = sum(1 for t in early_tests if t.is_abnormal) / len(early_tests) if early_tests else 0
                late_abnormal_rate = sum(1 for t in late_tests if t.is_abnormal) / len(late_tests) if late_tests else 0

                if late_abnormal_rate < early_abnormal_rate - 0.1:
                    trends[test_type_name] = 'Improving'
                elif late_abnormal_rate > early_abnormal_rate + 0.1:
                    trends[test_type_name] = 'Deteriorating'
                else:
                    trends[test_type_name] = 'Stable'

        return trends

    @staticmethod
    def get_test_summary_for_quarter(
        db: Session,
        workflow_id: UUID,
        quarter_number: int
    ) -> dict:
        """
        Get summary statistics for a specific quarter.

        Useful for dashboard widgets and quick summaries.

        Args:
            db: Database session
            workflow_id: Surveillance workflow ID
            quarter_number: Quarter number (1-4)

        Returns:
            dict with summary stats
        """
        tests = (
            db.query(RepairSurveillanceTest)
            .filter(
                and_(
                    RepairSurveillanceTest.surveillance_workflow_id == workflow_id,
                    RepairSurveillanceTest.quarter_number == quarter_number
                )
            )
            .all()
        )

        completed = [t for t in tests if t.test_status == 'completed']
        abnormal = [t for t in tests if t.is_abnormal]

        return {
            'total_tests': len(tests),
            'completed_tests': len(completed),
            'abnormal_tests': len(abnormal),
            'abnormal_rate': (len(abnormal) / len(completed) * 100) if completed else 0,
            'pending_tests': len(tests) - len(completed),
        }

    @staticmethod
    def get_overall_summary(
        db: Session,
        workflow_id: UUID
    ) -> dict:
        """
        Get overall surveillance workflow summary.

        Args:
            db: Database session
            workflow_id: Surveillance workflow ID

        Returns:
            dict with overall stats
        """
        workflow = db.query(RepairWorkflow).filter(
            RepairWorkflow.id == workflow_id
        ).first()

        if not workflow:
            return {}

        all_tests = (
            db.query(RepairSurveillanceTest)
            .filter(RepairSurveillanceTest.surveillance_workflow_id == workflow_id)
            .all()
        )

        completed = [t for t in all_tests if t.test_status == 'completed']
        abnormal = [t for t in all_tests if t.is_abnormal]

        quality_rating = SurveillanceConfigService.calculate_quality_rating(
            db,
            total_tests=len(completed),
            abnormal_tests=len(abnormal),
            organization_id=workflow.organization_id,
            department_id=workflow.department_id
        )

        return {
            'workflow_id': str(workflow_id),
            'status': workflow.status,
            'total_tests': len(all_tests),
            'completed_tests': len(completed),
            'abnormal_tests': len(abnormal),
            'abnormal_rate': (len(abnormal) / len(completed) * 100) if completed else 0,
            'quality_rating': quality_rating,
            'start_date': workflow.start_date.isoformat() if workflow.start_date else None,
            'end_date': workflow.end_date.isoformat() if workflow.end_date else None,
        }
