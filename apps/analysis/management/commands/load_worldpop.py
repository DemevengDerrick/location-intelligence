from django.core.management.base import BaseCommand

from apps.analysis import worldpop


class Command(BaseCommand):
    help = (
        "Download the WorldPop rasters for Cameroon: R2025A age-sex (2015, 2020, 2025, 2030) "
        "and Global1 totals (2000, 2005, 2010)."
    )

    def add_arguments(self, parser):
        years = worldpop.YEARS + worldpop.HISTORY_YEARS
        parser.add_argument("--year", type=int, action="append", choices=sorted(years))

    def handle(self, *args, year=None, **options):
        years = year or worldpop.YEARS + worldpop.HISTORY_YEARS
        history = [y for y in years if y in worldpop.HISTORY_YEARS]
        worldpop.load([y for y in years if y in worldpop.YEARS], log=self.stdout.write)
        worldpop.load_history(history, log=self.stdout.write)
        self.stdout.write(
            self.style.SUCCESS(
                f"Years available: {worldpop.available_years()}; "
                f"{worldpop.HISTORY_RELEASE} totals: {worldpop.available_history_years()}"
            )
        )
