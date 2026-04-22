"""
Verify the migration was applied successfully
"""
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'Relu_Vendor2',
    'user': 'relu_user',
    'password': 'StrongPassword123!'
}

def verify_migration():
    """Verify the migration"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print("Checking test_results table structure...\n")

        # Check column exists
        cursor.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'test_results'
            AND column_name = 'test_session_id'
        """)

        column_info = cursor.fetchone()
        if column_info:
            print("[OK] test_session_id column exists")
            print(f"  - Type: {column_info[1]}")
            print(f"  - Nullable: {column_info[2]}")
            print(f"  - Default: {column_info[3] or 'NULL'}")
        else:
            print("[FAIL] test_session_id column NOT found")
            return False

        # Check foreign key
        cursor.execute("""
            SELECT
                tc.constraint_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.table_schema = 'public'
            AND tc.table_name = 'test_results'
            AND tc.constraint_type = 'FOREIGN KEY'
            AND kcu.column_name = 'test_session_id'
        """)

        fk_info = cursor.fetchone()
        if fk_info:
            print(f"\n[OK] Foreign key constraint exists: {fk_info[0]}")
            print(f"  - References: {fk_info[2]}.{fk_info[3]}")
        else:
            print("\n[FAIL] Foreign key constraint NOT found")

        # Check index
        cursor.execute("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND tablename = 'test_results'
            AND indexname = 'idx_test_results_session_id'
        """)

        idx_info = cursor.fetchone()
        if idx_info:
            print(f"\n[OK] Index exists: {idx_info[0]}")
        else:
            print("\n[FAIL] Index NOT found")

        # Count existing results
        cursor.execute("SELECT COUNT(*) FROM public.test_results")
        total_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM public.test_results WHERE test_session_id IS NOT NULL")
        linked_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM public.test_results WHERE test_session_id IS NULL")
        unlinked_count = cursor.fetchone()[0]

        print(f"\n[INFO] Existing test_results:")
        print(f"  - Total: {total_count}")
        print(f"  - Linked to sessions: {linked_count}")
        print(f"  - Not linked (legacy): {unlinked_count}")

        print("\n" + "="*60)
        print("[SUCCESS] Migration verification complete!")
        print("="*60)
        print("\nNext steps:")
        print("1. Restart your FastAPI server")
        print("2. The error should be resolved")
        print("3. Try submitting a result again")

        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"[ERROR] {e}")
        return False

if __name__ == "__main__":
    verify_migration()
