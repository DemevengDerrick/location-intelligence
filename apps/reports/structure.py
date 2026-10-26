"""Report sections in the order of TRD §4 "Report structure", and the modules in each."""

from django.utils.translation import gettext_lazy as _

SECTIONS = [
    ("location", _("Location and boundary check"), ["location"]),
    ("occupation", _("Current imagery and occupation"), ["imagery", "buildings"]),
    ("change", _("Change over time"), ["change"]),
    ("water_terrain", _("Flood, water and terrain"), ["flood", "terrain"]),
    ("access", _("Access and services"), ["access"]),
    ("demographics", _("Demographics and area growth"), ["demographics"]),
    ("red_flags", _("Regulatory red flags"), ["red_flags"]),
    ("signals", _("Area signals: reported land issues nearby"), ["signals"]),
    ("field", _("Field verification findings"), ["field"]),
]


def sections_for(order):
    """The sections this order's report contains (field findings only on the field tier)."""
    return [s for s in SECTIONS if s[0] != "field" or order.tier == "field"]
