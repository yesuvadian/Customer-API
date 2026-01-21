from datetime import datetime
from sqlalchemy.orm import Session

from models import Role, User, UserRole
from security_utils import get_password_hash
from services.contact_service import ContactService
from utils.email_service import EmailService
from utils.email_template_loader import render_welcome_email


# -------------------------------------------------
# Default password (ONLY for new Zoho users)
# -------------------------------------------------
COMMON_PASSWORD = "utility@123"
DEFAULT_PASSWORD_HASH = get_password_hash(COMMON_PASSWORD)


class ZohoUserSyncService:
    """
    Sync Zoho Contacts (customer) → public.users
    """

    def __init__(self, db: Session, access_token: str):
        self.db = db
        self.access_token = access_token
        self.contact_service = ContactService()
        self._viewer_role_id = None
        self.email_service = EmailService()  # ✅ instantiate ONCE

    # -------------------------------------------------
    # Mapper
    # -------------------------------------------------
    @staticmethod
    def _map_zoho_contact(contact: dict, is_new: bool) -> dict:
        data = {
            "zoho_erp_id": contact["contact_id"],
            "email": contact.get("email"),
            "firstname": contact.get("first_name"),
            "lastname": contact.get("last_name"),
            "phone_number": contact.get("mobile") or contact.get("phone"),
            "usertype": "customer",
            "isactive": True,
            "erp_last_sync_at": datetime.utcnow(),
            "erp_error_message": None,
        }

        # ✅ Only set status for NEW users
        if is_new:
            data["erp_sync_status"] = "completed"

        if is_new:
            data.update({
                "password_hash": DEFAULT_PASSWORD_HASH,
                "is_quick_registered": True,
                "email_confirmed": False,
                "phone_confirmed": False,
            })

        return data

    # -------------------------------------------------
    # Role lookup
    # -------------------------------------------------
    def _get_viewer_role_id(self) -> int:
        if self._viewer_role_id:
            return self._viewer_role_id

        role = (
            self.db.query(Role)
            .filter(Role.name == "Viewer")
            .one_or_none()
        )

        if not role:
            raise Exception("Viewer role not found in roles table")

        self._viewer_role_id = role.id
        return role.id

    # -------------------------------------------------
    # Upsert logic
    # -------------------------------------------------
    def _upsert_user(self, contact: dict):
        """
        Returns:
            (user, action)
            action ∈ {"created", "updated", "no_change"} or (None, None)
        """

        zoho_id = contact["contact_id"]
        emails = self._extract_emails(contact)

        # 1️⃣ Match by Zoho ERP ID
        user = (
            self.db.query(User)
            .filter(
                User.zoho_erp_id == zoho_id,
                User.usertype == "customer"
            )
            .one_or_none()
        )

        if user:
            changed = False
            user_data = self._map_zoho_contact(contact, is_new=False)

            # ❌ NEVER overwrite email
            user_data.pop("email", None)

            for field, value in user_data.items():
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    changed = True

            # ✅ Preserve legacy success
            if user.erp_sync_status not in ("success", "completed"):
                user.erp_sync_status = "completed"
                changed = True

            if changed:
                user.erp_last_sync_at = datetime.utcnow()
                user.erp_error_message = None
                return user, "updated"

            return user, "no_change"

        # 2️⃣ Attach by email
        if emails:
            user = (
                self.db.query(User)
                .filter(
                    User.email.in_(emails),
                    User.usertype == "customer",
                    User.zoho_erp_id.is_(None),
                    User.erp_external_id.is_(None)
                )
                .one_or_none()
            )

            if user:
                user.zoho_erp_id = zoho_id

                if user.erp_sync_status not in ("success", "completed"):
                    user.erp_sync_status = "completed"

                user.erp_last_sync_at = datetime.utcnow()
                user.erp_error_message = None
                return user, "updated"

        # 3️⃣ FINAL GUARD: never create if email exists
        if emails:
            email_exists = (
                self.db.query(User)
                .filter(User.email.in_(emails))
                .one_or_none()
            )
            if email_exists:
                return None, None

        # 4️⃣ Safe create
        user_data = self._map_zoho_contact(contact, is_new=True)
        user = User(**user_data)
        self.db.add(user)
        self.db.flush()

        # ✅ Assign VIEWER role
        viewer_role_id = self._get_viewer_role_id()
        self.db.add(
            UserRole(
                user_id=user.id,
                role_id=viewer_role_id,
                created_by=None,
                modified_by=None
            )
        )

        return user, "created"

    # -------------------------------------------------
    # Email extraction
    # -------------------------------------------------
    @staticmethod
    def _extract_emails(contact: dict) -> list[str]:
        emails = []
        if contact.get("email"):
            emails.append(contact["email"].lower())
        if contact.get("secondary_email"):
            emails.append(contact["secondary_email"].lower())
        return emails

    # -------------------------------------------------
    # Public sync method
    # -------------------------------------------------
    def sync_customers(self) -> dict:
        contacts = self.contact_service.get_all_customers(self.access_token)

        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        processed_emails: set[str] = set()

        for contact in contacts:
            try:
                emails = self._extract_emails(contact)

                if not emails or any(e in processed_emails for e in emails):
                    skipped += 1
                    continue

                user, action = self._upsert_user(contact)

                if action is None:
                    skipped += 1
                    continue

                if action == "created":
                    inserted += 1

                    body_html = render_welcome_email(
                        name=f"{user.firstname or ''} {user.lastname or ''}".strip(),
                        email=user.email
                    )

                    # ✅ Correct method call (instance)
                    self.email_service.send_email_starttls(
                        to_email=user.email,
                        subject="Welcome to PowerXchange.ai",
                        body_html=body_html
                    )

                elif action == "updated":
                    updated += 1

                for email in emails:
                    processed_emails.add(email)

            except Exception as ex:
                failed += 1
                self._mark_failed(contact.get("contact_id"), str(ex))

        self.db.commit()

        return {
            "inserted": inserted,
            "updated": updated,
            "synced": inserted,
            "skipped": skipped,
            "failed": failed,
        }

    # -------------------------------------------------
    # Failure handler
    # -------------------------------------------------
    def _mark_failed(self, zoho_erp_id: str, error: str):
        self.db.query(User).filter(
            User.zoho_erp_id == zoho_erp_id
        ).update({
            "erp_sync_status": "failed",
            "erp_error_message": error,
            "erp_last_sync_at": datetime.utcnow(),
        })
