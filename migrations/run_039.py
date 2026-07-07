"""
Run migration 039: add source_stage_id to tr_wf_routing_rules.
"""
from database import SessionLocal
from sqlalchemy import text

def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE public.tr_wf_routing_rules
                ADD COLUMN IF NOT EXISTS source_stage_id UUID
                    REFERENCES public.tr_wf_stages(id) ON DELETE CASCADE;
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_tr_wf_routing_rules_source_stage_id
                ON public.tr_wf_routing_rules(source_stage_id);
        """))
        db.commit()
        print("Migration 039 complete: source_stage_id added to tr_wf_routing_rules.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
