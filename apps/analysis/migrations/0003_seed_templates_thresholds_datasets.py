"""Finding templates (FR/EN), thresholds and dataset licences for the first modules.

All of it is editable in the admin afterwards; nothing here is hard-coded in module logic.
"""

from django.db import migrations

TEMPLATES = {
    ("location", "green"): (
        "Le contour couvre {area} m², en accord avec les {stated_area} m² annoncés par le "
        "vendeur. La parcelle se trouve dans la commune de {commune} ({admin_area}).",
        "The boundary covers {area} m², in line with the {stated_area} m² stated by the seller. "
        "The parcel lies in {commune} ({admin_area}).",
    ),
    ("location", "amber"): (
        "Le contour couvre {area} m², soit {difference} % d'écart avec les {stated_area} m² "
        "annoncés par le vendeur. Faites confirmer les limites par un géomètre. La parcelle se "
        "trouve dans la commune de {commune} ({admin_area}).",
        "The boundary covers {area} m², {difference} % away from the {stated_area} m² stated by "
        "the seller. Have a surveyor confirm the boundary. The parcel lies in {commune} "
        "({admin_area}).",
    ),
    ("location", "red"): (
        "Le contour couvre {area} m², soit {difference} % d'écart avec les {stated_area} m² "
        "annoncés par le vendeur. Ne payez pas avant qu'un géomètre ait confirmé les limites. "
        "La parcelle se trouve dans la commune de {commune} ({admin_area}).",
        "The boundary covers {area} m², {difference} % away from the {stated_area} m² stated by "
        "the seller. Do not pay before a surveyor has confirmed the boundary. The parcel lies "
        "in {commune} ({admin_area}).",
    ),
    ("location", "grey"): (
        "La parcelle se trouve dans la commune de {commune} ({admin_area}). Sa "
        "superficie n'a pas pu être comparée à celle du vendeur, faute de contour exact ou de "
        "superficie annoncée.",
        "The parcel lies in {commune} ({admin_area}). Its area could not be compared "
        "with the seller's, because the exact boundary or the stated area is missing.",
    ),
    ("terrain", "green"): (
        "Le terrain est en pente douce : pente moyenne de {slope_mean}°, altitude de "
        "{elevation_min} à {elevation_max} m. La pente ne présente pas de risque d'érosion.",
        "The ground is gently sloping: average slope {slope_mean}°, elevation {elevation_min} to "
        "{elevation_max} m. Slope is not an erosion concern.",
    ),
    ("terrain", "amber"): (
        "Le terrain est en pente modérée : pente moyenne de {slope_mean}° (jusqu'à "
        "{slope_max}°), altitude de {elevation_min} à {elevation_max} m. {steep_share} % de la "
        "parcelle dépasse {threshold}°. Prévoyez le drainage et vérifiez l'érosion sur place.",
        "The ground is moderately sloping: average slope {slope_mean}° (up to {slope_max}°), "
        "elevation {elevation_min} to {elevation_max} m. {steep_share} % of the parcel is "
        "steeper than {threshold}°. Plan drainage and check for erosion on site.",
    ),
    ("terrain", "red"): (
        "Le terrain est en forte pente : pente moyenne de {slope_mean}° (jusqu'à {slope_max}°). "
        "{steep_share} % de la parcelle dépasse {threshold}°, ce qui expose à l'érosion et aux "
        "glissements. Construire peut nécessiter terrassements et murs de soutènement.",
        "The ground is steep: average slope {slope_mean}° (up to {slope_max}°). {steep_share} % "
        "of the parcel is steeper than {threshold}°, where erosion and landslides are a concern. "
        "Building may need terracing and retaining walls.",
    ),
    ("terrain", "grey"): (
        "La pente de la parcelle n'a pas pu être évaluée.",
        "The slope of the parcel could not be assessed.",
    ),
    ("buildings", "green"): (
        "Aucun bâtiment n'est cartographié sur la parcelle ni à moins de {buffer} m de ses limites.",
        "No building is mapped on the parcel or within {buffer} m of its boundary.",
    ),
    ("buildings", "amber"): (
        "Aucun bâtiment n'est cartographié sur la parcelle, mais {near_count} bâtiment(s) se "
        "trouvent à moins de {buffer} m de ses limites. Vérifiez sur place qu'aucun n'empiète "
        "sur la parcelle.",
        "No building is mapped on the parcel, but {near_count} building(s) stand within {buffer} m "
        "of its boundary. Check on site that none encroaches on the parcel.",
    ),
    ("buildings", "red"): (
        "{inside_count} bâtiment(s) sont cartographiés sur la parcelle, couvrant environ "
        "{inside_footprint} m² ({inside_share} % de sa surface). Renseignez-vous sur leurs "
        "occupants avant d'acheter.",
        "{inside_count} building(s) are mapped on the parcel, covering about {inside_footprint} m² "
        "({inside_share} % of it). Find out who occupies them before buying.",
    ),
    ("buildings", "grey"): (
        "La présence de bâtiments n'a pas pu être vérifiée.",
        "Buildings on the parcel could not be checked.",
    ),
}

DATASETS = [
    {
        "slug": "copernicus-dem-glo30",
        "name": "Copernicus DEM GLO-30",
        "provider": "European Space Agency / Copernicus",
        "version": "GLO-30 (2021)",
        "licence": "Copernicus DEM licence: free use including commercial, attribution required",
        "attribution": (
            "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence "
            "and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; "
            "all rights reserved."
        ),
        "url": "https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model",
        "commercial_use_allowed": True,
    },
    {
        "slug": "osm-buildings",
        "name": "OpenStreetMap buildings",
        "provider": "OpenStreetMap contributors, via the Overpass API",
        "version": "",
        "licence": "Open Database License (ODbL) 1.0",
        "attribution": "© OpenStreetMap contributors, available under the Open Database License.",
        "url": "https://www.openstreetmap.org/copyright",
        "commercial_use_allowed": True,
    },
]


def seed(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    Dataset = apps.get_model("core", "Dataset")

    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    SiteSetting.objects.get_or_create(
        key="analysis_thresholds",
        defaults={
            "value": {
                "area_amber_pct": 10,
                "area_red_pct": 25,
                "slope_amber_deg": 5,
                "slope_red_deg": 10,
                "erosion_slope_deg": 15,
                "building_buffer_m": 20,
            },
            "description": (
                "Traffic-light thresholds. Area: % difference stated vs computed. Terrain: mean "
                "slope in degrees; erosion_slope_deg marks steep, erosion-prone ground. "
                "building_buffer_m: distance counted as 'near the boundary'."
            ),
        },
    )
    for dataset in DATASETS:
        Dataset.objects.update_or_create(slug=dataset["slug"], defaults=dataset)


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0002_moduleresult_maps_findingtemplate"),
        ("core", "0002_set_site_name"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
