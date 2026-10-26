from django.db import migrations


def seed(apps, schema_editor):
    SiteSetting = apps.get_model("core", "SiteSetting")
    SiteSetting.objects.get_or_create(
        key="parcel_intake",
        defaults={
            "value": {
                "min_area_m2": 50,
                "max_area_m2": 5_000_000,
                "pin_buffer_m": 30,
                "area_difference_pct": 10,
            },
            "description": (
                "Order-form checks. Parcels outside min/max area (m²) get a warning, pin-only "
                "orders are analysed with a pin_buffer_m circle, and a difference between "
                "stated and computed area above area_difference_pct is highlighted."
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies = [("parcels", "0001_initial"), ("core", "0002_set_site_name")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
