"""PDF reports with WeasyPrint (A4, one template for both languages)."""

import base64

import segno
from django.conf import settings
from django.core.files.storage import default_storage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation

from apps.analysis import charts, style
from apps.analysis.modules import MODULES
from apps.core.models import Dataset
from apps.pages.models import Page, PageSlug

from .structure import PAIRED_MAPS, in_report_order, requester, sections_for, statement_for


def _svg_image(svg):
    """An SVG as an <img> data URI: still vector in the PDF, and drawn by WeasyPrint's SVG
    renderer (inline SVG would be parsed as HTML CSS and spam warnings)."""
    if not svg:
        return ""
    if isinstance(svg, str):
        svg = svg.encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


def _stored_svg(key):
    if not key:
        return ""
    with default_storage.open(key) as handle:
        return _svg_image(handle.read())


def _charts(finding, language):
    """Each chart as an SVG image, or the reason it is missing (FR-68)."""
    rendered = []
    for chart in finding.get("charts", {}).values():
        if "reason" in chart:
            rendered.append({"reason": chart["reason"].get(language, "")})
        elif "table" in chart:  # {"caption", "columns", "rows"} per language
            rendered.append({"table": chart["table"].get(language)})
        elif chart.get(language):
            rendered.append({"src": _svg_image(charts.to_svg(chart[language], language))})
    return rendered


def verify_url(report, language):
    with translation.override(language):
        return settings.SITE_URL + reverse("reports:verify", args=[report.reference])


def _finding_context(finding, language):
    rating = finding["rating"]
    map_srcs = [_stored_svg(by_language.get(language)) for by_language in finding["maps"].values()]
    pair = [src for src in map_srcs if src] if finding["module"] in PAIRED_MAPS else []
    return {
        **finding,
        "title": str(MODULES[finding["module"]].title) if finding["module"] in MODULES else "",
        "sentence": finding["text"][language],
        "key_figure": finding.get("key", {}).get(language, ""),
        "colour": style.RATING_COLOURS[rating],
        "icon": style.RATING_ICONS[rating],
        "word": str(style.RATING_WORDS[rating]),
        "map_srcs": map_srcs,
        "map_pair": pair if len(pair) == 2 else [],
        "charts": _charts(finding, language),
    }


def render_pdf(report, content, language, number):
    order = report.order
    parcel = order.parcels.first()
    visible = in_report_order(f for f in content["findings"] if not f["hidden"])
    with translation.override(language):
        findings = [_finding_context(f, language) for f in visible]
        by_module = {f["module"]: f for f in findings}
        sections = [
            {
                "title": str(title),
                "statement": statement_for(key),
                "findings": [by_module[m] for m in modules if m in by_module],
            }
            for key, title, modules in sections_for(order)
        ]
        dataset_slugs = {slug for f in findings for slug in f["datasets"]}
        url = verify_url(report, language)
        html = render_to_string(
            "reports/pdf.html",
            {
                "report": report,
                "order": order,
                "parcel": parcel,
                "requester": requester(order),
                "number": number,
                "language": language,
                "scorecard": findings,
                "sections": sections,
                "note": content["note"].get(language, ""),
                "approximate": content.get("approximate"),
                "datasets": Dataset.objects.filter(slug__in=dataset_slugs).order_by("name"),
                "disclaimer": Page.objects.filter(slug=PageSlug.DISCLAIMER).first(),
                "verify_url": url,
                "qr_src": segno.make(url, error="m").svg_data_uri(scale=2, border=0),
                "generated_at": timezone.now(),
                "site_name": settings.SITE_NAME,
            },
        )
    from weasyprint import HTML  # heavy import; only needed when rendering

    return HTML(string=html, base_url=settings.SITE_URL).write_pdf()
