from database import get_db
from sqlalchemy import text

db = next(get_db())
rows = db.execute(text(
    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'scada%' ORDER BY tablename"
)).fetchall()
if rows:
    for r in rows:
        print("[OK]", r[0])
else:
    print("NO SCADA TABLES FOUND — running create_tables now")
db.close()
