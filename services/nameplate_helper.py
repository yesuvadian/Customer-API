"""
Shared equipment-identity lookups for report generators.

Every report generator (PDF / HTML / Excel, across testing requests, test
sessions and consolidated reports) needs to pull the same handful of fields
— capacity and voltage ratio in particular — out of Equipment.nameplate_data.
Each generator used to check a different subset of key names, so the same
equipment could show "-" in one report and a real value in another. These
helpers are the single source of truth for those lookups.
"""

# Different nameplate templates have stored capacity under different keys
# over time (rated_mva, capacity_mva, mva_rating, ...) — check them all.
_CAPACITY_KEYS = (
    "rated_mva", "rated_mva_onan", "rated_mva_onan_mva",
    "capacity_mva", "mva_rating", "rated_capacity", "capacity", "kva_rating",
)


def get_capacity(nameplate_data: dict, blank: str = "-") -> str:
    """Resolve equipment capacity from nameplate_data, trying every known key."""
    nd = nameplate_data or {}
    for key in _CAPACITY_KEYS:
        val = nd.get(key)
        if val not in (None, "", 0, "0"):
            val_str = str(val)
            if "MVA" not in val_str.upper() and "KVA" not in val_str.upper():
                val_str += " MVA"
            return val_str
    return blank


def get_voltage_ratio(nameplate_data: dict, voltage_class: str = None, blank: str = "-") -> str:
    """Resolve transformer voltage ratio (e.g. "220/66/11 kV") from nameplate_data.

    Tries, in order: an explicit `voltage_ratio` key, HV/MV/LV voltage keys
    (in either naming convention used by different templates), a single
    voltage-class value recorded in the same dict (`voltage_class` /
    `transformer_voltage` — not a true ratio, but more useful than blank when
    that's all that was ever captured), then finally the Equipment.voltage_class
    column passed in by the caller.
    """
    nd = nameplate_data or {}

    ratio = nd.get("voltage_ratio")
    if ratio not in (None, ""):
        return str(ratio)

    for hv_key, mv_key, lv_key in (
        ("hv_voltage", "mv_voltage", "lv_voltage"),
        ("hv_voltage_kv", "mv_voltage_kv", "lv_voltage_kv"),
    ):
        hv = nd.get(hv_key)
        if hv not in (None, ""):
            parts = [str(x) for x in (hv, nd.get(mv_key), nd.get(lv_key)) if x not in (None, "")]
            return "/".join(parts) + " kV"

    single = nd.get("voltage_class") or nd.get("transformer_voltage") or voltage_class
    if single not in (None, ""):
        single_str = str(single)
        return single_str if "KV" in single_str.upper() else f"{single_str} kV"

    return blank


def resolve_capacity(*sources: dict, blank: str = "-") -> str:
    """Try get_capacity against each source dict in order, first hit wins.

    Equipment.nameplate_data is often left blank at onboarding time, but the
    same values frequently get typed into a test's own form fields (e.g. the
    transformer oil test template's "Rated MVA" field). Pass the equipment
    register first, then any TestResult.test_data dicts as fallbacks, so the
    report shows a real value when the register is incomplete.
    """
    for src in sources:
        val = get_capacity(src, blank="")
        if val:
            return val
    return blank


def resolve_voltage_ratio(*sources: dict, voltage_class: str = None, blank: str = "-") -> str:
    """Try get_voltage_ratio against each source dict in order, first hit wins."""
    for src in sources:
        val = get_voltage_ratio(src, blank="")
        if val:
            return val
    if voltage_class not in (None, ""):
        vc = str(voltage_class)
        return vc if "KV" in vc.upper() else f"{vc} kV"
    return blank
