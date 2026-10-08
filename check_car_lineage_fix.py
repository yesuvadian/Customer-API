"""Read-only check for the CAR-lineage provenance fix (car_service.py:
_lineage_test_request_ids / _inflight_request now require
test_request_type != "ORIGINAL").

Usage:
    python3 check_car_lineage_fix.py TR-KP-2026-1703

Prints:
  - the target TR's own fields (id, test_request_type, status)
  - every sibling TR (same equipment_id + test_type_id) with its
    test_request_type, and whether _lineage_test_request_ids would now
    include it (post-fix) vs. would have included it before the fix
  - every open CAR whose lineage/linked TRs the target TR touches, and
    whether the target TR is linked to it in car_test_requests

Run this against the SAME database your app/API uses - not this shell's
local Relu_Vendor Postgres, which has no CAR data.
"""
import sys

from database import VendorSessionLocal
from sqlalchemy import text


def main(request_number: str) -> None:
    db = VendorSessionLocal()
    try:
        tr = db.execute(
            text(
                """
                SELECT id, request_number, test_request_type, status,
                       equipment_id, test_type_id, parent_request_id
                  FROM testing_requests
                 WHERE request_number = :rn
                """
            ),
            {"rn": request_number},
        ).mappings().first()

        if not tr:
            print(f"No TR found with request_number={request_number!r}")
            return

        print("Target TR:")
        for k, v in tr.items():
            print(f"  {k}: {v}")
        print()

        siblings = db.execute(
            text(
                """
                SELECT id, request_number, test_request_type, status
                  FROM testing_requests
                 WHERE equipment_id = :eq
                   AND test_type_id = :tt
                   AND id != :self_id
                """
            ),
            {"eq": tr["equipment_id"], "tt": tr["test_type_id"], "self_id": tr["id"]},
        ).mappings().all()

        print(f"Sibling TRs (same equipment_id + test_type_id): {len(siblings)}")
        for s in siblings:
            would_include_post_fix = s["test_request_type"] != "ORIGINAL"
            print(
                f"  {s['request_number']}: test_request_type={s['test_request_type']!r} "
                f"status={s['status']!r} -> "
                f"{'INCLUDED in lineage (system-raised)' if would_include_post_fix else 'EXCLUDED from lineage (manual/ORIGINAL) [fix applies here]'}"
            )
        print()

        cars = db.execute(
            text(
                """
                SELECT c.id, c.car_number, c.status
                  FROM corrective_action_requests c
                  JOIN car_test_requests ctr ON ctr.car_id = c.id
                 WHERE ctr.test_request_id = ANY(:ids)
                """
            ),
            {"ids": [tr["id"]] + [s["id"] for s in siblings]},
        ).mappings().all()

        seen = set()
        print("CARs touching this TR or its (pre-fix) siblings:")
        for c in cars:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            linked_to_target = db.execute(
                text(
                    "SELECT 1 FROM car_test_requests WHERE car_id = :cid AND test_request_id = :tid"
                ),
                {"cid": c["id"], "tid": tr["id"]},
            ).first()
            print(
                f"  {c['car_number']} (status={c['status']}) - "
                f"target TR {'IS' if linked_to_target else 'is NOT'} linked to it"
            )
        if not cars:
            print("  (none)")

    finally:
        db.close()


def check_car(car_number: str) -> None:
    db = VendorSessionLocal()
    try:
        car = db.execute(
            text("SELECT id, car_number, status FROM corrective_action_requests WHERE car_number = :cn"),
            {"cn": car_number},
        ).mappings().first()
        if not car:
            print(f"No CAR found with car_number={car_number!r}")
            return

        print(f"CAR {car['car_number']} (status={car['status']}) linked test requests:")
        rows = db.execute(
            text(
                """
                SELECT tr.request_number, tr.test_request_type, tr.status,
                       tr.originator_id, ctr.relationship_type
                  FROM car_test_requests ctr
                  JOIN testing_requests tr ON tr.id = ctr.test_request_id
                 WHERE ctr.car_id = :cid
                 ORDER BY tr.cts
                """
            ),
            {"cid": car["id"]},
        ).mappings().all()

        for r in rows:
            flag = " <-- WRONGLY LINKED (manual/ORIGINAL, would be excluded post-fix)" if r["test_request_type"] == "ORIGINAL" else ""
            print(
                f"  {r['request_number']}: test_request_type={r['test_request_type']!r} "
                f"status={r['status']!r} relationship_type={r['relationship_type']!r}{flag}"
            )
        if not rows:
            print("  (none)")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1].upper().startswith("CAR-"):
        check_car(sys.argv[1])
    elif len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        print("usage: python3 check_car_lineage_fix.py <request_number>")
        print("       python3 check_car_lineage_fix.py <car_number>")
        sys.exit(1)
