"""Report sections and the modules in each, in report order.

The order departs from TRD §4 "Report structure" on purpose: after the summary, the location
sets the scene, then the most insightful analysis (demographics, access, flood) comes first to
hook the reader, and area signals close the report.
"""

from django.utils.translation import gettext_lazy as _

SECTIONS = [
    ("location", _("Location and boundary check"), ["location"]),
    ("demographics", _("Demographics and area growth"), ["demographics"]),
    ("access", _("Access and services"), ["access"]),
    ("water_terrain", _("Flood, water and terrain"), ["flood", "terrain"]),
    ("red_flags", _("Regulatory red flags"), ["red_flags"]),
    ("occupation", _("Current imagery and occupation"), ["imagery", "buildings"]),
    ("change", _("Change over time"), ["change"]),
    ("field", _("Field verification findings"), ["field"]),
    ("signals", _("Area signals: reported land issues nearby"), ["signals"]),
]

MODULE_ORDER = [module for _key, _title, modules in SECTIONS for module in modules]
# Modules whose two maps show the same area and read best side by side in the PDF.
PAIRED_MAPS = {"demographics", "access", "flood"}


def sections_for(order):
    """The sections this order's report contains (field findings only on the field tier)."""
    return [s for s in SECTIONS if s[0] != "field" or order.tier == "field"]


def requester(order):
    """Who the report was prepared for, for the cover: name, organisation and intended use.
    No email or phone: the report can be shared, and share links promise not to show them."""
    customer = order.customer
    organization = order.organization or customer.organization
    return {
        "name": customer.get_full_name(),
        "organization": organization.name if organization else "",
        "intended_use": order.intended_use,
    }


def statement_for(key):
    """Fixed text a section always carries, in the active language (FR-34 for area signals)."""
    if key == "signals":
        from apps.analysis.modules.signals import statement

        return statement()
    return ""


def in_report_order(findings):
    """Findings sorted like the sections, so the summary scorecard reads in the same order
    (drafts made before a reorder keep their stored order otherwise)."""
    rank = {module: i for i, module in enumerate(MODULE_ORDER)}
    return sorted(findings, key=lambda f: rank.get(f["module"], len(rank)))
