"""Report order: the most insightful analysis first, area signals last."""

from apps.analysis.modules import MODULES
from apps.reports.structure import MODULE_ORDER, SECTIONS, in_report_order


def test_location_then_demographics_access_flood_lead_and_signals_end():
    keys = [key for key, _title, _modules in SECTIONS]
    assert keys[:4] == ["location", "demographics", "access", "water_terrain"]
    assert keys[-1] == "signals"


def test_module_registry_follows_section_order():
    assert list(MODULES) == [m for m in MODULE_ORDER if m in MODULES]


def test_in_report_order_sorts_stored_findings():
    stored = [{"module": m} for m in ("location", "imagery", "flood", "demographics", "access")]
    assert [f["module"] for f in in_report_order(stored)] == [
        "location",
        "demographics",
        "access",
        "flood",
        "imagery",
    ]
