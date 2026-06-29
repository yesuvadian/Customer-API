from database import vendor_engine
from sqlalchemy import text

sql = "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name='tr_wf_instances' ORDER BY column_name"
with vendor_engine.connect() as conn:
    rows = conn.execute(text(sql)).fetchall()
    for r in rows:
        print(r[0], '-', r[1])
