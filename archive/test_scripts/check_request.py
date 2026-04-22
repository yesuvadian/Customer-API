"""
Check request TR-20260421-0005 details
"""
import psycopg2

DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'Relu_Vendor2',
    'user': 'relu_user',
    'password': 'StrongPassword123!'
}

def check_request():
    """Check the request and sessions"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print("=" * 70)
        print("CHECKING REQUEST: TR-20260421-0005")
        print("=" * 70)

        # Check request details
        cursor.execute("""
            SELECT
                id,
                request_number,
                title,
                is_multi_session,
                total_sessions_planned,
                status,
                cts
            FROM public.testing_requests
            WHERE request_number = 'TR-20260421-0005'
        """)

        request = cursor.fetchone()
        if not request:
            print("\n[ERROR] Request TR-20260421-0005 not found!")
            return

        request_id, req_num, title, is_multi, total_sessions, status, created = request

        print(f"\n[REQUEST DETAILS]")
        print(f"  ID: {request_id}")
        print(f"  Request Number: {req_num}")
        print(f"  Title: {title}")
        print(f"  Status: {status}")
        print(f"  Is Multi-Session: {is_multi}")
        print(f"  Total Sessions Planned: {total_sessions}")
        print(f"  Created: {created}")

        # Check test sessions
        cursor.execute("""
            SELECT
                id,
                session_number,
                status,
                started_at,
                completed_at
            FROM public.test_sessions
            WHERE testing_request_id = %s
            ORDER BY session_number
        """, (request_id,))

        sessions = cursor.fetchall()

        print(f"\n[TEST SESSIONS]")
        if sessions:
            print(f"  Total Sessions Created: {len(sessions)}")
            for sess in sessions:
                sess_id, sess_num, sess_status, started, completed = sess
                print(f"\n  Session {sess_num}:")
                print(f"    ID: {sess_id}")
                print(f"    Status: {sess_status}")
                print(f"    Started: {started}")
                print(f"    Completed: {completed or 'Not completed'}")

                # Count readings for this session
                cursor.execute("""
                    SELECT COUNT(*) FROM public.test_results
                    WHERE test_session_id = %s
                """, (sess_id,))
                reading_count = cursor.fetchone()[0]
                print(f"    Readings: {reading_count}")
        else:
            print("  [WARNING] No sessions found!")
            print("  This could be why the UI shows nothing.")

        # Check test results (linked to session)
        cursor.execute("""
            SELECT
                id,
                test_session_id,
                template_key,
                overall_result,
                cts
            FROM public.test_results
            WHERE testing_request_id = %s
            ORDER BY cts DESC
        """, (request_id,))

        results = cursor.fetchall()

        print(f"\n[TEST RESULTS]")
        if results:
            print(f"  Total Results: {len(results)}")
            for res in results:
                res_id, sess_id, template, overall, created = res
                print(f"\n  Result: {template}")
                print(f"    ID: {res_id}")
                print(f"    Session ID: {sess_id or 'NOT LINKED TO SESSION!'}")
                print(f"    Overall Result: {overall}")
                print(f"    Created: {created}")
        else:
            print("  No test results found")

        print("\n" + "=" * 70)
        print("DIAGNOSIS:")
        print("=" * 70)

        if not is_multi:
            print("\n⚠️  PROBLEM: is_multi_session is FALSE or NULL")
            print("   → Flutter UI won't show Testing Sessions section")
            print("   → Backend won't auto-create sessions")
            print("\n   FIX: Set is_multi_session = TRUE for this request")
        elif not sessions:
            print("\n⚠️  PROBLEM: No test sessions exist")
            print("   → Sessions should auto-create when testing starts")
            print("   → Or manually via 'Start New Session' button")
            print("\n   FIX: Backend needs to create first session")
        elif results and any(r[1] is None for r in results):
            print("\n⚠️  PROBLEM: Test results exist but NOT linked to sessions")
            print("   → Results have test_session_id = NULL")
            print("   → They won't show in session timeline")
            print("\n   FIX: Link existing results to a session")
        else:
            print("\n✅  Everything looks correct!")
            print("   → Check Flutter app refresh or API response")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\n[ERROR] {e}")

if __name__ == "__main__":
    check_request()
