"""
Add these schemas to schemas.py for the approval workflow
"""

from pydantic import BaseModel
from typing import Optional
from uuid import UUID

# Add to schemas.py:

class TesterInfo(BaseModel):
    """Information about a tester user"""
    user_id: str
    email: str
    name: str
    department_id: Optional[str] = None
    active_requests: int  # Current workload

    class Config:
        from_attributes = True


class ApproverTesterSelection(BaseModel):
    """Request body for approver selecting a tester"""
    tester_role_id: UUID  # Which tester role was selected
    tester_id: UUID       # Which specific user was chosen
    comment: Optional[str] = None  # Optional approval comment

    class Config:
        from_attributes = True


class ApprovalResponse(BaseModel):
    """Response from approval/rejection action"""
    success: bool
    message: str
    testing_request_id: str
    assigned_tester_id: Optional[str] = None
    assigned_tester_email: Optional[str] = None
    new_status: str

    class Config:
        from_attributes = True
