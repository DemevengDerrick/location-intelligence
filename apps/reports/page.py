"""The interactive report page (FR-19): the latest delivered version, in the reader's language,
with MapLibre layers and Vega-Lite charts built from the same stored results as the PDF
(FR-59, FR-66). Used by the customer portal and by shared links."""

import json

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import Http404
from django.utils import translation
from django.utils.translation import gettext as _

from apps.analysis import style
from apps.analysis.modules import MODULES
from apps.core.maps import basemap_url
from apps.core.models import Dataset
from apps.pages.models import Page, PageSlug

from .structure import in_report_order, sections_for, statement_for

HIDDEN_CHART_FIELDS = {"order"}  # helper fields in chart data, not shown in data tables


def latest_versions(report):
    """{language: ReportVersion} for the newest delivered version, or Http404."""
    versions = list(report.versions.order_by("-number"))
    if not versions:
        raise Http404("No delivered version")
    newest = versions[0].number
    return {v.language: v for v in versions if v.number == newest}


def _pick(value, language):
    """A {"fr": ..., "en": ...} value in the reader's language; other values unchanged."""
    if isinstance(value, dict) and set(value) <= {"fr", "en"} and value:
        return value.get(language) or value.get("fr") or value.get("en")
    return value


def _signed(key):
    return default_storage.url(key) if key else ""


def map_key(stored, language):
    """A stored static map: {"fr": key, "en": key}, or one key in drafts made before maps
    were drawn per language."""
    if isinstance(stored, str):
        return stored
    return (stored or {}).get(language) or (stored or {}).get("en") or ""


def _layer_for_browser(layer, language):
    """Pick the reader's language everywhere and swap storage keys for signed URLs."""
    out = {k: v for k, v in layer.items() if k not in {"image", "title", "legend", "hover"}}
    out["title"] = _pick(layer.get("title"), language)
    out["legend"] = [
        {**entry, "label": _pick(entry.get("label"), language)} for entry in layer.get("legend", [])
    ]
    if layer.get("type") == "image":
        out["url"] = _signed(layer.get("image"))
        hover = layer.get("hover")
        if hover:
            out["hover"] = {
                "grid": hover["grid"],
                "unit": _pick(hover.get("unit"), language),
                "categories": {
                    k: _pick(v, language) for k, v in (hover.get("categories") or {}).items()
                },
            }
    else:
        out["hover"] = [
            {"property": h["property"], "label": _pick(h["label"], language)}
            for h in layer.get("hover", [])
        ]
        data = layer.get("data") or {"type": "FeatureCollection", "features": []}
        out["data"] = {
            "type": "FeatureCollection",
            "features": [
                {
                    **feature,
                    "properties": {
                        k: _pick(v, language) for k, v in (feature.get("properties") or {}).items()
                    },
                }
                for feature in data.get("features", [])
            ],
        }
    return out


def _chart_table(chart_spec):
    """The chart's data as a table, for screen readers and readers without JavaScript."""
    values = (chart_spec.get("data") or {}).get("values") or []
    if not values:
        return None
    columns = [c for c in values[0] if c not in HIDDEN_CHART_FIELDS]
    return {"columns": columns, "rows": [[row.get(c, "") for c in columns] for row in values]}


def _charts(finding, language):
    module = finding["module"]
    rendered = []
    for name, chart in (finding.get("charts") or {}).items():
        if "reason" in chart:
            rendered.append({"name": name, "reason": _pick(chart["reason"], language)})
        elif "table" in chart:
            rendered.append({"name": name, "table": _pick(chart["table"], language)})
        elif chart.get(language):
            chart_spec = chart[language]
            title = chart_spec.get("title", {})
            rendered.append(
                {
                    "name": name,
                    "script_id": f"vega-{module}-{name}",
                    "spec": chart_spec,
                    "title": title.get("text", "") if isinstance(title, dict) else title,
                    "data": _chart_table(chart_spec),
                }
            )
    return rendered


def finding_for_browser(finding, language, parcel_geojson, element_id):
    rating = finding["rating"]
    module = MODULES.get(finding["module"])
    layers = [_layer_for_browser(layer, language) for layer in finding.get("layers") or []]
    return {
        "module": finding["module"],
        "title": str(module.title) if module else finding["module"],
        "rating": rating,
        "colour": style.RATING_COLOURS[rating],
        "icon": style.RATING_ICONS[rating],
        "word": str(style.RATING_WORDS[rating]),
        "sentence": _pick(finding["text"], language),
        "key_figure": _pick(finding.get("key") or {}, language) or "",
        "unavailable": finding.get("unavailable"),
        "overridden": rating != finding.get("computed_rating") and finding.get("override_reason"),
        "override_reason": finding.get("override_reason", ""),
        "static_maps": [_signed(map_key(m, language)) for m in finding["maps"].values()],
        "charts": _charts(finding, language),
        "map_id": element_id,
        "map_config_id": f"{element_id}-config",
        "map": {
            "basemapUrl": basemap_url(),
            "attribution": settings.BASEMAP_ATTRIBUTION,
            "parcel": parcel_geojson,
            "layers": layers,
            "language": language,
            "labels": {
                "compare": _("Compare two years"),
                "left": _("Left"),
                "right": _("Right"),
                "divider": _("Divider position"),
                "colon": _(":"),
            },
        }
        if layers
        else None,
    }


def page_context(report, language):
    versions = latest_versions(report)
    version = versions.get(language) or next(iter(versions.values()))
    content = version.content
    order = report.order
    parcel = order.parcels.first()
    parcel_geojson = json.loads(parcel.geometry.geojson) if parcel and parcel.geometry else None
    visible = in_report_order(f for f in content.get("findings", []) if not f.get("hidden"))
    findings = [
        finding_for_browser(f, language, parcel_geojson, f"map-{f['module']}") for f in visible
    ]
    by_module = {f["module"]: f for f in findings}
    with translation.override(language):
        sections = [
            {"key": key, "title": str(title), "statement": statement_for(key),
             "findings": [by_module[m] for m in modules if m in by_module]}
            for key, title, modules in sections_for(order)
        ]  # fmt: skip
    dataset_slugs = {slug for f in visible for slug in f.get("datasets", {})}
    return {
        "report": report,
        "order": order,
        "parcel": parcel,
        "version": version,
        "versions": versions,
        "summary": findings,
        "sections": sections,
        "note": _pick(content.get("note") or {}, language),
        "approximate": content.get("approximate"),
        "datasets": Dataset.objects.filter(slug__in=dataset_slugs).order_by("name"),
        "disclaimer": Page.objects.filter(slug=PageSlug.DISCLAIMER).first(),
    }
