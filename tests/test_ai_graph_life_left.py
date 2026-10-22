"""
Life-left maths behind the AI Graph Dashboard (routers/ai_graph.py).

Pure unit tests - db=None uses the hard-coded expected-life defaults
(power transformer = 30 yrs), no database needed.

    python -m pytest tests/test_ai_graph_life_left.py -v
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from routers import ai_graph as G  # noqa: E402


def _commissioned(years_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=years_ago * 365.25)


def test_life_left_within_expected_life():
    ll = G._life_left(_commissioned(20), "Power Transformer", None)
    assert round(ll, 1) == 10.0


def test_life_left_past_expected_life_is_negative_not_zero():
    # 37 years old, 30-year life: 7 years overdue - used to clamp to 0.0.
    ll = G._life_left(_commissioned(37), "Power Transformer", None)
    assert round(ll, 1) == -7.0


def test_life_left_unknown_without_commissioned_date():
    assert G._life_left(None, "Power Transformer", None) is None


def test_overdue_has_its_own_bucket():
    assert G._life_bucket(-0.1) == "Overdue"
    assert G._life_bucket(-12) == "Overdue"
    assert G._life_bucket(0) == "0–5 yrs"
    assert G._life_bucket(4.9) == "0–5 yrs"
    assert G._life_bucket(25) == "25+ yrs"


def test_just_past_end_of_life_rounds_to_zero_bucket():
    # -0.04 is shown as 0.0 yr - the overview buckets it the same way.
    assert G._life_bucket(round(-0.04, 1)) == "0–5 yrs"
