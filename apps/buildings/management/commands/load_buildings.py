from django.core.management.base import BaseCommand

from apps.buildings import loader


class Command(BaseCommand):
    help = (
        "Download the Google Open Buildings v3 tiles covering Cameroon (about 6.6 GB) and load "
        "the buildings inside Cameroon as the active building release."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", action="append", help="Load this .csv.gz instead of downloading (repeatable)"
        )

    def handle(self, *args, file=None, **options):
        paths = file or loader.download(log=self.stdout.write)
        source = ", ".join(file) if file else loader.tile_url("{tile}")
        release = loader.load(paths, source_url=source, log=self.stdout.write)
        self.stdout.write(
            self.style.SUCCESS(f"Google Open Buildings {release.version}: {release.count:,} loaded")
        )
