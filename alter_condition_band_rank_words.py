#!/usr/bin/env python3
"""
One-time setup: create the condition_band_rank_words table (via the
ConditionBandRankWord model in models.py) and seed it with the word/phrase
-> severity rank (0=best, 1=mid, 2=worst) list that used to be hardcoded
independently in two places:

  - routers/analytics.py's _BAND_RANK_WORDS (used by _next_worse_boundary
    to rank ParameterThresholdBand rows for breach forecasting)
  - services/evaluation_service.py's _cond_rank (used by
    _eval_threshold_table to rank a table row's own bands at
    test-evaluation time)

Confirmed live the two copies had already drifted (analytics.py's had
"excellent", evaluation_service.py's didn't) — this is the single seed
list both now read from at runtime via
services/analytics_engine.py's _load_band_rank_words, same
db-with-hardcoded-fallback pattern as _load_risk_bands/
_load_condition_labels/_load_condition_scores.

This is a one-time seed, not an extraction like
alter_parameter_threshold_band.py — there's no single template source of
truth for this word list, it's app-level config. Re-running is safe and
idempotent (updates existing phrases' rank by their unique key, inserts
any missing ones, never duplicates).

Usage:
    python alter_condition_band_rank_words.py
"""
from database import VendorSessionLocal
from models import Base, ConditionBandRankWord
from services.analytics_engine import _DEFAULT_BAND_RANK_WORDS


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[ConditionBandRankWord.__table__],
    )
    print("Ensured condition_band_rank_words table exists.")

    db = VendorSessionLocal()
    try:
        inserted = updated = 0
        for phrase, rank in _DEFAULT_BAND_RANK_WORDS.items():
            existing = (
                db.query(ConditionBandRankWord)
                .filter(ConditionBandRankWord.phrase == phrase)
                .first()
            )
            if existing:
                if existing.rank != rank:
                    existing.rank = rank
                    updated += 1
            else:
                db.add(ConditionBandRankWord(phrase=phrase, rank=rank))
                inserted += 1

        db.commit()
        print(f"Seeded condition_band_rank_words: "
              f"{inserted} phrase(s) inserted, {updated} rank(s) updated, "
              f"{len(_DEFAULT_BAND_RANK_WORDS) - inserted - updated} already current.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
