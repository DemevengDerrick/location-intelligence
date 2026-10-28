"""PDF reports with WeasyPrint (A4, one template for both languages)."""

import base64

import segno
from django.conf import settings
from django.core.files.storage import default_storage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from apps.analysis import charts, style
from apps.analysis.modules import MODULES
from apps.core.models import Dataset
from apps.pages.models import Page, PageSlug

from . import cover as cover_art
from .structure import (
    HOW_TO_READ,
    PAIRED_MAPS,
    in_report_order,
    limits_for,
    requester,
    sections_for,
    statement_for,
)


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


FONTS_DIR = settings.BASE_DIR / "static" / "fonts" / "outfit"
# Cover title colours, word by word: warm and cool tints that read on deep blue
TITLE_COLOURS = ["#F4B183", "#56B4E9", "#E69F00", "#9FD3F0", "#CC79A7"]


def _cover(report):
    seed = str(report.reference)
    title = str(_("Location intelligence report")).split()
    return {
        "title": [(word, TITLE_COLOURS[i % len(TITLE_COLOURS)]) for i, word in enumerate(title)],
        "contours": _svg_image(cover_art.contours_svg(seed)),
        "back_contours": _svg_image(cover_art.contours_svg(f"back-{seed}", rings=34)),
        "stripe": cover_art.stripe(seed),
    }


def _logo(name="logo-liod-header-light.svg"):
    """A logo as a data URI (vector in the PDF): the light one for the blue covers, the dark
    one for the page footers. Same wide design as the website header."""
    path = settings.BASE_DIR / "static" / "img" / name
    return _svg_image(path.read_bytes())


def _contact():
    website = settings.REPORT_CONTACT_WEBSITE
    return {
        "email": settings.REPORT_CONTACT_EMAIL,
        "website": website,
        "website_label": website.split("://", 1)[-1].rstrip("/"),
        "qr": segno.make(website, error="m").svg_data_uri(scale=2, border=0) if website else "",
    }


def render_pdf(report, content, language, number, sample=False):
    """The report as PDF bytes. `sample` renders it as a public sample: the requester is
    replaced by a placeholder and the cover says it is an example."""
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
                "limits": limits_for(key),
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
                "requester": {"name": str(_("Sample client")), "intended_use": ""}
                if sample
                else requester(order),
                "sample": sample,
                "cover": _cover(report),
                "contact": _contact(),
                "fonts_url": FONTS_DIR.as_uri(),
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
                "how_to_read": [str(line) for line in HOW_TO_READ],
                "logo_src": _logo(),
                "footer_logo_src": _logo("logo-liod-header.svg"),
            },
        )
    from weasyprint import HTML  # heavy import; only needed when rendering
    from weasyprint.text.fonts import FontConfiguration

    fonts = FontConfiguration()  # needed for the @font-face heading font
    return HTML(string=html, base_url=settings.SITE_URL).write_pdf(font_config=fonts)
