"""Flood and water: finding templates, dataset licences and thresholds."""

from django.db import migrations

TEMPLATES = {
    ("flood", "green"): (
        "Aucune rivière, zone humide ou zone inondable ne touche la parcelle. {nearest}",
        "No river, wetland or flood zone affects the parcel. {nearest}",
    ),
    ("flood", "amber"): (
        "La parcelle est proche de l'eau ou d'une zone inondable : {reasons}. Vérifiez le terrain "
        "après de fortes pluies et interrogez les voisins sur les inondations passées.",
        "The parcel is close to water or a flood zone: {reasons}. Check the ground after heavy "
        "rain and ask neighbours about past flooding.",
    ),
    ("flood", "red"): (
        "La parcelle est exposée aux inondations : {reasons}. N'achetez pas sans avoir vérifié sur "
        "place le comportement du terrain en saison des pluies.",
        "The parcel is exposed to flooding: {reasons}. Do not buy without checking on site how "
        "the land behaves in the rainy season.",
    ),
    ("flood", "grey"): (
        "L'exposition aux inondations n'a pas pu être évaluée.",
        "Flood exposure could not be assessed.",
    ),
}

DATASETS = [
    {
        "slug": "jrc-gsw",
        "name": "JRC Global Surface Water (occurrence)",
        "provider": "European Commission Joint Research Centre / Google",
        "version": "v1.4 (1984–2021)",
        "licence": "Free of charge, without restriction of use (Copernicus programme); "
        "citation required",
        "attribution": "Pekel, J.-F., Cottam, A., Gorelick, N., Belward, A. S. (2016). "
        "High-resolution mapping of global surface water and its long-term changes. Nature 540, "
        "418–422. Source: EC JRC/Google.",
        "url": "https://global-surface-water.appspot.com/",
        "commercial_use_allowed": True,
    },
    {
        "slug": "jrc-flood-hazard",
        "name": "Global river flood hazard maps (Copernicus EMS / GloFAS)",
        "provider": "European Commission Joint Research Centre, Copernicus Emergency "
        "Management Service",
        "version": "v2.1.2, 1-in-100-year return period, ~90 m",
        "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
        "attribution": "© European Union, Copernicus Emergency Management Service. Global river "
        "flood hazard maps (JRC). Changes: resampled to the parcel's elevation grid.",
        "url": "https://data.jrc.ec.europa.eu/collection/id-0054",
        "commercial_use_allowed": True,
    },
    {
        "slug": "osm-water",
        "name": "OpenStreetMap waterways, water bodies and wetlands",
        "provider": "OpenStreetMap contributors, via the Overpass API",
        "version": "",
        "licence": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors, available under the Open Database License.",
        "url": "https://www.openstreetmap.org/copyright",
        "commercial_use_allowed": True,
    },
]

THRESHOLDS = {
    "gsw_water_pct": 50,
    "water_seen_red_pct": 10,
    "flood_share_red_pct": 10,
    "height_above_water_amber_m": 3,
    "water_distance_amber_m": 100,
    "flood_zone_amber_m": 200,
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
    dependencies = [("analysis", "0006_vegetated_or_not")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
