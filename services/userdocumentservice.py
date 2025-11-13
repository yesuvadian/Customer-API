from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, NoResultFound
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from models import UserDocument


class UserDocumentService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE -----------------
    def create_document(
        self,
        user_id: UUID,
        division_name: str,
        document_name: str,
        document_type: Optional[str] = None,
        document_url: Optional[str] = None,
        file_data: Optional[bytes] = None,
        file_size: Optional[int] = None,
        content_type: Optional[str] = None,
        om_number: Optional[str] = None,
        expiry_date: Optional[datetime] = None,
        uploaded_by: Optional[UUID] = None
    ) -> UserDocument:
        document = UserDocument(
            user_id=user_id,
            division_name=division_name,
            document_name=document_name,
            document_type=document_type,
            document_url=document_url,
            file_data=file_data,
            file_size=file_size,
            content_type=content_type,
            om_number=om_number,
            expiry_date=expiry_date,
            uploaded_by=uploaded_by
        )
        self.db.add(document)
        try:
            self.db.commit()
            self.db.refresh(document)
            return document
        except IntegrityError as e:
            self.db.rollback()
            raise ValueError(f"Failed to create document: {str(e)}")

    # ----------------- READ -----------------
    def get_document(self, document_id: UUID) -> UserDocument:
        doc = self.db.get(UserDocument, document_id)
        if not doc:
            raise ValueError(f"Document with id '{document_id}' not found.")
        return doc

    def list_documents_by_user(self, user_id: UUID) -> List[UserDocument]:
        return (
            self.db.query(UserDocument)
            .filter(UserDocument.user_id == user_id)
            .order_by(UserDocument.cts.desc())
            .all()
        )

    def list_expired_documents(self, as_of: Optional[datetime] = None) -> List[UserDocument]:
        if not as_of:
            as_of = datetime.utcnow()
        return (
            self.db.query(UserDocument)
            .filter(UserDocument.expiry_date != None)
            .filter(UserDocument.expiry_date < as_of)
            .all()
        )

    # ----------------- UPDATE -----------------
    def update_document(
        self,
        document_id: UUID,
        om_number: Optional[str] = None,
        expiry_date: Optional[datetime] = None,
        is_active: Optional[bool] = None,
        document_url: Optional[str] = None,
        modified_by: Optional[UUID] = None
    ) -> UserDocument:
        doc = self.get_document(document_id)

        if om_number is not None:
            doc.om_number = om_number
        if expiry_date is not None:
            doc.expiry_date = expiry_date
        if is_active is not None:
            doc.is_active = is_active
        if document_url is not None:
            doc.document_url = document_url
        if modified_by is not None:
            doc.uploaded_by = modified_by

        self.db.commit()
        self.db.refresh(doc)
        return doc

    # ----------------- DELETE -----------------
    def delete_document(self, document_id: UUID) -> bool:
        doc = self.get_document(document_id)
        self.db.delete(doc)
        self.db.commit()
        return True
