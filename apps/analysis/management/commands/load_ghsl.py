from django.core.management.base import BaseCommand

from apps.analysis.providers import GhslBuiltSurface


class Command(BaseCommand):
    help = (
        "Download the GHSL built-up tiles covering Cameroon (epochs 1975, 1990, 2000, 2010, 2020)."
    )

    def handle(self, *args, **options):
        GhslBuiltSurface().download(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("GHSL tiles ready."))
