#!/usr/bin/env python3
"""
One-time setup: create the recompute_jobs table (via the RecomputeJob model
in models.py), the shared copy of Recompute All job progress. Without it the
API keeps jobs only in the memory of the process that started them, so a
progress poll that reaches another process (the DR server, or a second
uvicorn worker) gets a 404 - "Recompute job is no longer available".

Run it once on one server (primary and DR share the database). Re-running
this script is safe.

Usage:
    python alter_recompute_jobs.py
"""
from database import VendorSessionLocal
from models import Base, RecomputeJob


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[RecomputeJob.__table__],
    )
    print("Ensured recompute_jobs table exists.")


if __name__ == "__main__":
    main()
