"""Collect candidate news items (FR-22..FR-25): outlet RSS feeds, outlet search feeds and the
GDELT DOC API. Every fetch respects robots.txt (FR-24); only items that mention a land-issue
keyword are stored, and their text stays private (FR-25)."""

import hashlib
import re
import time
import unicodedata
import urllib.robotparser
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlsplit, urlunsplit

import httpx
from defusedxml import ElementTree
from django.core.cache import cache
from django.utils import timezone
from django.utils.html import strip_tags

from .models import SourceItem

USER_AGENT = "LandDueDiligenceBot/0.1 (+https://github.com/DemevengDerrick/location-intelligence)"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_INTERVAL_S = 6  # GDELT asks for at most one request every 5 seconds
GDELT_COOLDOWN_S = 600  # after a 429, leave GDELT alone for a while


class GdeltBusy(ValueError):
    """GDELT is throttling us; the search is skipped and retried by a later order."""


GDELT_LANGUAGES = {"French": "fr", "English": "en"}
MAX_TEXT = 4000  # private text kept per item (title + feed description), enough to extract


def client():
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30, connect=10),
        headers={"User-Agent": USER_AGENT},
    )


def normalise(text):
    """Lower-case, without accents or punctuation, single-spaced: for keyword matching."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def contains_any(text, phrases):
    """Whole-word match of any phrase in the text (both normalised)."""
    haystack = f" {normalise(text)} "
    return any(f" {normalise(p)} " in haystack for p in phrases if normalise(p))


def canonical_url(url):
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


def content_hash(url):
    return hashlib.sha256(canonical_url(url).encode()).hexdigest()


# --- robots.txt (FR-24) -----------------------------------------------------------------


def allowed_by_robots(url, http=None):
    """True if the site's robots.txt lets our user agent fetch this URL (cached a day)."""
    parts = urlsplit(url)
    key = f"robots:{parts.scheme}://{parts.netloc}"
    lines = cache.get(key)
    if lines is None:
        http = http or client()
        try:
            response = http.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
            if response.status_code in (401, 403):
                lines = ["User-agent: *", "Disallow: /"]
            elif response.status_code >= 400:
                lines = []  # no robots.txt: everything allowed
            else:
                lines = response.text.splitlines()
        except httpx.HTTPError:
            return False  # can't tell: don't fetch
        cache.set(key, lines, 60 * 60 * 24)
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(lines)
    return parser.can_fetch(USER_AGENT, url)


# --- Feeds --------------------------------------------------------------------------------


def _text(element, *names):
    for name in names:
        found = element.find(name)
        if found is not None and (found.text or "").strip():
            return found.text.strip()
    return ""


def _date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)  # RSS
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_feed(xml_text):
    """Entries of an RSS 2.0 or Atom feed: dicts with url, title, description, published_at."""
    root = ElementTree.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    atom = "{http://www.w3.org/2005/Atom}"
    entries = []
    for item in root.iter("item"):
        entries.append(
            {
                "url": _text(item, "link", "guid"),
                "title": _text(item, "title"),
                "description": _text(
                    item, "description", "{http://purl.org/rss/1.0/modules/content/}encoded"
                ),
                "published_at": _date(
                    _text(item, "pubDate", "{http://purl.org/dc/elements/1.1/}date")
                ),
            }
        )
    for entry in root.iter(f"{atom}entry"):
        link = entry.find(f"{atom}link")
        entries.append(
            {
                "url": link.get("href", "") if link is not None else "",
                "title": _text(entry, f"{atom}title"),
                "description": _text(entry, f"{atom}summary", f"{atom}content"),
                "published_at": _date(_text(entry, f"{atom}published", f"{atom}updated")),
            }
        )
    for entry in entries:
        entry["title"] = " ".join(strip_tags(entry["title"]).split())
        entry["description"] = " ".join(strip_tags(entry["description"]).split())
    return [e for e in entries if e["url"].startswith(("http://", "https://")) and e["title"]]


