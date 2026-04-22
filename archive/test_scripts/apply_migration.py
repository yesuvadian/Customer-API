"""
Apply migration: Add test_session_id to test_results table
"""
import psycopg2
import sys

# Database connection parameters
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'Relu_Vendor2',
    'user': 'relu_user',
    'password': 'StrongPassword123!'
}

def apply_migration():
    """Apply the test_session_id migration"""

    migration_sql = """
    -- Check if column already exists
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'test_results'
            AND column_name = 'test_session_id'
        ) THEN
            -- Add test_session_id column (nullable to support existing results)
            ALTER TABLE public.test_results
            ADD COLUMN test_session_id UUID;

            -- Add foreign key constraint
            ALTER TABLE public.test_results
            ADD CONSTRAINT fk_test_results_session
            FOREIGN KEY (test_session_id)
            REFERENCES public.test_sessions(id)
            ON DELETE SET NULL;

            -- Add index for performance
            CREATE INDEX idx_test_results_session_id ON public.test_results(test_session_id);

            -- Add comment for documentation
            COMMENT ON COLUMN public.test_results.test_session_id IS 'Links result to specific test session. NULL for legacy single-session results.';

            RAISE NOTICE 'Migration applied successfully: test_session_id column added';
        ELSE
            RAISE NOTICE 'Migration already applied: test_session_id column exists';
        END IF;
    END $$;
    """

    try:
        # Connect to database
        print("Connecting to database...")
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = True
        cursor = conn.cursor()

        print("Applying migration...")
        cursor.execute(migration_sql)

        # Verify column was added
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
            AND table_name = 'test_results'
            AND column_name = 'test_session_id'
        """)
        result = cursor.fetchone()

        if result:
            print(f"\n[SUCCESS!]")
            print(f"Column: {result[0]}")
            print(f"Type: {result[1]}")
            print(f"Nullable: {result[2]}")

            # Check constraint
            cursor.execute("""
                SELECT constraint_name
                FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                AND table_name = 'test_results'
                AND constraint_name = 'fk_test_results_session'
            """)
            fk_result = cursor.fetchone()
            if fk_result:
                print(f"Foreign Key: {fk_result[0]} [OK]")

            # Check index
            cursor.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                AND tablename = 'test_results'
                AND indexname = 'idx_test_results_session_id'
            """)
            idx_result = cursor.fetchone()
            if idx_result:
                print(f"Index: {idx_result[0]} [OK]")

            print("\n[COMPLETE!] Migration completed successfully!")
            print("\nYou can now:")
            print("1. Restart your FastAPI server")
            print("2. Test multi-session result submission")

        else:
            print("[ERROR] Column was not added")
            return False

        cursor.close()
        conn.close()
        return True

    except psycopg2.Error as e:
        print(f"[ERROR] Database error: {e}")
        print(f"Error code: {e.pgcode}")
        return False
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("SEACMS Multi-Session Migration")
    print("Adding test_session_id to test_results table")
    print("=" * 60)
    print()

    success = apply_migration()
    sys.exit(0 if success else 1)
