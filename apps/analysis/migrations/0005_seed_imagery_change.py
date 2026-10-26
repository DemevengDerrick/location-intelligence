"""Finding templates, the Sentinel-2 licence record and new thresholds for imagery and change."""

from django.db import migrations

TEMPLATES = {
    ("imagery", "green"): (
        "L'imagerie satellite récente ({period}) montre une parcelle surtout libre : environ "
        "{vegetation} % de végétation, {bare} % de sol nu et {built} % de surface bâtie.",
        "Recent satellite imagery ({period}) shows the parcel mostly open: about {vegetation} % "
        "vegetation, {bare} % bare ground and {built} % built-up.",
    ),
    ("imagery", "amber"): (
        "L'imagerie satellite récente ({period}) montre une partie bâtie sur la parcelle : environ "
        "{built} %, avec {vegetation} % de végétation et {bare} % de sol nu. Vérifiez sur place ce "
        "qui a été construit.",
        "Recent satellite imagery ({period}) shows some built-up surface on the parcel: about "
        "{built} %, with {vegetation} % vegetation and {bare} % bare ground. Check on site what has "
        "been built.",
    ),
    ("imagery", "red"): (
        "L'imagerie satellite récente ({period}) montre une parcelle largement bâtie : environ "
        "{built} % de sa surface. Renseignez-vous sur ses occupants avant d'acheter.",
        "Recent satellite imagery ({period}) shows the parcel largely built-up: about {built} % of "
        "its surface. Find out who occupies it before buying.",
    ),
    ("imagery", "grey"): (
        "L'imagerie satellite récente ne permet pas de voir clairement la parcelle (trop de "
        "nuages) : son occupation n'a pas pu être mesurée.",
        "Recent satellite imagery does not show the parcel clearly (too much cloud), so its "
        "occupation could not be measured.",
    ),
    ("change", "green"): (
        "Entre {first_year} et {last_year}, la parcelle a peu changé : la surface bâtie est passée "
        "de {built_first} % à {built_last} % et la végétation de {veg_first} % à {veg_last} %.",
        "Between {first_year} and {last_year} the parcel changed little: built-up surface went from "
        "{built_first} % to {built_last} % and vegetation from {veg_first} % to {veg_last} %.",
    ),
    ("change", "amber"): (
        "Entre {first_year} et {last_year}, la parcelle a changé : la végétation est passée de "
        "{veg_first} % à {veg_last} % et la surface bâtie de {built_first} % à {built_last} %. Le "
        "terrain a été défriché ou travaillé ; demandez au vendeur pourquoi.",
        "Between {first_year} and {last_year} the parcel changed: vegetation went from {veg_first} % "
        "to {veg_last} % and built-up surface from {built_first} % to {built_last} %. The land has "
        "been cleared or worked; ask the seller why.",
    ),
    ("change", "red"): (
        "Des constructions sont apparues récemment sur la parcelle : la surface bâtie est passée de "
        "{built_ref} % en {ref_year} à {built_last} % en {last_year}. Vérifiez sur place qui a "
        "construit et quand.",
        "Construction appeared on the parcel recently: built-up surface rose from {built_ref} % in "
        "{ref_year} to {built_last} % in {last_year}. Check on site who built and when.",
    ),
    ("change", "grey"): (
        "Trop peu d'images claires étaient disponibles pour suivre l'évolution de la parcelle.",
        "Too few clear images were available to follow changes on the parcel over time.",
    ),
}

NEW_THRESHOLDS = {
    "built_amber_pct": 5,
    "built_red_pct": 25,
    "built_increase_red_pts": 10,
    "vegetation_loss_amber_pts": 30,
    "imagery_max_scene_cloud": 70,
    "imagery_max_scenes": 6,
    "change_first_year": 2017,
    "ndvi_vegetation": 0.35,
    "ndbi_built": -0.05,
    "ndvi_built_max": 0.25,
    "mndwi_water": 0.2,
}

SENTINEL = {
    "slug": "sentinel-2-l2a",
    "name": "Copernicus Sentinel-2 Level-2A",
    "provider": "European Space Agency / Copernicus, via the AWS Open Data catalogue (Earth Search)",
    "version": "L2A",
    "licence": "Copernicus Sentinel data terms: free, full and open, including commercial use",
    "attribution": "Contains modified Copernicus Sentinel data, processed by the report provider.",
    "url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/",
    "commercial_use_allowed": True,
}


def seed(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    Dataset = apps.get_model("core", "Dataset")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    setting = SiteSetting.objects.filter(key="analysis_thresholds").first()
    if setting is not None:
        setting.value = {**NEW_THRESHOLDS, **(setting.value or {})}  # keep edited values
        setting.save()
    Dataset.objects.update_or_create(slug=SENTINEL["slug"], defaults=SENTINEL)


class Migration(migrations.Migration):
    dependencies = [("analysis", "0004_moduleresult_charts")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
