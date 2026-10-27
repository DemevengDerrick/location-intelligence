"""Offline helpers for area-signals tests: an HTTP client answering from a dict, an RSS
builder and a fake extractor."""

from email.utils import format_datetime

import httpx

from .extraction import ExtractedIncident, Extraction


def rss(*items):
    """An RSS 2.0 feed; each item is (title, link, description, datetime)."""
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<description><![CDATA[<p>{description}</p>]]></description>"
        f"<pubDate>{format_datetime(when)}</pubDate></item>"
        for title, link, description, when in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{entries}</channel></rss>'


class Web:
    """httpx client whose answers come from `routes`: {substring of URL: response}, where a
    response is a str (200 body), an int (status) or a callable(request). robots.txt is
    allowed unless routed. Every requested URL is kept in `requested`."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requested = []

    def handler(self, request):
        url = str(request.url)
        self.requested.append(url)
        for key, answer in self.routes.items():
            if key in url:
                if callable(answer):
                    return answer(request)
                if isinstance(answer, int):
                    return httpx.Response(answer, text="")
                if isinstance(answer, dict):
                    return httpx.Response(200, json=answer)
                return httpx.Response(200, text=answer)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        return httpx.Response(200, text=rss())

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=True)


class FakeExtractor:
    def __init__(self, incidents=None, error=None):
        self.incidents = incidents if incidents is not None else []
        self.error = error
        self.seen = []

    def extract(self, item):
        self.seen.append(item.pk)
        if self.error:
            raise self.error
        return Extraction(incidents=[ExtractedIncident(**i) for i in self.incidents])


def extracted(**overrides):
    values = {
        "incident_type": "demolition",
        "place_names": ["Bonamoussadi"],
        "event_date": "2025-03-14",
        "summary_fr": "Des maisons ont été démolies selon la commune.",
        "summary_en": "Houses were reportedly demolished by the council.",
        "is_official_act": False,
        "confidence": 0.8,
    }
    return {**values, **overrides}
