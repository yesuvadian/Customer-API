"""
Unit tests for the "equipment test with no usable threshold → CRITICAL" rule
in services/evaluation_service.py. Pure functions — no DB or server needed.

    pytest tests/test_no_threshold_evaluation.py -p no:cacheprovider --noconftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.evaluation_service import (  # noqa: E402
    EvaluationService as E, NO_THRESHOLD_VALUES, NOT_ASSESSED,
)


def _tpl(*fields, template_type="test", **extra):
    return {"template_type": template_type, "sections": [{"fields": list(fields)}], **extra}


IR = {"key": "ir", "label": "IR", "type": "number",
      "evaluation": {"enabled": True, "critical_below": 50, "normal_min": 100}}
NOTE = {"key": "note", "type": "text"}


# ── scope ────────────────────────────────────────────────────────────────────

def test_test_template_without_thresholds_is_critical():
    ev = E.evaluate_test_data(_tpl(NOTE), {"note": "x"})
    assert ev["overall"] == "CRITICAL"
    assert ev["unassessed_reason"] == NO_THRESHOLD_VALUES
    assert ev["no_threshold_values"] is True
    assert ev["fields"][0]["remedial_action_text"]


def test_non_test_templates_are_exempt():
    for ttype in ("nameplate", "repair_stage", "audit_stage", "failure_registry", None):
        ev = E.evaluate_test_data(_tpl(NOTE, template_type=ttype), {"note": "x"})
        assert ev["overall"] == "NORMAL", ttype
        assert "unassessed_reason" not in ev


def test_untyped_template_in_a_test_request_is_held_to_thresholds():
    # e.g. the static test_templates.py fallback — none carry template_type
    untyped = _tpl(NOTE, template_type=None)
    ev = E.evaluate_test_data(untyped, {"note": "x"}, is_equipment_test=True)
    assert ev["unassessed_reason"] == NO_THRESHOLD_VALUES
    assert E.evaluate_test_data(untyped, {"note": "x"}, is_equipment_test=False)["overall"] == "NORMAL"


def test_scope_precedence():
    req = E.requires_thresholds
    assert req(_tpl(NOTE)) is True                                   # typed test, no request
    assert req(_tpl(NOTE), is_equipment_test=False) is False         # used in a maintenance request
    assert req(_tpl(NOTE, template_type="nameplate"), True) is False # explicit non-test type wins
    # Template Designer stamps category_type; its tab default is "test"
    assert req(_tpl(NOTE, category_type="maintenance"), True) is False
    assert req(_tpl(NOTE, category_type="test"), True) is True


class _Req:
    def __init__(self, cat): self.request_category = cat


def test_is_equipment_test_request():
    from models import RequestCategory
    assert E.is_equipment_test_request(_Req(RequestCategory.test)) is True
    assert E.is_equipment_test_request(_Req(RequestCategory.maintenance)) is False
    assert E.is_equipment_test_request(_Req("test")) is True
    assert E.is_equipment_test_request(None) is None


def test_calibration_and_cumulative_rules_count_as_thresholds():
    cal = _tpl(NOTE, rules=[{"type": "DATE_ADD", "config": {"validity_field": "validity_months"}}])
    cum = _tpl(NOTE, rules=[{"type": "CUMULATIVE_DIFF", "config": {"default_threshold": 2000}}])
    for tpl in (cal, cum):
        assert E.threshold_sources(tpl) == {"rule"}
        ev = E.evaluate_test_data(tpl, {"note": "x"})
        assert ev["overall"] == "NORMAL" and ev["fields"] == []   # analytics scores it


# ── blocks that are switched on but hold no limit don't count ─────────────────

def test_enabled_blocks_without_limits_do_not_count():
    empty_number = {"key": "a", "type": "number", "evaluation": {"enabled": True}}
    all_normal_dd = {"key": "b", "type": "dropdown",
                     "dropdown_evaluation": {"enabled": True,
                                             "value_severities": {"Yes": "NORMAL", "No": "NORMAL"}}}
    agg_no_column = {"key": "c", "type": "table",
                     "table_evaluation": {"enabled": True, "aggregate_threshold": 5}}
    assert not E.has_threshold_values(_tpl(empty_number, all_normal_dd, agg_no_column))


def test_real_thresholds_count():
    dd = {"key": "b", "type": "dropdown",
          "dropdown_evaluation": {"enabled": True, "value_severities": {"Fail": "CRITICAL"}}}
    thr_table = {"key": "dga", "type": "table", "columns": [
        {"key": "cond", "type": "calculated",
         "rule": {"type": "THRESHOLD", "config": {"input_field": "ppm",
                                                  "thresholds": {"H2": {"Good": [0, 100]}}}}}]}
    for f in (IR, dd, thr_table):
        assert E.threshold_sources(_tpl(f)) == {"field"}, f["key"]


# ── thresholds exist but nothing was assessed ─────────────────────────────────

def test_blank_threshold_readings_are_not_assessed():
    ev = E.evaluate_test_data(_tpl(IR, NOTE), {"note": "only the note"})
    assert ev["overall"] == "CRITICAL"
    assert ev["unassessed_reason"] == NOT_ASSESSED


def test_threshold_rows_with_no_matching_entry_are_not_assessed():
    thr_table = {"key": "dga", "type": "table", "columns": [
        {"key": "gas", "type": "text"},
        {"key": "cond", "type": "calculated",
         "rule": {"type": "THRESHOLD", "config": {
             "input_field": "ppm", "lookup_fields": ["gas"],
             "thresholds": {"H2": {"Good": [0, 100], "Poor": [100, None]}}}}}]}
    ev = E.evaluate_test_data(_tpl(thr_table), {"dga": [{"gas": "N2", "ppm": 5}]})
    assert ev["unassessed_reason"] == NOT_ASSESSED


def test_only_limitless_results_do_not_count_as_assessed():
    all_normal_dd = {"key": "b", "type": "dropdown",
                     "dropdown_evaluation": {"enabled": True, "value_severities": {"Yes": "NORMAL"}}}
    ev = E.evaluate_test_data(_tpl(IR, all_normal_dd), {"b": "Yes"})
    assert ev["unassessed_reason"] == NOT_ASSESSED


def test_assessed_test_evaluates_normally():
    assert E.evaluate_test_data(_tpl(IR), {"ir": 150})["overall"] == "NORMAL"
    assert E.evaluate_test_data(_tpl(IR), {"ir": 10})["overall"] == "CRITICAL"
    assert "unassessed_reason" not in E.evaluate_test_data(_tpl(IR), {"ir": 10})


# ── cross-session merge ──────────────────────────────────────────────────────

def test_cross_session_lifts_not_assessed():
    ev = E._unassessed_result(NOT_ASSESSED)
    cross = {"overall": "ALERT", "fields": [{"key": "x", "status": "ALERT", "source": "cross_session"}]}
    E.merge_cross_session(ev, cross)
    assert ev["overall"] == "ALERT"
    assert "unassessed_reason" not in ev
    assert [f["key"] for f in ev["fields"]] == ["x"]


def test_cross_session_never_lifts_missing_thresholds():
    ev = E._unassessed_result(NO_THRESHOLD_VALUES)
    E.merge_cross_session(ev, {"overall": "NORMAL", "fields": [{"key": "x", "status": "NORMAL"}]})
    assert ev["overall"] == "CRITICAL"
    assert ev["unassessed_reason"] == NO_THRESHOLD_VALUES


def test_empty_cross_session_changes_nothing():
    ev = E._unassessed_result(NOT_ASSESSED)
    E.merge_cross_session(ev, {"overall": "NORMAL", "fields": []})
    assert ev["unassessed_reason"] == NOT_ASSESSED


# ── re-evaluating a stored result ────────────────────────────────────────────

class _Stored:
    template_key = "t"
    organization_id = None
    overall_result = "pass"
    test_data = {"note": "x"}
    evaluation_result = {"overall": "NORMAL", "fields": [], "cumulative_lifecycle": {"status": "NORMAL"}}


def test_reevaluate_stored_syncs_overall_result_and_keeps_extras(monkeypatch):
    monkeypatch.setattr(E, "get_template_data", staticmethod(lambda *a, **k: _tpl(NOTE)))
    r = _Stored()
    ev = E.reevaluate_stored(r, db=None)
    assert ev["overall"] == "CRITICAL"
    assert r.overall_result == "fail"
    assert r.evaluation_result is ev
    assert ev["cumulative_lifecycle"] == {"status": "NORMAL"}
