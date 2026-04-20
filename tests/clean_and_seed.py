"""
clean_and_seed.py
=================
Drops every table in the public schema, then re-runs seed.py.
Prints row counts for key tables after seeding.

Usage:
    python tests/clean_and_seed.py
    python tests/clean_and_seed.py --skip-drop      # only re-seed, no drop
    python tests/clean_and_seed.py --skip-seed      # only drop, no re-seed
"""
import os
import sys
import argparse
import subprocess
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ── DB credentials ─────────────────────────────────────────────────────────────
DB_CFG = dict(
    dbname   = os.getenv("DB_NAME",     "Relu_Vendor2"),
    user     = os.getenv("DB_USER",     "relu_user"),
    password = os.getenv("DB_PASSWORD", "StrongPassword123!"),
    host     = os.getenv("DB_HOST",     "localhost"),
    port     = int(os.getenv("DB_PORT", "5432")),
)

# Tables whose row counts we verify after seeding
VERIFY_TABLES = [
    "users", "roles", "modules", "role_module_privileges",
    "organizations", "org_roles", "org_user_roles", "org_role_permissions",
    "equipment", "testing_requests",
    "report_definitions", "report_logs",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def connect() -> psycopg2.extensions.connection:
    return psycopg2.connect(**DB_CFG)


def drop_all_tables(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT tablename FROM pg_tables WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        tables = [r[0] for r in cur.fetchall()]

        if not tables:
            print("  [INFO] No tables found — nothing to drop.")
            return 0

        for t in tables:
            cur.execute(f'DROP TABLE IF EXISTS public."{t}" CASCADE;')
            print(f"  [DROP] {t}")

        conn.commit()
        return len(tables)


def verify_seed(conn) -> None:
    print()
    print("  Row counts after seeding:")
    with conn.cursor() as cur:
        for tbl in VERIFY_TABLES:
            try:
                cur.execute(f"SELECT COUNT(*) FROM public.{tbl}")
                n = cur.fetchone()[0]
                icon = "[OK]" if n > 0 else "[--]"
                print(f"    {icon}  {tbl:<35} {n:>6} rows")
            except Exception:
                print(f"    [??]  {tbl:<35}  (table not found)")


# ── Steps ──────────────────────────────────────────────────────────────────────

def step_drop():
    print()
    print("=" * 70)
    print("  STEP 1: DROP ALL TABLES")
    print("=" * 70)
    try:
        conn = connect()
        n = drop_all_tables(conn)
        conn.close()
        print()
        print(f"  [OK] Dropped {n} table(s).")
        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def step_seed():
    print()
    print("=" * 70)
    print("  STEP 2: RUN seed.py")
    print("=" * 70)
    print()
    # Run from the project root so seed.py can import its modules
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    result = subprocess.run(
        [sys.executable, "seed.py"],
        cwd=project_root,
        timeout=600,
    )
    return result.returncode == 0


def step_verify():
    print()
    print("=" * 70)
    print("  STEP 3: VERIFY SEED DATA")
    print("=" * 70)
    try:
        conn = connect()
        verify_seed(conn)
        conn.close()
    except Exception as e:
        print(f"  [ERROR] Could not verify: {e}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Drop all tables and re-seed the database")
    parser.add_argument("--skip-drop", action="store_true", help="Skip the DROP step")
    parser.add_argument("--skip-seed", action="store_true", help="Skip the seed step")
    args = parser.parse_args()

    print()
    print("*" * 70)
    print("  CLEAN & SEED  —  TLSS EE Database")
    print("*" * 70)
    print(f"  Host     : {DB_CFG['host']}:{DB_CFG['port']}")
    print(f"  Database : {DB_CFG['dbname']}")
    print(f"  User     : {DB_CFG['user']}")

    # Step 1 — Drop
    if not args.skip_drop:
        if not step_drop():
            sys.exit(1)
    else:
        print("\n  [SKIP] Drop step skipped (--skip-drop)")

    # Step 2 — Seed
    if not args.skip_seed:
        if not step_seed():
            print("\n  [FAILED] seed.py exited with a non-zero code.")
            sys.exit(1)
    else:
        print("\n  [SKIP] Seed step skipped (--skip-seed)")

    # Step 3 — Verify
    step_verify()

    print()
    print("*" * 70)
    print("  DATABASE IS READY FOR TESTING")
    print("*" * 70)
    print()
    print("  Seeded accounts:")
    accounts = [
        ("superadmin@system.com",     "Admin123!",       "Super Admin"),
        ("orgadmin@sampleorg.com",    "OrgAdmin123!",    "Org Admin (Sample Org)"),
        ("originator@sampleorg.com",  "Originator123!",  "Originator"),
        ("testassigner@sampleorg.com","Assigner123!",    "Test Assigner"),
        ("depthead@sampleorg.com",    "DeptHead123!",    "Department Head"),
        ("fieldtester1@sampleorg.com","Tester123!",      "Field Tester 1"),
        ("labtester1@sampleorg.com",  "Tester123!",      "Lab Tester 1"),
        ("purchaser@sampleorg.com",   "Purchaser123!",   "Purchaser"),
    ]
    for email, pwd, role in accounts:
        print(f"    {role:<28}  {email:<36}  {pwd}")
    print()
    print("  Run the test suite:")
    print("    python tests/test_comprehensive_suite.py")
    print()


if __name__ == "__main__":
    main()
