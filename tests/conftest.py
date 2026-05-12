"""
Root conftest.py — re-exports all session fixtures from conftest_outcome.py
so pytest discovers them for every file in this directory.
"""
from conftest_outcome import tokens, org_info, sample_equipment  # noqa: F401
