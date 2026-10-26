"""Access and services: finding templates, dataset licence and thresholds."""

from django.db import migrations

TEMPLATES = {
    ("access", "green"): (
        "La parcelle est bien desservie : {road}. {times}",
        "The parcel is well served: {road}. {times}",
    ),
    ("access", "amber"): (
        "L'accès est à vérifier : {reasons}. {times} Vérifiez sur place comment on rejoint la "
        "parcelle, en toute saison.",
        "Access needs checking: {reasons}. {times} Check on site how the parcel is reached, in "
        "every season.",
    ),
    ("access", "red"): (
        "La parcelle n'a pas d'accès routier : {reasons}. Vérifiez sur place comment on y accède "
        "et qu'un droit de passage existe avant d'acheter.",
        "The parcel has no road access: {reasons}. Check on site how it is reached and that a "
        "right of way exists before buying.",
    ),
    ("access", "grey"): (
        "L'accès et les services n'ont pas pu être évalués.",
        "Access and services could not be assessed.",
    ),
}

DATASETS = [
    {
        "slug": "osm-roads-services",
        "name": "OpenStreetMap roads and services (Cameroon extract)",
        "provider": "OpenStreetMap contributors, via Geofabrik; routes by Valhalla",
        "version": "",
        "licence": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors, available under the Open Database "
        "License. Travel times and areas computed with the Valhalla routing engine.",
        "url": "https://www.openstreetmap.org/copyright",
        "commercial_use_allowed": True,
    },
]

THRESHOLDS = {
    "road_touch_m": 10,
    "road_red_m": 500,
    "paved_road_amber_m": 2000,
    "health_drive_amber_min": 30,
    "school_walk_amber_min": 30,
    "service_search_m": 20000,
}


def seed(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    Dataset = apps.get_model("core", "Dataset")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    for dataset in DATASETS:
        Dataset.objects.update_or_create(slug=dataset["slug"], defaults=dataset)
    setting = SiteSetting.objects.filter(key="analysis_thresholds").first()
    if setting is not None:
        setting.value = {**THRESHOLDS, **(setting.value or {})}
        setting.save()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0007_seed_flood")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
