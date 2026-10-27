"""Dataset entry for the official land-use layers of the Forest Atlas of Cameroon."""

from django.db import migrations

DATASET = {
    "slug": "forest-atlas",
    "name": "Forest Atlas of Cameroon: protected areas, forest estate and concessions",
    "provider": "Ministry of Forests and Wildlife (MINFOF) with the World Resources Institute",
    "version": "",
    "licence": "Public open data portal; reuse with attribution to MINFOF and WRI",
    "attribution": "Atlas forestier du Cameroun, MINFOF/WRI (cmr-data.forest-atlas.org): "
    "protected areas, forest reserves, production and council forests, community forests, "
    "hunting zones and agro-industrial plantations.",
    "url": "https://cmr-data.forest-atlas.org/",
    "commercial_use_allowed": True,
}


def seed(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    Dataset.objects.update_or_create(slug=DATASET["slug"], defaults=DATASET)


class Migration(migrations.Migration):
    dependencies = [("analysis", "0015_seed_area_signals"), ("core", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
