import psycopg2

conn = psycopg2.connect(
    database='Relu_Vendor2',
    user='relu_user',
    password='StrongPassword123!',
    host='localhost',
    port='5432'
)

cur = conn.cursor()

# Check if table exists
cur.execute("""
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'tester_role_module_requirements'
""")

if cur.fetchone():
    print("[OK] Table 'tester_role_module_requirements' exists")

    # Check columns
    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'tester_role_module_requirements'
        ORDER BY ordinal_position
    """)

    columns = cur.fetchall()
    print(f"\n[OK] Table has {len(columns)} columns:")
    for col in columns:
        print(f"  - {col[0]:30s} {col[1]}")

    # Check if seeded
    cur.execute("SELECT COUNT(*) FROM tester_role_module_requirements")
    count = cur.fetchone()[0]
    print(f"\n[INFO] Table has {count} rows")

    if count == 0:
        print("[INFO] No seed data yet, inserting default configuration...")
        cur.execute("""
            INSERT INTO public.tester_role_module_requirements (
                id,
                organization_id,
                required_module_ids,
                description,
                is_active
            ) VALUES (
                gen_random_uuid(),
                NULL,
                ARRAY[45, 46, 49, 51],
                'Global default: Roles must have full permissions on Testing Requests, Testing, Testing Request Approvals, and Tester Mapping modules',
                TRUE
            )
            RETURNING id, required_module_ids
        """)
        result = cur.fetchone()
        conn.commit()
        print(f"[OK] Seed data inserted: ID={result[0]}, Modules={result[1]}")
    else:
        print("\n[OK] Existing configurations:")
        cur.execute("""
            SELECT id, organization_id, required_module_ids, description
            FROM tester_role_module_requirements
        """)
        for row in cur.fetchall():
            print(f"  ID: {row[0]}")
            print(f"  Org: {'Global Default' if row[1] is None else row[1]}")
            print(f"  Modules: {row[2]}")
            print(f"  Description: {row[3]}")
            print()
else:
    print("[ERROR] Table 'tester_role_module_requirements' does not exist!")

cur.close()
conn.close()
