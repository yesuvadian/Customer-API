#!/usr/bin/env python3
"""
One-time setup: create the deterioration_review_records table (via the
DeteriorationReviewRecord model in models.py) — no seed data, this table is
populated by officers using the app (POST /analytics/deterioration-watch-
list/review), not by any script.

Usage:
    python alter_deterioration_review_record.py
"""
from database import VendorSessionLocal
from models import Base, DeteriorationReviewRecord


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[DeteriorationReviewRecord.__table__],
    )
    print("Ensured deterioration_review_records table exists.")


if __name__ == "__main__":
    main()
