from django.core.management.base import BaseCommand

from apps.analysis.providers import SurfaceWaterAndFloods


class Command(BaseCommand):
    help = "Download the JRC 1-in-100-year river flood depth tiles covering Cameroon."

    def handle(self, *args, **options):
        names = SurfaceWaterAndFloods().download(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(f"{len(names)} flood tiles ready."))
