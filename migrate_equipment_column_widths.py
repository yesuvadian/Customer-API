"""
Widen equipment columns that were incorrectly defined as VARCHAR(10).

- bay_number:    VARCHAR(10) -> VARCHAR(255)
- serial_in_bay: VARCHAR(10) -> VARCHAR(255)
- voltage_class: VARCHAR(10) -> VARCHAR(50)
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text
from database import SessionLocal

session = SessionLocal()
try:
    alters = [
        "ALTER TABLE public.equipment ALTER COLUMN bay_number TYPE VARCHAR(255)",
        "ALTER TABLE public.equipment ALTER COLUMN serial_in_bay TYPE VARCHAR(255)",
        "ALTER TABLE public.equipment ALTER COLUMN voltage_class TYPE VARCHAR(50)",
    ]
    for stmt in alters:
        print(f"[RUN] {stmt}")
        session.execute(text(stmt))
        print("[OK]")
    session.commit()
    print("\n[DONE] Equipment column widths updated.")
except Exception as e:
    session.rollback()
    print(f"[ERROR] {e}")
finally:
    session.close()
