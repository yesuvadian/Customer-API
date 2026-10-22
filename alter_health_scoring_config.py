#!/usr/bin/env python3
"""
One-time setup: create the health_scoring_config table (via the
HealthScoringConfig model in models.py), which holds the "Table scoring"
setting on the Threshold Config page (worst row / row average — see
HealthScorer.score_test in services/analytics_engine.py).

No row is seeded: with the table empty the scorer keeps its original
"worst_row" behaviour, and GET /threshold-config/health-scoring reports
is_configured=False. The first save from the Threshold Config page creates
the row. Re-running this script is safe.

Usage:
    python alter_health_scoring_config.py
"""
from database import VendorSessionLocal
from models import Base, HealthScoringConfig


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[HealthScoringConfig.__table__],
    )
    print("Ensured health_scoring_config table exists.")


if __name__ == "__main__":
    main()
