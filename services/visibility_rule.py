"""
Server-side evaluator for template "visibility_rule" blocks - the Python
counterpart to lib/common/rule_engine.dart's RuleEngine.COMPARE (Flutter),
used by report generators (HTML preview, PDF) so a section/field/row hidden
from the tester also stays hidden in the generated report, evaluated
directly against the rule rather than inferred from "is there any data".

Rule shape (same as the Flutter side):
    {"type": "COMPARE", "config": {"field": "voltage_ratio", "operator": "=", "value": "400"}}
    {"type": "COMPARE", "config": {"field": "voltage_ratio", "operator": "in", "values": ["400", "220"]}}
operator: "=" | "!=" | "<" | "<=" | ">" | ">=" | "in"
"""
from typing import Any, Dict, Optional


def evaluate_visibility_rule(rule: Optional[Dict[str, Any]], data: Dict[str, Any]) -> Optional[bool]:
    """Evaluate a visibility_rule against a flat data dict (typically
    TestResult.test_data). Returns:
      True/False - the rule was evaluated (the referenced field was present)
      None       - can't evaluate (no rule, unknown type, or the field is
                   entirely absent from data) - caller should fall back to
                   another signal (e.g. "does this section have any data").
    """
    if not rule:
        return None
    if rule.get("type") != "COMPARE":
        return None

    config = rule.get("config") or {}
    field = config.get("field")
    if not field or field not in data:
        return None

    raw = str(data.get(field) or "").strip()
    op = config.get("operator", "=")

    if op == "in":
        values = [str(v).strip() for v in (config.get("values") or [])]
        return raw in values

    target = str(config.get("value") or "").strip()

    def _num(s: str):
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    raw_num, target_num = _num(raw), _num(target)
    both_numeric = raw_num is not None and target_num is not None

    if op in ("=", "=="):
        return raw_num == target_num if both_numeric else raw == target
    if op == "!=":
        return raw_num != target_num if both_numeric else raw != target
    if op == "<":
        return both_numeric and raw_num < target_num
    if op == "<=":
        return both_numeric and raw_num <= target_num
    if op == ">":
        return both_numeric and raw_num > target_num
    if op == ">=":
        return both_numeric and raw_num >= target_num
    return None


def is_section_visible(section: Dict[str, Any], test_data: Dict[str, Any]) -> bool:
    """Decide whether a template section should appear in a generated
    report. Primary signal: evaluate the section's own visibility_rule
    directly against test_data. Fallback (when the rule can't be evaluated -
    e.g. an older saved result that never captured the bound field, such as
    voltage_ratio): treat the section as visible only if at least one of its
    fields actually has data, since a section the tester never saw never had
    any of its fields saved (see TestResultForm._collectData)."""
    result = evaluate_visibility_rule(section.get("visibility_rule"), test_data)
    if result is not None:
        return result

    fields = section.get("fields", [])
    return any(
        test_data.get(f.get("key", "")) not in (None, "", [])
        for f in fields
    )
