"""
Set org_departments.description based on hierarchy level:
  Level 1 → Zone
  Level 2 → Circle
  Level 3 → Division
  Level 4 with children → Subdivision
  Level 4 leaf / Level 5 → Substation
  Level 6+ → Level N

Run once:
    python migrate_dept_descriptions.py
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text
from database import SessionLocal

SQL = """
WITH RECURSIVE dept_hierarchy AS (
    SELECT
        id,
        parent_department_id,
        1 AS level
    FROM public.org_departments
    WHERE parent_department_id IS NULL

    UNION ALL

    SELECT
        d.id,
        d.parent_department_id,
        dh.level + 1
    FROM public.org_departments d
    JOIN dept_hierarchy dh
      ON d.parent_department_id = dh.id
)
UPDATE public.org_departments od
SET description = CASE
    WHEN dh.level = 1 THEN 'Zone'
    WHEN dh.level = 2 THEN 'Circle'
    WHEN dh.level = 3 THEN 'Division'
    WHEN dh.level = 4
         AND EXISTS (
             SELECT 1
             FROM public.org_departments c
             WHERE c.parent_department_id = od.id
         ) THEN 'Subdivision'
    WHEN dh.level = 4 THEN 'Substation'
    WHEN dh.level = 5 THEN 'Substation'
    ELSE CONCAT('Level ', dh.level)
END
FROM dept_hierarchy dh
WHERE od.id = dh.id
"""

session = SessionLocal()
try:
    result = session.execute(text(SQL))
    session.commit()
    print(f"[OK] Updated {result.rowcount} department descriptions.")
except Exception as e:
    session.rollback()
    print(f"[ERROR] {e}")
    sys.exit(1)
finally:
    session.close()
