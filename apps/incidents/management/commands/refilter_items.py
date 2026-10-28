"""Check collected items again against the current keyword filter (Core → Settings →
`area_signals`) and remove the ones it no longer keeps.

    manage.py refilter_items            # list what would be removed
    manage.py refilter_items --delete

Items added by hand and items an incident was made from always stay.
"""

from django.core.management.base import BaseCommand

from apps.incidents import collectors
from apps.incidents.config import signals_settings
from apps.incidents.models import SourceItem, SourceType


def entry(item):
    """The item as the collector saw it: its title and feed description."""
    description = item.private_text.partition("\n\n")[2]
    return {"title": item.title, "description": description}


def off_topic(settings=None):
    settings = settings or signals_settings()
    items = (
        SourceItem.objects.filter(incidents__isnull=True)
        .exclude(source__source_type=SourceType.MANUAL)
        .order_by("pk")
    )
    return [
        item
        for item in items
        if not collectors.relevant(entry(item), settings.keywords, settings.weak_keywords)
    ]


class Command(BaseCommand):
    help = "Remove collected items that the current keyword filter would not keep"

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Remove them (default: list)")

    def handle(self, *args, **options):
        items = off_topic()
        for item in items:
            self.stdout.write(f"{item.pk:>6}  {item.outlet[:24]:<24}  {item.title[:90]}")
        total = SourceItem.objects.count()
        if options["delete"]:
            SourceItem.objects.filter(pk__in=[i.pk for i in items]).delete()
            self.stdout.write(f"Removed {len(items)} of {total} items.")
        else:
            self.stdout.write(f"{len(items)} of {total} items would be removed (use --delete).")
