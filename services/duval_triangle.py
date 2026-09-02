"""
Duval Triangle 1 — transformer fault-type classification from DGA gas ratios.
==============================================================================
KPTCL spec Part II §3 / §12.x: "DGA Trend Report... with Duval Triangle
classification." This is a DIFFERENT diagnostic from the absolute-ppm
NORMAL/ALERT/CRITICAL thresholds already implemented per-gas in the
transformer_dga test template (test_templates.py) — that method flags
"is any single gas concentration too high"; the Duval Triangle instead asks
"given the RELATIVE proportions of three key gases, what TYPE of fault is
this" (thermal vs. electrical, and how severe), which absolute thresholds
alone cannot answer — a sample can have every gas within Normal range and
still show a ratio pattern consistent with an active low-energy fault.

────────────────────────────────────────────────────────────────────────────
ACCURACY / VALIDATION STATUS — read before relying on this for a real
maintenance decision
────────────────────────────────────────────────────────────────────────────
The zone boundaries below are the widely-published Duval Triangle 1 method
(IEC 60599), reconstructed from general engineering knowledge, not
transcribed from a KPTCL-supplied or freshly-verified copy of the standard
- and the boundary has been revised across different IEC 60599 editions.
There is currently zero real DGA test data in this org to validate the
classifier's output against.

Per the spec's own explicit requirement ("All AI-generated outputs are
clearly labelled as AI Advisory... require review by a qualified officer
before any action is initiated" - PART E, and "actual test types...
threshold parameters shall be provided by KPTCL's RT & R&D sections" -
PART C note), every classification this module returns carries that same
status: AI Advisory, NOT a validated diagnostic, until KPTCL's RT & R&D
section confirms the exact boundary coefficients against their adopted
standard revision. Do not remove the advisory flag from API responses that
use this module.
"""

from __future__ import annotations

ADVISORY_NOTE = (
    "AI Advisory — Duval Triangle zone boundaries are the general IEC 60599 "
    "method, not yet validated against KPTCL RT & R&D's specific standard "
    "revision. Confirm with a qualified officer before acting on this "
    "classification."
)

# Zone name -> plain-language meaning, shown alongside the code so a
# reviewing officer doesn't have to look the abbreviation up separately.
ZONE_MEANINGS = {
    "PD": "Partial discharges (corona)",
    "T1": "Thermal fault, < 300°C",
    "T2": "Thermal fault, 300–700°C",
    "T3": "Thermal fault, > 700°C",
    "D1": "Discharge of low energy",
    "D2": "Discharge of high energy",
    "DT": "Mixture of thermal and electrical fault",
}


def gas_percentages(ch4: float, c2h4: float, c2h2: float) -> tuple[float, float, float] | None:
    """Normalize the three key gases to percentages summing to 100.
    Returns None if all three readings are zero/missing (nothing to plot).
    """
    total = (ch4 or 0) + (c2h4 or 0) + (c2h2 or 0)
    if total <= 0:
        return None
    return (100.0 * (ch4 or 0) / total, 100.0 * (c2h4 or 0) / total, 100.0 * (c2h2 or 0) / total)


def classify_duval_triangle(ch4: float, c2h4: float, c2h2: float) -> dict:
    """
    Classify a fault type from CH4/C2H4/C2H2 concentrations (any consistent
    unit — only their ratio matters). Uses the simplified axis-aligned
    decision rules most consistently published across DGA interpretation
    references for Duval Triangle 1, rather than attempting the full
    diagonal-boundary polygon geometry from memory (see module docstring's
    accuracy note — the diagonal D1/D2/DT boundaries carry materially more
    reconstruction uncertainty than the T1/T2/T3 axis-aligned ones, so this
    intentionally stays on the more defensible subset of the standard).

    Returns {"zone": str|None, "meaning": str|None, "pct_ch4": float,
    "pct_c2h4": float, "pct_c2h2": float, "advisory": str} — zone/meaning
    are None if there isn't enough gas present to classify.
    """
    pct = gas_percentages(ch4, c2h4, c2h2)
    if pct is None:
        return {
            "zone": None, "meaning": None,
            "pct_ch4": None, "pct_c2h4": None, "pct_c2h2": None,
            "advisory": ADVISORY_NOTE,
        }
    pct_ch4, pct_c2h4, pct_c2h2 = pct

    if pct_c2h2 < 4:
        # Low-discharge-gas region: thermal-fault axis, banded by %C2H4.
        if pct_c2h2 < 1 and pct_c2h4 < 20:
            zone = "PD"
        elif pct_c2h4 < 20:
            zone = "T1"
        elif pct_c2h4 < 50:
            zone = "T2"
        else:
            zone = "T3"
    elif pct_c2h2 < 13:
        zone = "DT" if pct_c2h4 >= 50 else "D1"
    else:
        zone = "D2" if pct_c2h2 >= pct_c2h4 else "DT"

    return {
        "zone": zone,
        "meaning": ZONE_MEANINGS.get(zone),
        "pct_ch4": round(pct_ch4, 1),
        "pct_c2h4": round(pct_c2h4, 1),
        "pct_c2h2": round(pct_c2h2, 1),
        "advisory": ADVISORY_NOTE,
    }
