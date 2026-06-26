"""
Delete sample equipment records that were seeded by seed_sample_equipment().
These are identified by their factory_serial_number patterns from the seed script.
"""
from contextlib import contextmanager
from database import VendorSessionLocal
from models import Equipment

SAMPLE_SERIALS = [
    # seed_sample_equipment()
    "PT2024001", "PT2024002", "PT2024003",
    "CT2024001", "CT2024002",
    "CVT2024001",
    "REL2024001",
    "MTR2024001",
    "CB2024001", "CB2024002",
    "PR2024001", "PR2024002",
    "TVM2024001", "TVM2024002",
    # _seed_dft_equipment()
    "NTH2024001", "NTH2024002", "NTH2024003",
    "STH2024001", "STH2024002", "STH2024003",
    "MYS2024001", "MYS2024002", "MYS2024003",
    # seed_kit_equipment_records()
    "SN-MIT-001", "SN-BDV-001", "SN-FLK-001", "SN-OMC-001",
    "SN-MPR-001", "SN-FLK-002", "SN-MIT-002", "SN-BDV-002",
]

@contextmanager
def get_db_session():
    session = VendorSessionLocal()
    try:
        yield session
    finally:
        session.close()

with get_db_session() as session:
    deleted = (
        session.query(Equipment)
        .filter(Equipment.factory_serial_number.in_(SAMPLE_SERIALS))
        .all()
    )
    count = len(deleted)
    for eq in deleted:
        session.delete(eq)
    session.commit()
    print(f"[OK] Deleted {count} sample equipment records.")
