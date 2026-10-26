from django.core.management.base import BaseCommand

from apps.analysis.providers import GhslBuiltSurface, GhslPopulation


class Command(BaseCommand):
    help = (
        "Download the GHSL tiles covering Cameroon: built-up surface (1975, 1990, 2000, 2010, "
        "2020) and population (2000–2030 every 5 years)."
    )

    def handle(self, *args, **options):
        GhslBuiltSurface().download(log=self.stdout.write)
        GhslPopulation().download(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("GHSL tiles ready."))
