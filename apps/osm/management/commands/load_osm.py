from django.conf import settings
from django.core.management.base import BaseCommand

from apps.osm import loader


class Command(BaseCommand):
    help = "Download the Cameroon OpenStreetMap extract and load it as the active OSM import."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="Load this .osm.pbf instead of downloading")
        parser.add_argument("--url", default=None, help="Extract URL (default OSM_EXTRACT_URL)")

    def handle(self, *args, file=None, url=None, **options):
        if file:
            path, source = file, file
        else:
            source = url or settings.OSM_EXTRACT_URL
            self.stdout.write(f"Downloading {source} ...")
            path = loader.download(source)
        self.stdout.write(f"Loading {path} ...")
        osm_import = loader.load(path, source_url=source)
        self.stdout.write(
            self.style.SUCCESS(f"OSM data as of {osm_import.data_timestamp}: {osm_import.counts}")
        )
