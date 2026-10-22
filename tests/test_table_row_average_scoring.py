"""
HealthScorer.score_test table scoring modes (Threshold Config "Table
scoring"): "worst_row" (original) vs "row_average". Pure unit tests - no db,
default points Good=100 / Fair=50 / Poor=-100.

    python -m pytest tests/test_table_row_average_scoring.py -p no:cacheprovider
"""
from services.analytics_engine import (
    HealthScorer,
    TABLE_SCORING_ROW_AVERAGE as AVG,
    TABLE_SCORING_WORST_ROW as WORST,
    _risk_from_score,
    risk_by_finding_checker,
)


def _tmpl(*fields):
    return {"sections": [{"fields": list(fields)}]}


def _threshold_table_eval(key, row_statuses, overall=None, **extra):
    rank = {"NORMAL": 0, "ALERT": 1, "CRITICAL": 2}
    overall = overall or max(row_statuses, key=lambda s: rank[s])
    return {
        "key": key, "type": "table", "status": overall,
        "row_results": [
            {"row_id": f"r{i}", "value": i, "status": s}
            for i, s in enumerate(row_statuses)
        ],
        "column_results": [],
        **extra,
    }


def _score(template, fields, mode):
    return HealthScorer.score_test(
        template, {"overall": "X", "fields": fields}, table_scoring_mode=mode)


TABLE = {"key": "dga", "type": "table", "label": "DGA"}
OTHER = {"key": "ir", "type": "number", "label": "IR"}


def test_one_bad_row_worst_row_vs_average():
    # 6 rows, one CRITICAL, plus one Good non-table field.
    t = _threshold_table_eval("dga", ["NORMAL"] * 5 + ["CRITICAL"])
    fields = [t, {"key": "ir", "status": "NORMAL"}]
    worst, _ = _score(_tmpl(TABLE, OTHER), fields, WORST)
    avg, findings = _score(_tmpl(TABLE, OTHER), fields, AVG)
    assert worst == 0.0                       # (-100 + 100) / 2
    # table = (5*100 - 100) / 6 = 66.67 ; test = (66.67 + 100) / 2
    assert round(avg, 1) == 83.3
    # risk unaffected: the CRITICAL row is still a critical finding
    assert any(f["status"] == "CRITICAL" for f in findings)
    assert _risk_from_score(avg, findings) == "Critical"


def test_every_row_failing_still_scores_zero():
    t = _threshold_table_eval("dga", ["CRITICAL"] * 4)
    avg, _ = _score(_tmpl(TABLE), [t], AVG)
    assert avg == 0.0


def test_default_mode_is_worst_row():
    t = _threshold_table_eval("dga", ["NORMAL", "CRITICAL"])
    default, _ = HealthScorer.score_test(_tmpl(TABLE), {"fields": [t]})
    assert default == 0.0


def test_column_table_rows_scored_at_worst_cell():
    # Row 0: two NORMAL cells. Row 1: NORMAL + CRITICAL -> row is CRITICAL.
    # Averaging cells would give (3*100 - 100)/4 = 50; by row it's 0.
    tbl = {"key": "td", "type": "table", "label": "Tan delta"}
    ef = {
        "key": "td", "type": "table", "status": "CRITICAL",
        "column_results": [
            {"column": "a", "row": 0, "row_label": "HV", "value": 1, "status": "NORMAL"},
            {"column": "b", "row": 0, "row_label": "HV", "value": 1, "status": "NORMAL"},
            {"column": "a", "row": 1, "row_label": "LV", "value": 9, "status": "NORMAL"},
            {"column": "b", "row": 1, "row_label": "LV", "value": 9, "status": "CRITICAL"},
        ],
    }
    avg, _ = _score(_tmpl(tbl), [ef], AVG)
    assert avg == 0.0  # (100 - 100) / 2
    ef["column_results"].append(
        {"column": "a", "row": 2, "row_label": "TV", "value": 1, "status": "NORMAL"})
    avg, _ = _score(_tmpl(tbl), [ef], AVG)
    assert round(avg, 2) == 33.33  # (100 - 100 + 100) / 3


def test_lowercase_or_unknown_cell_status_is_not_poor():
    tbl = {"key": "fx", "type": "table", "label": "Functional"}
    ef = {
        "key": "fx", "type": "table", "status": "CRITICAL",
        "column_results": [
            {"column": "a", "row": 0, "value": "Pass", "status": "normal"},
            {"column": "a", "row": 1, "value": "?", "status": "PASS"},
            {"column": "a", "row": 2, "value": "Fail", "status": "critical"},
        ],
    }
    avg, _ = _score(_tmpl(tbl), [ef], AVG)
    assert round(avg, 2) == 33.33  # (100 + 100 - 100) / 3


def test_table_level_verdict_counts_as_extra_row():
    # Duval zone raised the table to CRITICAL with every gas row NORMAL.
    t = _threshold_table_eval("dga", ["NORMAL"] * 3, overall="CRITICAL",
                              duval_zone="T3")
    avg, _ = _score(_tmpl(TABLE), [t], AVG)
    assert avg == 50.0  # (3*100 - 100) / 4, not 100


def test_duval_critical_over_alert_rows_stays_critical():
    # Dev data case: Duval D2 makes the table CRITICAL, worst gas row is
    # only ALERT. Row average lifts the score, so risk must come from a
    # table-level CRITICAL finding.
    t = _threshold_table_eval(
        "dga", ["NORMAL"] * 7 + ["ALERT"], overall="CRITICAL",
        duval_zone="D2", remedial_action_text="Duval Triangle zone D2 ...")
    for mode in (WORST, AVG):
        score, findings = _score(_tmpl(TABLE), [t], mode)
        crit = [f for f in findings if f["status"] == "CRITICAL"]
        assert len(crit) == 1 and "Duval zone D2" in crit[0]["label"]
        assert _risk_from_score(score, findings) == "Critical"
    assert round(_score(_tmpl(TABLE), [t], AVG)[0], 2) == 72.22


def test_no_row_detail_falls_back_to_worst_row():
    ef = {"key": "dga", "type": "table", "status": "CRITICAL"}
    avg, _ = _score(_tmpl(TABLE), [ef], AVG)
    assert avg == 0.0


def test_table_keeps_its_weight():
    tbl = {"key": "dga", "type": "table", "label": "DGA",
           "table_evaluation": {"weight": 3}}
    t = _threshold_table_eval("dga", ["NORMAL", "CRITICAL"])  # table avg 0
    avg, _ = _score(_tmpl(tbl, OTHER), [t, {"key": "ir", "status": "NORMAL"}], AVG)
    assert avg == 25.0  # (0*3 + 100*1) / 4


def test_alert_row_finding_condition_is_fair():
    t = _threshold_table_eval("dga", ["NORMAL", "ALERT"])
    _, findings = _score(_tmpl(TABLE), [t], AVG)
    assert [f["condition"] for f in findings] == ["Fair"]


def test_risk_by_finding_check():
    check = risk_by_finding_checker(None)  # default bands
    assert check(85.7, "Critical") is True
    assert check(0.0, "Critical") is False
    assert check(85.7, "Low") is False
    assert check(None, "Critical") is False
