"""Report sections and the modules in each, in report order.

The order departs from TRD §4 "Report structure" on purpose: after the summary, the most
insightful analysis (demographics, access, flood) comes first to hook the reader, and area
signals close the report.
"""

from django.utils.translation import gettext_lazy as _

SECTIONS = [
    ("demographics", _("Demographics and area growth"), ["demographics"]),
    ("access", _("Access and services"), ["access"]),
    ("water_terrain", _("Flood, water and terrain"), ["flood", "terrain"]),
    ("red_flags", _("Regulatory red flags"), ["red_flags"]),
    ("occupation", _("Current imagery and occupation"), ["imagery", "buildings"]),
    ("change", _("Change over time"), ["change"]),
    ("location", _("Location and boundary check"), ["location"]),
    ("field", _("Field verification findings"), ["field"]),
    ("signals", _("Area signals: reported land issues nearby"), ["signals"]),
]

MODULE_ORDER = [module for _key, _title, modules in SECTIONS for module in modules]


def sections_for(order):
    """The sections this order's report contains (field findings only on the field tier)."""
    return [s for s in SECTIONS if s[0] != "field" or order.tier == "field"]


def in_report_order(findings):
    """Findings sorted like the sections, so the summary scorecard reads in the same order
    (drafts made before a reorder keep their stored order otherwise)."""
    rank = {module: i for i, module in enumerate(MODULE_ORDER)}
    return sorted(findings, key=lambda f: rank.get(f["module"], len(rank)))
