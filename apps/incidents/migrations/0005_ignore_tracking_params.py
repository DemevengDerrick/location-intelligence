"""Recompute item hashes without utm_* tracking parameters and merge the duplicates this
reveals: the oldest item keeps the incidents and area searches of the others."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.db import migrations

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid)$", re.IGNORECASE)


def canonical_hash(url):
    parts = urlsplit(url.strip())
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode([(k, v) for k, v in pairs if not TRACKING_PARAMS.match(k)])
    url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, query, ""))
    return hashlib.sha256(url.encode()).hexdigest()


def rehash(apps, schema_editor):
    SourceItem = apps.get_model("incidents", "SourceItem")
    IncidentSource = apps.get_model("incidents", "IncidentSource")
    AreaSearch = apps.get_model("incidents", "AreaSearch")
    kept = {}
    for item in SourceItem.objects.order_by("pk"):
        digest = canonical_hash(item.url)
        keeper = kept.setdefault(digest, item)
        if keeper.pk == item.pk:
            continue
        for link in IncidentSource.objects.filter(source_item=item):
            if not IncidentSource.objects.filter(
                incident_id=link.incident_id, source_item=keeper
            ).exists():
                IncidentSource.objects.create(incident_id=link.incident_id, source_item=keeper)
        for search in AreaSearch.objects.filter(items=item):
            search.items.add(keeper)
        item.delete()
    for digest, item in kept.items():
        if item.content_hash != digest:
            SourceItem.objects.filter(pk=item.pk).update(content_hash=digest)


class Migration(migrations.Migration):
    dependencies = [("incidents", "0004_more_outlets")]

    operations = [migrations.RunPython(rehash, migrations.RunPython.noop)]
