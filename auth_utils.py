from typing import Dict, Optional
from urllib.request import Request
import uuid
import os
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from database import get_db
from models import BillingOrder, Module, OrgDepartment, PasswordHistory, PasswordResetToken, Plan, Role, RoleModulePrivilege, User, UserRole, UserSecurity, UserSession
from security_utils import get_password_hash, verify_password
from services import user_service
from utils.common_service import UTCDateTimeMixin
from utils.email_service import EmailService
# Single source for these — previously redeclared here independently of
# config.py with disagreeing fallback defaults (60 vs 30 min token expiry,
# different placeholder SECRET_KEY strings). services/auth_service.py
# already imports SECRET_KEY/ALGORITHM/REFRESH_TOKEN_EXPIRE_DAYS straight
# from config.py to sign/verify JWTs — two independently-configured
# secrets for the same token scheme was the real risk, not just the
# duplication. Both currently resolve to the same real value in every
# environment with these env vars set (confirmed against .env), so this
# only closes a latent risk for an environment that doesn't set them.
from config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS,
    MAX_LOGIN_ATTEMPTS, LOGIN_LOCK_DURATION_MIN, PASSWORD_HISTORY_LIMIT,
)


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", 300))
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


# ==============================
# Token Utilities
# ==============================

def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expire = UTCDateTimeMixin._utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_reset_token(token: str) -> Optional[str]:
    """Verify a password reset token and return the user_id if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "password_reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type"
            )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token payload"
            )
        return user_id

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )


def generate_reset_token(user_id: str) -> str:
    """Create a short-lived JWT token for password reset."""
    expire = UTCDateTimeMixin._utc_now() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "password_reset",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    expire = UTCDateTimeMixin._utc_now() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = data.copy()
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str):
    """Decode JWT access token."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def get_registration_user(token: str = Depends(oauth2_scheme)) -> str:
    """Validate registration token issued in Step 1."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Registration token missing",
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_or_session_id = payload.get("sub")
        token_type = payload.get("type")
        exp = payload.get("exp")

        if not user_or_session_id or token_type != "register":
            raise HTTPException(status_code=401, detail="Invalid registration token")

        if exp and UTCDateTimeMixin._utc_now().timestamp() > exp:
            raise HTTPException(status_code=401, detail="Registration token expired")

        return user_or_session_id

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired registration token",
        )


# ==============================
# Privilege Builder
# ==============================

def build_user_privileges(db: Session, user_id) -> dict:
    """
    Build the merged privilege dict for a user from all their roles.
    Returns: { "ModuleName": { "can_view": bool, ... , "is_active": bool }, ... }
    """
    modules_map = {
        m.id: {
            "name": m.name,
            "is_active": m.is_active
        }
        for m in db.query(Module).all()
    }

    filtered_privileges = {}

    # Old role system privileges
    try:
        raw_privs = db.query(RoleModulePrivilege).filter(
            RoleModulePrivilege.role_id.in_(
                [r.role_id for r in db.query(UserRole).filter_by(user_id=user_id)]
            )
        ).all()

        for priv in raw_privs:
            module_info = modules_map.get(priv.module_id)
            if not module_info:
                continue

            mod_name = module_info["name"]

            if mod_name not in filtered_privileges:
                filtered_privileges[mod_name] = {
                    "can_view": False,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_search": False,
                    "can_import": False,
                    "can_export": False,
                    "can_approve": False,
                    "can_assign": False,
                    "is_active": bool(module_info["is_active"]) if module_info["is_active"] is not None else True,
                }

            for key in ["can_view", "can_add", "can_edit", "can_delete",
                        "can_search", "can_import", "can_export"]:
                filtered_privileges[mod_name][key] |= bool(getattr(priv, key, None) or False)

    except Exception as e:
        print(f"[INFO] Old role system not available in build_user_privileges: {e}")
        db.rollback()

    # New organization role system privileges
    from models import OrgUserRole, OrgRolePermission
    org_user_roles = db.query(OrgUserRole).filter_by(user_id=user_id, is_active=True).all()
    if org_user_roles:
        org_role_ids = [ur.org_role_id for ur in org_user_roles]
        org_privs = db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id.in_(org_role_ids)
        ).all()

        for priv in org_privs:
            module_info = modules_map.get(priv.module_id)
            if not module_info:
                continue

            mod_name = module_info["name"]

            if mod_name not in filtered_privileges:
                filtered_privileges[mod_name] = {
                    "can_view": False,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_search": False,
                    "can_import": False,
                    "can_export": False,
                    "can_approve": False,
                    "can_assign": False,
                    "is_active": bool(module_info["is_active"]) if module_info["is_active"] is not None else True,
                }

            for key in ["can_view", "can_add", "can_edit", "can_delete",
                        "can_import", "can_export", "can_approve", "can_assign"]:
                filtered_privileges[mod_name][key] |= bool(getattr(priv, key, None) or False)

    return filtered_privileges


# ==============================
# Login User (primary login function)
# ==============================

def has_org_admin_role(user, db) -> bool:
    """Return True if the user holds any active org-admin role in their organisation.
    Role-based check — never tests usertype, per plan Decision 7.

    Single source for this check — previously reimplemented independently
    in middleware/org_auth.py (4x), routers/equipment.py, and two services,
    which had already drifted: one variant skipped the OrgUserRole.is_active
    filter, another (services/repair_timeliness_service.py's _is_org_admin,
    gating a 403 check on record_delay_attribution) skipped both active
    filters entirely — a deactivated org-admin role assignment would still
    pass. Accepts either a full user object (existing call sites) or a bare
    user_id (the call sites above only ever had an id on hand), so neither
    shape of caller needs to change how it calls this.
    """
    from models import OrgUserRole, OrgRole
    user_id = user.id if hasattr(user, "id") else user
    return db.query(OrgUserRole).join(OrgRole).filter(
        OrgUserRole.user_id == user_id,
        OrgUserRole.is_active == True,
        OrgRole.is_org_admin == True,
        OrgRole.is_active == True,
    ).first() is not None


def check_active_billing(user, org, db):
    """Mid-session billing guard for dept-level orgs.
    Call on every authenticated request that touches org data.
    No-ops for org-level orgs, super_admin, and org admins (Decision 7)."""
    from datetime import datetime, timezone
    from models import OrgDepartment

    if not org or not org.billing_scope or org.billing_scope.code != "department_level":
        return

    if user.usertype == "super_admin" or user.department_id is None or has_org_admin_role(user, db):
        return

    now = datetime.now(timezone.utc)

    # Active trial covers all access — no dept subscription required yet
    if org.is_trial and org.trial_end_date and org.trial_end_date > now:
        return

    # Resolve billing unit: use denormalized field when recompute is not pending
    if getattr(org, "billing_unit_recompute_pending", False):
        from routers.billing import walk_up_tree
        billing_unit = walk_up_tree(user.department_id, db, is_billing_unit=True)
    else:
        billing_unit = (
            db.query(OrgDepartment).filter_by(id=user.billing_unit_id).first()
            if user.billing_unit_id else None
        )

    if billing_unit:
        if not billing_unit.subscription_end_date or billing_unit.subscription_end_date < now:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=403,
                detail="SESSION_BILLING_EXPIRED",
                headers={
                    "X-Dept-Name": billing_unit.name or "",
                    "X-Dept-Id":   str(billing_unit.id),
                },
            )
        return

    # User is above billing level — check if any billing unit is still active
    any_active = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org.id,
        OrgDepartment.is_billing_unit == True,
        OrgDepartment.subscription_end_date > now,
    ).first()
    if not any_active:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="SESSION_AWAITING_DEPT_PAYMENT",
            headers={"X-Org-Name": org.name or ""},
        )


def _billing_token_ttl(db):
    from models import SystemConfig
    row = db.query(SystemConfig).filter_by(key="billing_payment_token_ttl_hours").first()
    hours = int(row.value) if row else 1
    return timedelta(hours=hours)


def _get_billing_alert_days(db) -> int:
    from models import SystemConfig
    import json as _json
    row = db.query(SystemConfig).filter_by(key="billing_subscription_reminder_days").first()
    if row:
        days = _json.loads(row.value)
        return min(days) if days else 7
    return 7


def _build_dept_billing_fields(org, billing_unit, now, db=None):
    """Billing fields appended to every login/me response."""
    alert_days = _get_billing_alert_days(db) if db else 7
    dept_days_remaining = None
    dept_alert_active = False
    if billing_unit and billing_unit.subscription_end_date:
        delta = billing_unit.subscription_end_date - now
        dept_days_remaining = max(0, delta.days)
        dept_alert_active = delta.days <= alert_days
    return {
        "dept_billing_unit_id":       str(billing_unit.id)                if billing_unit else None,
        "dept_billing_unit_name":     billing_unit.name                   if billing_unit else None,
        "dept_subscription_end_date": billing_unit.subscription_end_date.isoformat()
                                      if billing_unit and billing_unit.subscription_end_date else None,
        "dept_days_remaining":        dept_days_remaining,
        "dept_alert_active":          dept_alert_active,
    }


def _build_org_admin_billing_summary(org, db, now):
    """dept_billing_summary for org admin in dept-level mode."""
    from models import OrgDepartment
    SUMMARY_PREVIEW_LIMIT = 10
    billing_units = db.query(OrgDepartment).filter_by(
        organization_id=org.id, is_billing_unit=True
    ).all()

    def dept_status(d):
        if not d.subscription_end_date:
            return "pending_payment"
        if d.subscription_end_date < now:
            return "expired"
        return "active"

    summary = [{
        "dept_id":               str(d.id),
        "dept_name":             d.name,
        "subscription_end_date": d.subscription_end_date.isoformat() if d.subscription_end_date else None,
        "status":                dept_status(d),
        "days_remaining":        max(0, (d.subscription_end_date - now).days)
                                 if d.subscription_end_date and d.subscription_end_date >= now else None,
        "alert_active":          bool(d.subscription_end_date and
                                      0 < (d.subscription_end_date - now).days <= _get_billing_alert_days(db)),
    } for d in billing_units]

    all_depts_inactive = all(
        s["status"] in ("expired", "pending_payment") for s in summary
    ) if summary else False

    return {
        "all_depts_inactive":              all_depts_inactive,
        "dept_billing_summary":            summary[:SUMMARY_PREVIEW_LIMIT],
        "dept_billing_summary_total":      len(summary),
        "dept_billing_summary_has_more":   len(summary) > SUMMARY_PREVIEW_LIMIT,
    }


def _check_dept_level_billing(user, org, db, now):
    """
    Raise HTTPException if the user is blocked by dept-level billing rules.
    Called during login and (optionally) /auth/me.
    Returns quietly if the user may proceed.
    """
    from routers.billing import get_dept_depth, walk_up_tree

    # Trial still active → skip all dept billing checks
    if org.is_trial and org.trial_end_date and org.trial_end_date >= now:
        return

    # Trial expired in dept-level mode
    if org.is_trial and org.trial_end_date and org.trial_end_date < now:
        # Root users and org admins get the wizard token
        if user.usertype == "super_admin" or user.department_id is None or has_org_admin_role(user, db):
            payment_token = create_access_token(
                {"org_id": str(org.id), "scope": "billing"},
                expires_delta=_billing_token_ttl(db),
            )
            from models import OrgPlanPricing, BillingScope
            dept_scope = db.query(BillingScope).filter_by(code="department_level").first()
            dept_pricing_ready = False
            if dept_scope:
                dept_pricing_ready = db.query(OrgPlanPricing).filter_by(
                    org_id=org.id, billing_scope_id=dept_scope.id
                ).first() is not None
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TRIAL_EXPIRED_ADMIN",
                headers={
                    "X-Payment-Token":      payment_token,
                    "X-Org-Name":           org.name,
                    "X-Billing-Mode":       org.billing_scope.code if org.billing_scope else "org_level",
                    "X-Dept-Pricing-Ready": str(dept_pricing_ready).lower(),
                },
            )
        # Regular user in dept-level mode — cannot act, message only
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TRIAL_EXPIRED",
            headers={"X-Org-Name": org.name, "X-Trial-Expired-Dept-Mode": "true"},
        )

    # Dept-level converted org: if trial deadline passed and no dept has paid, block root admin too
    if not org.is_trial and org.trial_end_date and org.trial_end_date < now:
        from models import OrgDepartment
        any_active = db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == org.id,
            OrgDepartment.is_billing_unit == True,
            OrgDepartment.subscription_end_date > now,
        ).first()
        if not any_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AWAITING_DEPT_PAYMENT",
                headers={"X-Org-Name": org.name},
            )

    # Root users and org admins always pass dept billing checks
    if user.usertype == "super_admin" or user.department_id is None or has_org_admin_role(user, db):
        return

    # Users above billing level
    user_dept_depth = get_dept_depth(user.department_id, db)
    billing_level = org.billing_hierarchy_level

    if user_dept_depth is None or (billing_level and user_dept_depth < billing_level):
        from models import OrgDepartment
        any_active = db.query(OrgDepartment).filter(
            OrgDepartment.organization_id == org.id,
            OrgDepartment.is_billing_unit == True,
            OrgDepartment.subscription_end_date > now,
        ).first()
        if not any_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="AWAITING_DEPT_PAYMENT",
                headers={"X-Org-Name": org.name},
            )
        return  # at least one dept active → allow

    # Regular user — find billing unit ancestor
    billing_unit = walk_up_tree(user.department_id, db, is_billing_unit=True)

    if billing_unit is None:
        # No billing unit in ancestry → fall back to org-level subscription check
        if org.subscription_end_date and org.subscription_end_date < now:
            # Only root users (no department) can pay an org-level subscription
            is_root_user = user.department_id is None
            headers = {"X-Org-Name": org.name or ""}
            if is_root_user:
                payment_token = create_access_token(
                    {"org_id": str(org.id), "scope": "billing"},
                    expires_delta=_billing_token_ttl(db),
                )
                headers["X-Payment-Token"] = payment_token
                if org.plan_id:
                    headers["X-Plan-Id"] = str(org.plan_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SUBSCRIPTION_EXPIRED",
                headers=headers,
            )
        return  # allow

    # NULL subscription_end_date = pending (never paid); or genuinely expired
    if not billing_unit.subscription_end_date or billing_unit.subscription_end_date < now:
        payment_token = create_access_token(
            {"org_id": str(org.id), "dept_id": str(billing_unit.id), "scope": "billing"},
            expires_delta=_billing_token_ttl(db),
        )
        is_expired = bool(billing_unit.subscription_end_date)
        detail = "SUBSCRIPTION_EXPIRED_DEPT" if is_expired else "SUBSCRIPTION_PENDING_DEPT"
        headers = {
            "X-Payment-Token": payment_token,
            "X-Org-Name":      org.name,
            "X-Dept-Name":     billing_unit.name,
            "X-Dept-Id":       str(billing_unit.id),
        }
        # Use plan from last paid order for this dept, then any dept in org, then org plan
        dept_order = (
            db.query(BillingOrder)
            .filter(BillingOrder.department_id == billing_unit.id, BillingOrder.status == "paid")
            .order_by(BillingOrder.paid_at.desc())
            .first()
        )
        org_order = None
        if not dept_order:
            org_order = (
                db.query(BillingOrder)
                .filter(BillingOrder.org_id == org.id, BillingOrder.status == "paid")
                .order_by(BillingOrder.paid_at.desc())
                .first()
            )
        resolved_order = dept_order or org_order
        plan_id = resolved_order.plan_id if resolved_order else org.plan_id
        print(f"[BILLING-DEPT] detail={detail} dept={billing_unit.name} dept_order={dept_order} org_order={org_order} plan_id={plan_id}")
        if plan_id:
            headers["X-Plan-Id"] = str(plan_id)
        print(f"[BILLING-DEPT] headers={headers}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            headers=headers,
        )
    # Subscription active — allow login


def login_user(db: Session, email: str, password: str):
    try:
        print("[DEBUG] login_user called")
        now = UTCDateTimeMixin._utc_now()

        # Step 1: Fetch user
        user = db.query(User).filter_by(email=email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Step 2: Check if user is active
        if not user.isactive:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive. Please contact administrator."
            )

        # Step 2b: Block login if the organisation is disabled or trial has expired
        if user.organization_id:
            from models import Organization
            org = db.query(Organization).filter_by(id=user.organization_id).first()
            if org and not org.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your organisation has been disabled. Please contact support.",
                )
            print(f"[TRIAL-LOGIN] org={org and org.name} is_trial={org and org.is_trial} trial_end={org and org.trial_end_date} now={now}")

            # Dept-level mode: hand off ALL checks (trial + subscription) to dept path
            is_dept_level = org and org.billing_scope and org.billing_scope.code == "department_level"

            if org and org.is_trial and org.trial_end_date:
                print(f"[TRIAL-LOGIN] expired={org.trial_end_date < now}")
                if org.trial_end_date < now:
                    if is_dept_level:
                        # Dept-level trial expiry handled by _check_dept_level_billing below
                        pass
                    else:
                        first_expiry = org.trial_status != "expired"
                        if first_expiry:
                            org.trial_status = "expired"
                            db.commit()
                        payment_token = create_access_token(
                            {"org_id": str(org.id), "scope": "billing"},
                            expires_delta=timedelta(hours=1),
                        )
                        if first_expiry:
                            try:
                                from services.billing_service import send_payment_link
                                send_payment_link(db, org)
                            except Exception as e:
                                print(f"[BILLING] Failed to send payment link: {e}")
                        is_root_user = user.department_id is None
                        if is_root_user:
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="TRIAL_EXPIRED_ADMIN",
                                headers={
                                    "X-Payment-Token": payment_token,
                                    "X-Org-Name": org.name,
                                    "X-Billing-Mode": org.billing_scope.code if org.billing_scope else "org_level",
                                },
                            )
                        else:
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="TRIAL_EXPIRED_NOTIFY",
                                headers={"X-Org-Name": org.name},
                            )

            if org and not org.is_trial and org.subscription_end_date and not is_dept_level:
                if org.subscription_end_date < now:
                    print(f"[SUBSCRIPTION-LOGIN] Subscription expired for {org.name}")
                    first_sub_expiry = org.subscription_status != "expired"
                    if first_sub_expiry:
                        org.subscription_status = "expired"
                        db.commit()
                        try:
                            from services.billing_service import send_payment_link
                            send_payment_link(db, org)
                        except Exception as e:
                            print(f"[BILLING] Failed to send renewal link: {e}")
                    is_root_user = user.department_id is None
                    if is_root_user:
                        # Root user can renew — give payment token and wizard
                        payment_token = create_access_token(
                            {"org_id": str(org.id), "scope": "billing"},
                            expires_delta=timedelta(hours=1),
                        )
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="SUBSCRIPTION_EXPIRED",
                            headers={
                                "X-Payment-Token": payment_token,
                                "X-Org-Name": org.name,
                                "X-Billing-Mode": org.billing_scope.code if org.billing_scope else "org_level",
                                "X-Plan-Id": str(org.plan_id) if org.plan_id else "",
                            },
                        )
                    else:
                        # Non-root user: cannot renew, show contact-admin message
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="SUBSCRIPTION_EXPIRED_NOTIFY",
                            headers={"X-Org-Name": org.name},
                        )

            # Dept-level billing check runs AFTER password verify (Step 5)

        # Step 3: Security record
        security = db.query(UserSecurity).filter_by(user_id=user.id).first()
        if not security:
            security = UserSecurity(
                user_id=user.id,
                failed_login_attempts=0,
                login_locked_until=None
            )
            db.add(security)
            db.flush()

        # Step 4: Account locked check
        locked_until = UTCDateTimeMixin._make_aware(security.login_locked_until)
        if locked_until and locked_until > now:
            remaining = locked_until - now
            remaining_minutes = max(1, int(remaining.total_seconds() // 60))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account locked. Try again in {remaining_minutes} minute(s)."
            )

        # Step 5: Password verification
        if verify_password(password, user.password_hash):
            # ✅ Correct password — reset attempts and clear expired lock
            security.failed_login_attempts = 0
            if locked_until and locked_until <= now:
                security.login_locked_until = None
            db.commit()
            # Dept-level billing check — only after password is confirmed correct
            if is_dept_level:
                _check_dept_level_billing(user, org, db, now)
        else:
            # ❌ Wrong password — increment attempts
            db.rollback()  # clear any dirty state before writing
            security.failed_login_attempts = (security.failed_login_attempts or 0) + 1

            if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
                security.login_locked_until = now + timedelta(minutes=LOGIN_LOCK_DURATION_MIN)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Too many failed attempts. Account locked for {LOGIN_LOCK_DURATION_MIN} minute(s)."
                )

            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        # Step 6: Load roles — initialize org_user_roles before if/else
        from models import OrgUserRole, OrgRole

        role_names = []
        dashboard_type = "generic"
        org_user_roles = []  # ✅ always initialized

        if getattr(user, "usertype", None) == "super_admin":
            role_names = ["super_admin"]
            dashboard_type = "admin"
        else:
            org_user_roles = db.query(OrgUserRole).filter_by(
                user_id=user.id, is_active=True
            ).all()

            if org_user_roles:
                org_role_ids = [ur.org_role_id for ur in org_user_roles]
                org_roles = db.query(OrgRole).filter(OrgRole.id.in_(org_role_ids)).all()
                role_names = [r.name for r in org_roles]

                priority = {"admin": 4, "supervisor": 3, "field": 2, "generic": 1}
                for role in org_roles:
                    role_dashboard = getattr(role, "default_dashboard_type", "generic")
                    if priority.get(role_dashboard, 0) > priority.get(dashboard_type, 0):
                        dashboard_type = role_dashboard

        # Step 7: Ensure user has at least one role
        if not role_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no roles assigned. Contact administrator."
            )

        # Step 8: Build privileges
        filtered_privileges = build_user_privileges(db, user.id)

        # Step 9: Primary department — prefer role-assignment dept, fall back to user record
        primary_department_id = None
        if org_user_roles:
            primary_department_id = org_user_roles[0].department_id
        if primary_department_id is None and getattr(user, 'department_id', None):
            primary_department_id = user.department_id

        # Step 10: Plan info
        plan = None
        if user.plan_id:
            plan_obj = db.query(Plan).filter_by(id=user.plan_id).first()
            if plan_obj:
                plan = {
                    "id": str(plan_obj.id),
                    "planname": plan_obj.planname,
                    "plan_description": plan_obj.plan_description,
                    "plan_limit": plan_obj.plan_limit,
                }

        from models import Organization, SystemConfig

        organization_name = None
        trial_info = {"billing_mode": "org_level"}

        if user.organization_id:
            org = db.query(Organization).filter(
                Organization.id == user.organization_id
            ).first()

            if org:
                organization_name = org.name
                days_remaining = None
                alert_active = False
                alert_row = db.query(SystemConfig).filter(SystemConfig.key == "trial_alert_days").first()
                alert_days = int(alert_row.value) if alert_row else 7
                if org.is_trial and org.trial_end_date:
                    delta = (org.trial_end_date - now).days
                    days_remaining = max(0, delta)
                    alert_active = days_remaining <= alert_days
                elif not org.is_trial and org.subscription_end_date:
                    delta = (org.subscription_end_date - now).days
                    days_remaining = max(0, delta)
                    alert_active = days_remaining <= alert_days
                effective_onboarding_complete = bool(org.onboarding_complete)
                print(f"[DEBUG] org={org.name} is_trial={org.is_trial} days_remaining={days_remaining} alert_active={alert_active} onboarding={effective_onboarding_complete}")
                trial_info = {
                    "is_trial": org.is_trial,
                    "trial_status": org.trial_status,
                    "days_remaining": days_remaining,
                    "trial_end_date": org.trial_end_date.isoformat() if org.trial_end_date else None,
                    "alert_active": alert_active,
                    "onboarding_complete": effective_onboarding_complete,
                }

                # Dept-level billing fields
                billing_scope_code = org.billing_scope.code if org.billing_scope else "org_level"
                trial_info["billing_mode"] = billing_scope_code
                # Root users (no department_id) are org admins — see all dept billing
                is_root_user = user.department_id is None

                if billing_scope_code == "department_level":
                    if is_root_user:
                        trial_info.update(_build_org_admin_billing_summary(org, db, now))
                    else:
                        billing_unit = db.query(OrgDepartment).filter_by(id=user.billing_unit_id).first() if user.billing_unit_id else None
                        if billing_unit is None:
                            trial_info["billing_mode"] = "org_level"
                        trial_info.update(_build_dept_billing_fields(org, billing_unit, now, db))
                else:
                    trial_info.update(_build_dept_billing_fields(org, None, now, db))

                # billing_action: what the banner button should do
                # root user → "upgrade" (manage billing)
                # dept user + dept-level → "pay_now"
                # dept user + org-level → null (contact admin)
                if is_root_user:
                    billing_action = "upgrade"
                elif billing_scope_code == "department_level":
                    billing_action = "pay_now"
                else:
                    billing_action = None
                trial_info["billing_action"] = billing_action
                print(f"[BILLING] user={user.email} scope={billing_scope_code} is_root={is_root_user} billing_action={billing_action}")

        # Create tokens
        access_token = create_access_token({"sub": str(user.id)})
        refresh_token = create_refresh_token(str(user.id))
        # Create session record
        session_record = UserSession(
            user_id=user.id,
            access_token=access_token,
            refresh_token=refresh_token,
            cts=now,
            expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        db.add(session_record)
        db.commit()

        # Step 11: Build and return result
        result = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "firstname": user.firstname,
                "lastname": user.lastname,
                "phone_number": user.phone_number,
                "is_active": user.isactive,
                "email_confirmed": user.email_confirmed,
                "phone_confirmed": user.phone_confirmed,
                "usertype": user.usertype,
                "organization_id": str(user.organization_id) if user.organization_id else None,
                "organization_name": organization_name,
                "department_id": str(primary_department_id) if primary_department_id else None,
                "cts": UTCDateTimeMixin._make_aware(user.cts),
                "mts": UTCDateTimeMixin._make_aware(user.mts),
                "roles": role_names,
                "dashboard_type": dashboard_type,
                "plan": plan,
                **trial_info,
            },
            "privileges": filtered_privileges
        }

        print(f"[DEBUG] dashboard_type in result: {result['user'].get('dashboard_type')}")
        print(f"[DEBUG] onboarding_complete in result: {result['user'].get('onboarding_complete')}")
        print(f"[BILLING-RESULT] billing_mode={result['user'].get('billing_mode')} dept_unit={result['user'].get('dept_billing_unit_name')} dept_end={result['user'].get('dept_subscription_end_date')}")
        return result

    except HTTPException:
        raise

    except Exception as e:
        print(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during login."
        )


# ==============================
# Authenticate User (session-based)
# ==============================

def authenticate_user(db: Session, username: str, password: str, request=None):
    """
    Authenticate a user and create a UserSession on success.
    Raises HTTPException on all failure cases.
    """
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required"
        )

    # Find user
    user = db.query(User).filter(User.email == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Check user is active
    if not user.isactive:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Please contact administrator."
        )

    # Ensure security record exists
    security = db.query(UserSecurity).filter_by(user_id=user.id).first()
    if not security:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        db.commit()
        db.refresh(security)

    now = UTCDateTimeMixin._utc_now()

    # Check lock
    locked_until = UTCDateTimeMixin._make_aware(security.login_locked_until)
    if locked_until:
        if locked_until <= now:
            # Lock expired — clear it
            security.login_locked_until = None
            db.commit()
        else:
            seconds_left = (locked_until - now).total_seconds()
            remaining_minutes = max(1, int(seconds_left // 60))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Account locked. Try again in {remaining_minutes} minute(s)."
            )

    # Verify password
    if not verify_password(password, user.password_hash):
        db.rollback()  # clear dirty state before writing
        security.failed_login_attempts = (security.failed_login_attempts or 0) + 1

        if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            security.login_locked_until = now + timedelta(minutes=LOGIN_LOCK_DURATION_MIN)
            security.failed_login_attempts = 0
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Too many failed attempts. Account locked for {LOGIN_LOCK_DURATION_MIN} minute(s)."
            )

        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Successful login — reset security counters
    security.failed_login_attempts = 0
    security.login_locked_until = None
    db.commit()

    # Create tokens
    access_token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token(str(user.id))

    # Create session
    session = UserSession(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        cts=now,
        expires_at=now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        ip_address=request.client.host if request else None,
        user_agent=request.headers.get("User-Agent") if request else None
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return {
        "user": user,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "session_id": session.id
    }


# ==============================
# Get Current User
# ==============================

_optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)


def get_current_user(
    request: Request,
    header_token: Optional[str] = Depends(_optional_oauth2_scheme),
    db: Session = Depends(get_db)
):
    # Reuse middleware-validated user if available
    if hasattr(request.state, "user") and request.state.user is not None:
        return request.state.user

    # Fall back to query-param token (for browser-navigated report URLs)
    raw_token = header_token or request.query_params.get("token")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except Exception:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception

    return user


# ==============================
# Password Reset
# ==============================

def requestpasswordreset(db: Session, email: str, request: Request) -> str:
    # Find user
    user = db.query(User).filter_by(email=email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Invalidate previous unused tokens
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == False
    ).update({"used": True})
    db.commit()

    # Generate new token
    reset_token = generate_reset_token(user.id)

    # Store token
    token_entry = PasswordResetToken(
        user_id=user.id,
        token=reset_token,
        cts=UTCDateTimeMixin._utc_now(),
        expires_at=UTCDateTimeMixin._utc_now() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        used=False
    )
    db.add(token_entry)
    db.commit()

    # Send email
    email_service = EmailService()
    email_service.send_password_reset(to_email=user.email, token=reset_token)

    reset_link = f"{email_service.base_url}/reset-password?token={reset_token}&email={user.email}"
    return reset_link


def resetpassword(db: Session, token: str, new_password: str):
    if not token or not new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token and new password are required"
        )

    # Verify JWT and extract user_id
    user_id = verify_reset_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    # Check token record
    from models import PasswordResetToken
    token_entry = db.query(PasswordResetToken).filter_by(token=token).first()
    if not token_entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token not found or already invalidated"
        )

    if token_entry.used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has already been used"
        )

    if UTCDateTimeMixin._make_aware(token_entry.expires_at) < UTCDateTimeMixin._utc_now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset token has expired"
        )

    # Fetch user
    user = db.query(User).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check password not same as current
    if verify_password(new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="New password cannot be the same as the current password."
        )

    # Check password history
    history = (
        db.query(PasswordHistory)
        .filter_by(user_id=user_id)
        .order_by(PasswordHistory.cts.desc())
        .limit(PASSWORD_HISTORY_LIMIT)
        .all()
    )

    for old_pw in history:
        if verify_password(new_password, old_pw.password_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"New password cannot be one of your last {PASSWORD_HISTORY_LIMIT} passwords."
            )

    # Update password
    new_hash = get_password_hash(new_password)
    user.password_hash = new_hash

    # Ensure security record exists
    security = db.query(UserSecurity).filter_by(user_id=user.id).first()
    if not security:
        security = UserSecurity(user_id=user.id)
        db.add(security)
        db.flush()

    security.failed_login_attempts = 0
    security.login_locked_until = None

    # Save to history
    pw_entry = PasswordHistory(
        user_id=user.id,
        password_hash=new_hash,
        cts=UTCDateTimeMixin._utc_now(),
        created_by=user.id,
        modified_by=user.id,
    )
    db.add(pw_entry)

    # Mark token used
    token_entry.used = True

    # Prune old history
    total_history = (
        db.query(PasswordHistory)
        .filter_by(user_id=user.id)
        .order_by(PasswordHistory.cts.desc())
        .all()
    )
    if len(total_history) > PASSWORD_HISTORY_LIMIT:
        for old_entry in total_history[PASSWORD_HISTORY_LIMIT:]:
            db.delete(old_entry)

    db.commit()
    return {"message": "Password reset successful"}