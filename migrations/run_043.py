"""
Run migration 043: add gps_coordinates to equipment.

Equipment.gps_coordinates (models.py) was added alongside the Data Quality
Index feature (commit 8daa4f0, "Add admin-configurable Data Quality Index
rules with equipment-type scoping") but no migration ever added the column
to the real Postgres table — that commit's own alter_dqi_rule_config.py only
touches dqi_rule_configs, not equipment. Since SQLAlchemy selects every
mapped column on a plain `db.query(Equipment)`, this breaks EVERY query
against Equipment with psycopg2.errors.UndefinedColumn, not just DQI-related
endpoints — confirmed live taking down /analytics/asset-breakdown,
/analytics/dashboard/equipment, /analytics/dashboard, /equipment/ and
/analytics/deterioration-watch-list.
"""
from database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE public.equipment
                ADD COLUMN IF NOT EXISTS gps_coordinates VARCHAR(100);
        """))
        db.commit()
        print("Migration 043 complete: equipment now has gps_coordinates.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
