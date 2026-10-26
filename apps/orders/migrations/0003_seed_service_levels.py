from django.db import migrations


def seed(apps, schema_editor):
    SiteSetting = apps.get_model("core", "SiteSetting")
    SiteSetting.objects.get_or_create(
        key="service_levels",
        defaults={
            "value": {"desk": 3},
            "description": (
                "Service-level targets: business days (Monday to Friday) from payment to "
                "delivery, per tier. Open orders past their target are flagged in the order "
                "queue. A tier without a number (e.g. field) has no target."
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0002_order_terms_accepted_at_order_terms_version_and_more"),
        ("core", "0002_set_site_name"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
