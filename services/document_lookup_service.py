from sqlalchemy.orm import Session
from uuid import UUID

from services.userdocumentservice import UserDocumentService
# from services.bankdocumentservice import BankDocumentService
# from services.taxdocumentservice import TaxDocumentService

class DocumentLookupService:

    def __init__(self, db: Session):
        self.db = db

    def find_document(self, document_id: UUID):
        # Try user document
        try:
            return UserDocumentService(self.db).get_document(document_id)
        except:
            pass

        # # Try bank document
        # try:
        #     return BankDocumentService(self.db).get_document(document_id)
        # except:
        #     pass

        # # Try tax document
        # try:
        #     return TaxDocumentService(self.db).get_document(document_id)
        # except:
        #     pass

        # Document not found anywhere
        return None
