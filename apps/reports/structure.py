"""Report sections and the modules in each, in report order.

The order departs from TRD §4 "Report structure" on purpose: after the summary, the location
sets the scene, then the most insightful analysis (demographics, access, flood) comes first to
hook the reader, and area signals close the report.
"""

from django.utils.translation import gettext_lazy as _

SECTIONS = [
    ("location", _("Location and boundary"), ["location"]),
    ("demographics", _("People and area growth"), ["demographics"]),
    ("access", _("Access and services"), ["access"]),
    ("water_terrain", _("Flooding and slope"), ["flood", "terrain"]),
    ("red_flags", _("Rules and restrictions"), ["red_flags"]),
    ("occupation", _("What is on the land today"), ["imagery", "buildings"]),
    ("change", _("Change over time"), ["change"]),
    ("field", _("Field verification findings"), ["field"]),
    ("signals", _("Land issues reported nearby"), ["signals"]),
]

# What each section's data cannot show, in everyday words: printed under every section so
# readers know the findings are indicative and need checking on the ground.
LIMITS = {
    "location": _(
        "We used the boundary you gave us; we did not survey it. Only a sworn surveyor "
        "(géomètre) can confirm the boundary and area on the ground, and only the land registry "
        "can confirm who owns the land."
    ),
    "demographics": _(
        "Population figures are estimates from computer models, not census counts. They are "
        "less reliable for small areas, and future figures are projections. Ages and sexes come "
        "from one profile per region, so they describe the region, not the neighbourhood. "
        "Local statistics or a visit may give a different picture."
    ),
    "access": _(
        "Travel times are calculated on roads mapped by volunteers (OpenStreetMap), without "
        "traffic. Unmapped tracks, closed roads or rainy-season conditions can change them. "
        "Visit the site to see how it is really reached."
    ),
    "water_terrain": _(
        "The flood data only covers large rivers, at about 90 m detail: it does not show "
        "flooding from heavy rain, blocked drains or the sea. Slopes come from 30 m elevation "
        "data that includes buildings and trees. Neighbours' experience and a visit in the "
        "rainy season remain essential."
    ),
    "red_flags": _(
        "We can only check rules that appear on the maps we have. Many constraints, such as "
        "planned roads, local zoning or customary claims, are not mapped. The commune's urban "
        "planning office and the land registry have the final word."
    ),
    "occupation": _(
        "Satellite images have 10 m pixels: they show what generally covers the land, not "
        "small buildings. The building map can be a few years old and miss recent or small "
        "structures. Only a visit tells you who is on the land today."
    ),
    "change": _(
        "Changes are measured on 10 m satellite pixels with one image a year; clouds, seasons "
        "and small parcels make the figures indicative only. Very recent work may not show "
        "yet."
    ),
    "field": "",
    "signals": _(
        "We only find what the news outlets we follow published online, checked by an "
        "analyst. Many disputes are never reported: ask neighbours and the local authorities."
    ),
}

# The red box at the start of every report
HOW_TO_READ = [
    _(
        "This report is a first look at a location, built from free public data: satellite "
        "images, open maps and global models. It is not a land title search, a survey or a "
        "valuation."
    ),
    _(
        "Each finding says what the data suggests. Data can be coarse, incomplete or out of "
        "date: more detailed data or a visit to the site may show something different."
    ),
    _(
        "Use it to decide what to check, and always confirm on the ground, with a sworn "
        "surveyor (géomètre), the land registry and the commune, before paying anything."
    ),
]

MODULE_ORDER = [module for _key, _title, modules in SECTIONS for module in modules]
# Modules whose two maps show the same area and read best side by side in the PDF.
PAIRED_MAPS = {"location", "demographics", "access"}


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


def limits_for(key):
    return str(LIMITS.get(key, ""))


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
