"""Add priority and target_date columns to document_requests."""
from database import SessionLocal

SQL = """
ALTER TABLE document_requests
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS target_date TIMESTAMPTZ;
"""

db = SessionLocal()
try:
    db.execute(__import__('sqlalchemy').text(SQL))
    db.commit()
    print("Migration complete: priority + target_date added to document_requests")
finally:
    db.close()
