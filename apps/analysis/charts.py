"""Charts as Vega-Lite specifications (FR-66, FR-67).

One spec per chart drives both outputs: rendered to SVG for the PDF here, and handed to
vega-embed on the portal. Colours and fonts come from `style`, never from the chart itself.
Every chart has a title stating the finding, labelled axes with units, and a source line.
"""

import vl_convert

from . import style

SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
LOCALES = {"fr": "fr-FR", "en": "en-US"}


def config():
    return {
        "font": style.FONT,
        "background": "#FFFFFF",
        "view": {"stroke": None},
        "title": {
            "fontSize": 12,
            "anchor": "start",
            "fontWeight": "bold",
            "subtitleColor": "#444444",
        },
        "axis": {"labelFontSize": 10, "titleFontSize": 10, "grid": True, "gridColor": "#E5E5E5"},
        "legend": {"labelFontSize": 10, "titleFontSize": 10, "orient": "bottom"},
        "range": {"category": list(style.CHART_CATEGORY)},
    }


def spec(*, title, source, width=420, height=200, **body):
    """A complete spec: `title` states the finding, `source` names the data and its date."""
    return {
        "$schema": SCHEMA,
        "title": {"text": title, "subtitle": source, "subtitleFontSize": 9, "subtitlePadding": 4},
        "width": width,
        "height": height,
        "config": config(),
        **body,
    }


def series_scale(series):
    """A colour scale mapping named series to the shared palette (style.SERIES)."""
    return {"domain": list(series), "range": [style.SERIES[name] for name in series]}


def to_svg(chart_spec, language):
    return vl_convert.vegalite_to_svg(chart_spec, format_locale=LOCALES.get(language, "fr-FR"))
