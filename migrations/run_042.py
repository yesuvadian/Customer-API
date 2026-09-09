"""
Run migration 042: add table_field_key to parameter_threshold_bands.

ParameterThresholdBand was keyed by (template_key, parameter_key,
context_key, band_label) only. Several templates reuse the exact same row
id across two or more different table fields in the SAME template with
DIFFERENT cutoffs — confirmed live:
  - capacitance_tandelta_transformer: five bushing voltage-class tables
    (400kV/220kV/66kV/33kV/11kV) all use 'R'/'Y'/'B' Phase row ids, and its
    winding_test_results vs idax_test_results tables both use HV-GND/
    HV-LV/LV-GND/LV-TV/TV-GND/etc row ids.
  - tan_delta_capacitance_idax: bushing_220kv_results vs
    bushing_66kv_results, same 'R'/'Y'/'B' Phase collision.
Without a table-field identifier, extracting one sub-table's band
silently overwrote another's (last one processed wins) — this migration
adds the missing column so each sub-table's bands can coexist.
"""
from database import SessionLocal
from sqlalchemy import text


def run():
    db = SessionLocal()
    try:
        db.execute(text("""
            ALTER TABLE public.parameter_threshold_bands
                ADD COLUMN IF NOT EXISTS table_field_key VARCHAR(100);
        """))
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_parameter_threshold_bands_table_field_key
                ON public.parameter_threshold_bands (table_field_key);
        """))
        db.execute(text("""
            ALTER TABLE public.parameter_threshold_bands
                DROP CONSTRAINT IF EXISTS uq_threshold_band;
        """))
        db.execute(text("""
            ALTER TABLE public.parameter_threshold_bands
                ADD CONSTRAINT uq_threshold_band
                UNIQUE (template_key, table_field_key, parameter_key, context_key, band_label);
        """))
        db.commit()
        print("Migration 042 complete: parameter_threshold_bands now has "
              "table_field_key, and uq_threshold_band includes it.")
    except Exception as e:
        db.rollback()
        print(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
