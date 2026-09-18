#!/usr/bin/env python3
"""
One-time / repeatable setup: sync the database schema to models.py,
without touching seed data.

Started as the same generic step deploy.sh's --create-tables flag runs
on the actual deploy servers (Base.metadata.create_all() for any missing
table, then a column-by-column diff against every model to ADD COLUMN
whatever's missing) -- pulled out into its own script because deploy.sh
is a bash script with Linux-only paths (sudo, venv/bin/activate,
/apps/customer/api) and can't be run directly on a Windows dev machine,
and because running the full seed.py isn't wanted here.

Fixes over that original deploy.sh logic, found by tracing it against
the real models:

  - Table-name double-qualification bug: Base.metadata.tables is keyed
    by "schema.table" for any table with an explicit schema (109 of 135
    models here), but the original passed that same qualified string as
    BOTH the schema-qualified table name AND alongside a separate
    schema= argument -- producing "public.public.foo" and making
    inspector.get_columns() raise NoSuchTableError for all 109 of them,
    silently swallowed by a bare except/continue. Confirmed live: this
    alone meant ~80% of tables were never actually diffed at all. Fixed
    by using table.name (always unqualified) for both the inspector
    call and the ALTER TABLE statement, with table.schema kept separate.

  - Never emitted NOT NULL, regardless of the model's nullable=False --
    every added column silently ended up nullable in the real database.

  - Only checked col.default (the Python-side default), never
    col.server_default (the DB-level one). Confirmed live: 37 columns
    across these models are NOT NULL with only a server_default (e.g.
    repair_stage_definitions.assign_statuses) -- those would've been
    added nullable with no default at all, so any insert relying on the
    server default would silently get NULL instead.

  - A column needing a named DB-level type (e.g. a Postgres native ENUM)
    would fail outright with "type does not exist" if that type wasn't
    already created by some earlier create_all() -- there was no
    create-the-type-first step for the add-a-column-to-an-existing-table
    path.

  - One transaction for the entire run, committed once at the end: a
    single failing column (e.g. from any of the above) aborted the
    whole transaction, discarding every other successful column
    addition in the same run, before and after it. Fixed by committing
    (or rolling back) after each individual column attempt, so one
    failure only costs that one column.

The two fixes above for NOT NULL / server_default are both handled by
letting SQLAlchemy's own DDL compiler (CreateColumn) build the column
fragment, instead of hand-assembling a DEFAULT clause -- the same
compiler create_all() already relies on, rather than a second,
independently-written implementation of the same thing.

Only ever adds tables/columns -- never drops or alters an existing one,
so re-running this is safe.

Usage:
    python sync_schema.py
"""
from database import engine
from models import Base
from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn


def main():
    Base.metadata.create_all(bind=engine)
    print("Tables created/verified.")

    inspector = inspect(engine)
    added, failed = 0, 0

    with engine.connect() as conn:
        for table in Base.metadata.tables.values():
            schema = table.schema or "public"
            try:
                existing = {
                    c["name"] for c in inspector.get_columns(table.name, schema=schema)
                }
            except Exception:
                # Table doesn't exist yet even after create_all (e.g. a
                # dependency-ordering issue) -- skip rather than abort
                # the whole sync over one table.
                continue

            for col in table.columns:
                if col.name in existing:
                    continue

                try:
                    # Named DB-level types (e.g. a Postgres native ENUM)
                    # need to exist before a column can reference them --
                    # create_all() does this for brand-new tables, but
                    # this add-a-column-to-an-existing-table path doesn't
                    # go through create_all() at all.
                    if hasattr(col.type, "create"):
                        col.type.create(conn, checkfirst=True)

                    fragment = str(CreateColumn(col).compile(dialect=engine.dialect))
                    conn.execute(text(
                        f"ALTER TABLE {schema}.{table.name} ADD COLUMN {fragment}"
                    ))
                    conn.commit()
                    print(f"Added column: {schema}.{table.name}.{col.name}")
                    added += 1
                except Exception as exc:
                    conn.rollback()
                    print(f"FAILED to add {schema}.{table.name}.{col.name}: {exc}")
                    failed += 1

    print(f"Schema sync complete. {added} column(s) added, {failed} failed.")


if __name__ == "__main__":
    main()
