from django.core.management.base import BaseCommand

from apps.analysis import worldpop


class Command(BaseCommand):
    help = "Download the WorldPop R2025A age-sex rasters for Cameroon (2020, 2025, 2030)."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, action="append", choices=worldpop.YEARS)

    def handle(self, *args, year=None, **options):
        worldpop.load(year or worldpop.YEARS, log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"Years available: {worldpop.available_years()}"))
