"""FR-23: an analyst adds an item by pasting a URL or uploading a PDF notice."""

import hashlib
import ipaddress
import re
import socket
from datetime import datetime, time
from urllib.parse import urlsplit

import httpx
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

from . import collectors
from .models import Source, SourceType

MAX_PAGE_BYTES = 5 * 1024 * 1024


class ManualItemError(Exception):
    pass


def _manual_source():
    source, _created = Source.objects.get_or_create(
        source_type=SourceType.MANUAL,
        url="https://manual.invalid/",
        defaults={"name": _("Added by an analyst"), "language": "fr", "is_active": False},
    )
    return source


def public_address(url):
    """True if the URL's host resolves only to public addresses (no internal services)."""
    host = urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    return bool(addresses) and all(a.is_global for a in addresses)


def page_text(html):
    """Title and readable text of an HTML page (scripts, styles and navigation dropped)."""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    body = re.sub(
        r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I
    )
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", body, re.S | re.I)
    text = " ".join(strip_tags(p) for p in paragraphs) or strip_tags(body)
    return (strip_tags(title.group(1)).strip() if title else ""), " ".join(text.split())


def pdf_text(data):
    import pypdfium2

    document = pypdfium2.PdfDocument(data)
    try:
        return " ".join(page.get_textpage().get_text_range() for page in document)
    finally:
        document.close()


def add_item(url="", pdf=None, title="", outlet="", published_at=None):
    """Store the item (deduplicated by URL); returns (item, created)."""
    text = ""
    if pdf is not None:
        try:
            text = pdf_text(pdf.read())
        except Exception as exc:  # pypdfium2 raises its own error types
            raise ManualItemError(_("The PDF could not be read.")) from exc
        url = url or f"https://manual.invalid/{hashlib.sha256(text.encode()).hexdigest()}"
        title = title or pdf.name
    elif url:
        if not url.startswith(("http://", "https://")) or not public_address(url):
            raise ManualItemError(_("This address cannot be fetched."))
        http = collectors.client()
        if not collectors.allowed_by_robots(url, http):
            raise ManualItemError(
                _("This site's robots.txt does not allow us to fetch the page. Upload it as a PDF.")
            )
        try:
            response = http.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ManualItemError(_("The page could not be fetched: %(e)s") % {"e": exc}) from exc
        page_title, text = page_text(response.text[:MAX_PAGE_BYTES])
        title = title or page_title or url
    entry = {
        "url": url,
        "title": title,
        "description": text,
        "outlet": outlet or urlsplit(url).netloc,
        "published_at": timezone.make_aware(datetime.combine(published_at, time(12)))
        if published_at
        else None,
    }
    return collectors.store(entry, _manual_source())