def fetch_feed(url, http=None):
    """Entries of a feed, or [] when robots.txt forbids it."""
    http = http or client()
    if not allowed_by_robots(url, http):
        return []
    response = http.get(url)
    response.raise_for_status()
    return parse_feed(response.content)


def search_feed_url(source, query):
    return source.search_url.replace("{query}", quote_plus(query))


# --- GDELT --------------------------------------------------------------------------------


def _wait_for_gdelt_slot():
    """Space GDELT requests across all workers (Redis-backed cache)."""
    while True:
        if cache.add("gdelt:slot", 1, timeout=GDELT_INTERVAL_S):
            return
        time.sleep(1)


def gdelt_query(place_names, keywords):
    """A GDELT DOC query: one of the place names and one of the keywords."""

    def term(text):
        return f'"{text}"' if " " in text or "-" in text else text

    places = sorted({n for n in place_names if len(n) >= 3})
    words = [k for k in dict.fromkeys(keywords) if len(k) >= 4]
    place_part = term(places[0]) if len(places) == 1 else f"({' OR '.join(map(term, places))})"
    return f"{place_part} ({' OR '.join(map(term, words))})"


def gdelt_search(query, timespan="3months", max_records=75, http=None):
    """Articles from the GDELT DOC API: dicts like parse_feed's, plus outlet and language."""
    http = http or client()
    if cache.get("gdelt:cooldown"):
        raise GdeltBusy("GDELT asked us to slow down; skipped for now")
    _wait_for_gdelt_slot()
    try:
        response = http.get(
            GDELT_URL,
            params={
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": max_records,
                "timespan": timespan,
                "sort": "datedesc",
            },
        )
    finally:
        cache.set("gdelt:slot", 1, timeout=GDELT_INTERVAL_S)  # the gap counts from the answer
    if response.status_code == 429:
        cache.set("gdelt:cooldown", 1, timeout=GDELT_COOLDOWN_S)
        raise GdeltBusy("GDELT answered 429 Too Many Requests")
    response.raise_for_status()
    try:
        articles = response.json().get("articles", [])
    except ValueError as exc:  # GDELT answers query errors in plain text
        raise ValueError(f"GDELT: {response.text[:200]}") from exc
    return [
        {
            "url": a.get("url", ""),
            "title": a.get("title", ""),
            "description": "",
            "published_at": _gdelt_date(a.get("seendate")),
            "outlet": a.get("domain", ""),
            "language": GDELT_LANGUAGES.get(a.get("language"), ""),
        }
        for a in articles
        if a.get("url", "").startswith(("http://", "https://"))
    ]


def _gdelt_date(value):
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


# --- Storing ------------------------------------------------------------------------------


def store(entry, source=None):
    """Save an entry as a SourceItem (deduplicated by URL); returns (item, created)."""
    if urlsplit(entry["url"]).scheme.lower() not in ("http", "https"):  # links in reports
        raise ValueError(f"Not a web address: {entry['url'][:100]}")
    outlet = entry.get("outlet") or (source.name if source else urlsplit(entry["url"]).netloc)
    text = entry["title"]
    if entry.get("description"):
        text = f"{text}\n\n{entry['description']}"
    return SourceItem.objects.get_or_create(
        content_hash=content_hash(entry["url"]),
        defaults={
            "source": source,
            "url": entry["url"][:1000],
            "title": entry["title"][:500],
            "outlet": outlet[:200],
            "published_at": entry.get("published_at"),
            "language": entry.get("language") or (source.language if source else ""),
            "private_text": text[:MAX_TEXT],
        },
    )


def relevant(entry, keywords):
    return contains_any(f"{entry['title']} {entry.get('description', '')}", keywords)


def collect_source(source, keywords, http=None):
    """FR-22 daily collection from one outlet feed: store the land-related items."""
    entries = fetch_feed(source.url, http)
    created = 0
    for entry in entries:
        if relevant(entry, keywords):
            created += store(entry, source)[1]
    source.last_crawled_at = timezone.now()
    source.save(update_fields=["last_crawled_at", "updated_at"])
    return created
