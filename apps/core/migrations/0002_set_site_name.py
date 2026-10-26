from urllib.parse import urlparse

from django.conf import settings
from django.db import migrations


def set_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": urlparse(settings.SITE_URL).netloc, "name": settings.SITE_NAME},
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(set_site, migrations.RunPython.noop)]
