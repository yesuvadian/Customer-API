"""
Tester Auto-Assignment Service

Automatically assigns testers to testing requests based on:
- Department/location
- Tester availability
- Current workload
- Role-based rules
- Assignment strategy (round-robin, least-loaded, priority-based)
"""

from typing import Optional, List, Dict, Tuple
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, case
from datetime import datetime, timedelta
import random

from models import (
    TestingRequest,
    User,
    UserRole,
    OrgRole,
    OrgDepartment,
    TestingRequestStatus
)


class TesterAutoAssignmentService:
    """
    Service to automatically assign testers to testing requests.
    """

    def __init__(self, db: Session):
        self.db = db

    # ========================================
    # 1. AUTO-ASSIGN TESTER
    # ========================================

    def auto_assign_tester(
        self,
        testing_request: TestingRequest,
        strategy: str = 'least_loaded'
    ) -> Tuple[bool, Optional[UUID], str]:
        """
        Automatically assign a tester to a testing request.

        Args:
            testing_request: The testing request to assign
            strategy: Assignment strategy ('least_loaded', 'round_robin', 'random', 'priority')

        Returns:
            (success, tester_id, message)
        """
        # Find eligible testers
        eligible_testers = self._find_eligible_testers(testing_request)

        if not eligible_testers:
            return False, None, "No eligible testers found for this request"

        # Apply assignment strategy
        if strategy == 'least_loaded':
            tester = self._assign_least_loaded(eligible_testers)
        elif strategy == 'round_robin':
            tester = self._assign_round_robin(eligible_testers)
        elif strategy == 'priority':
            tester = self._assign_by_priority(eligible_testers)
        elif strategy == 'random':
            tester = random.choice(eligible_testers)
        else:
            # Default to least loaded
            tester = self._assign_least_loaded(eligible_testers)

        if not tester:
            return False, None, "Failed to assign tester"

        return True, tester['user_id'], f"Auto-assigned to {tester['name']}"

    # ========================================
    # 2. FIND ELIGIBLE TESTERS
    # ========================================

    def _find_eligible_testers(
        self,
        testing_request: TestingRequest
    ) -> List[Dict]:
        """
        Find testers who are eligible for this testing request.

        Eligibility criteria:
        - Has 'Tester' role
        - Same organization as request
        - Same department or parent department (department tree)
        - User is active
        - Role is active
        """
        # Get tester role for the organization
        tester_role = self.db.query(OrgRole).filter(
            and_(
                OrgRole.organization_id == testing_request.organization_id,
                OrgRole.name.ilike('%tester%'),  # Role name contains "tester"
                OrgRole.is_active == True
            )
        ).first()

        if not tester_role:
            return []

        # Get users with tester role
        query = self.db.query(
            User.id.label('user_id'),
            User.firstname,
            User.lastname,
            User.email,
            UserRole.department_id,
            OrgDepartment.name.label('department_name'),
            OrgDepartment.hierarchy_path
        ).join(
            UserRole, User.id == UserRole.user_id
        ).join(
            OrgDepartment, UserRole.department_id == OrgDepartment.id
        ).filter(
            and_(
                UserRole.role_id == tester_role.id,
                UserRole.is_active == True,
                User.active == True,
                UserRole.organization_id == testing_request.organization_id
            )
        )

        # Filter by department scope
        if testing_request.department_id:
            # Get request's department
            request_dept = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == testing_request.department_id
            ).first()

            if request_dept:
                # Tester can be in the same department or any parent department
                query = query.filter(
                    # Tester's department is in the request department's hierarchy path
                    request_dept.hierarchy_path.like(
                        OrgDepartment.hierarchy_path + '%'
                    )
                )

        testers = query.all()

        # Convert to dict list
        result = []
        for tester in testers:
            result.append({
                'user_id': tester.user_id,
                'name': f"{tester.firstname} {tester.lastname or ''}".strip(),
                'email': tester.email,
                'department_id': tester.department_id,
                'department_name': tester.department_name,
                'hierarchy_path': tester.hierarchy_path
            })

        return result

    # ========================================
    # 3. ASSIGNMENT STRATEGIES
    # ========================================

    def _assign_least_loaded(self, testers: List[Dict]) -> Optional[Dict]:
        """
        Assign to the tester with the least active requests.
        """
        if not testers:
            return None

        # Get current workload for each tester
        tester_loads = []
        for tester in testers:
            active_count = self.db.query(func.count(TestingRequest.id)).filter(
                and_(
                    TestingRequest.assigned_tester_id == tester['user_id'],
                    TestingRequest.status.in_([
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress
                    ])
                )
            ).scalar() or 0

            tester_loads.append({
                **tester,
                'active_count': active_count
            })

        # Sort by active count (ascending)
        tester_loads.sort(key=lambda x: x['active_count'])

        return tester_loads[0]

    def _assign_round_robin(self, testers: List[Dict]) -> Optional[Dict]:
        """
        Assign using round-robin based on last assignment time.
        """
        if not testers:
            return None

        # Get last assignment time for each tester
        tester_times = []
        for tester in testers:
            last_assigned = self.db.query(
                func.max(TestingRequest.cts)
            ).filter(
                TestingRequest.assigned_tester_id == tester['user_id']
            ).scalar()

            tester_times.append({
                **tester,
                'last_assigned': last_assigned or datetime.min
            })

        # Sort by last assigned time (oldest first)
        tester_times.sort(key=lambda x: x['last_assigned'])

        return tester_times[0]

    def _assign_by_priority(self, testers: List[Dict]) -> Optional[Dict]:
        """
        Assign based on priority considering:
        - Current workload (weight: 60%)
        - Department proximity (weight: 40%)
        """
        if not testers:
            return None

        # Calculate scores for each tester
        scored_testers = []
        for tester in testers:
            # Get workload score (lower is better)
            active_count = self.db.query(func.count(TestingRequest.id)).filter(
                and_(
                    TestingRequest.assigned_tester_id == tester['user_id'],
                    TestingRequest.status.in_([
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress
                    ])
                )
            ).scalar() or 0

            # Workload score: 0-100 (inverted so lower count = higher score)
            workload_score = max(0, 100 - (active_count * 10))

            # Department proximity score: exact match = 100, parent = 50
            # For now, all eligible testers get 100 since they passed the filter
            proximity_score = 100

            # Calculate weighted total score
            total_score = (workload_score * 0.6) + (proximity_score * 0.4)

            scored_testers.append({
                **tester,
                'score': total_score,
                'workload_score': workload_score,
                'proximity_score': proximity_score,
                'active_count': active_count
            })

        # Sort by score (descending)
        scored_testers.sort(key=lambda x: x['score'], reverse=True)

        return scored_testers[0]

    # ========================================
    # 4. ASSIGNMENT STATISTICS
    # ========================================

    def get_tester_workload_stats(
        self,
        organization_id: UUID,
        department_id: Optional[UUID] = None
    ) -> List[Dict]:
        """
        Get workload statistics for all testers.

        Returns:
            List of testers with their current workload
        """
        # Get tester role
        tester_role = self.db.query(OrgRole).filter(
            and_(
                OrgRole.organization_id == organization_id,
                OrgRole.name.ilike('%tester%'),
                OrgRole.is_active == True
            )
        ).first()

        if not tester_role:
            return []

        # Query testers with workload counts
        query = self.db.query(
            User.id.label('user_id'),
            User.firstname,
            User.lastname,
            User.email,
            OrgDepartment.name.label('department_name'),
            func.count(
                case(
                    (TestingRequest.status == TestingRequestStatus.assigned, 1),
                    else_=None
                )
            ).label('assigned_count'),
            func.count(
                case(
                    (TestingRequest.status == TestingRequestStatus.accepted, 1),
                    else_=None
                )
            ).label('accepted_count'),
            func.count(
                case(
                    (TestingRequest.status == TestingRequestStatus.in_progress, 1),
                    else_=None
                )
            ).label('in_progress_count'),
            func.count(TestingRequest.id).label('total_active')
        ).join(
            UserRole, User.id == UserRole.user_id
        ).join(
            OrgDepartment, UserRole.department_id == OrgDepartment.id
        ).outerjoin(
            TestingRequest,
            and_(
                TestingRequest.assigned_tester_id == User.id,
                TestingRequest.status.in_([
                    TestingRequestStatus.assigned,
                    TestingRequestStatus.accepted,
                    TestingRequestStatus.in_progress
                ])
            )
        ).filter(
            and_(
                UserRole.role_id == tester_role.id,
                UserRole.is_active == True,
                User.active == True
            )
        )

        if department_id:
            query = query.filter(UserRole.department_id == department_id)

        query = query.group_by(
            User.id,
            User.firstname,
            User.lastname,
            User.email,
            OrgDepartment.name
        )

        results = query.all()

        return [
            {
                'user_id': str(r.user_id),
                'name': f"{r.firstname} {r.lastname or ''}".strip(),
                'email': r.email,
                'department_name': r.department_name,
                'assigned_count': r.assigned_count or 0,
                'accepted_count': r.accepted_count or 0,
                'in_progress_count': r.in_progress_count or 0,
                'total_active': r.total_active or 0
            }
            for r in results
        ]

    # ========================================
    # 5. TESTER AVAILABILITY CHECK
    # ========================================

    def is_tester_available(
        self,
        tester_id: UUID,
        max_concurrent: int = 5
    ) -> Tuple[bool, str]:
        """
        Check if a tester is available for new assignments.

        Args:
            tester_id: Tester user ID
            max_concurrent: Maximum concurrent active requests (default: 5)

        Returns:
            (is_available, reason)
        """
        # Check if user is active
        user = self.db.query(User).filter(User.id == tester_id).first()
        if not user or not user.active:
            return False, "Tester account is not active"

        # Check current workload
        active_count = self.db.query(func.count(TestingRequest.id)).filter(
            and_(
                TestingRequest.assigned_tester_id == tester_id,
                TestingRequest.status.in_([
                    TestingRequestStatus.assigned,
                    TestingRequestStatus.accepted,
                    TestingRequestStatus.in_progress
                ])
            )
        ).scalar() or 0

        if active_count >= max_concurrent:
            return False, f"Tester has reached maximum concurrent requests ({max_concurrent})"

        return True, "Tester is available"

    # ========================================
    # 6. REASSIGNMENT
    # ========================================

    def reassign_tester(
        self,
        testing_request: TestingRequest,
        strategy: str = 'least_loaded'
    ) -> Tuple[bool, Optional[UUID], str]:
        """
        Reassign a testing request to a different tester.
        """
        # Store old tester
        old_tester_id = testing_request.assigned_tester_id

        # Find new tester (excluding current one)
        eligible_testers = self._find_eligible_testers(testing_request)

        # Remove current tester from list
        if old_tester_id:
            eligible_testers = [
                t for t in eligible_testers
                if t['user_id'] != old_tester_id
            ]

        if not eligible_testers:
            return False, None, "No alternative testers available"

        # Apply strategy
        success, new_tester_id, message = self.auto_assign_tester(
            testing_request,
            strategy
        )

        if success:
            return True, new_tester_id, f"Reassigned from previous tester. {message}"
        else:
            return False, None, message
