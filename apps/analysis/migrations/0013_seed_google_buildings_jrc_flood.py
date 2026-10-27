"""Buildings from Google Open Buildings instead of OpenStreetMap; the flood section built on the
JRC 1-in-100-year flood map, without the height-above-water estimate."""

from django.db import migrations

CAVEAT = (
    "Ce modèle ne couvre que les crues des grands cours d'eau, pas les inondations dues aux "
    "fortes pluies, aux caniveaux bouchés ou à la mer.",
    "This model covers flooding from large rivers only, not flooding from heavy rain, blocked "
    "drains or the sea.",
)

TEMPLATES = {
    ("flood", "green"): (
        "Aucune zone inondable centennale, rivière ou zone humide ne touche la parcelle. "
        "{nearest} " + CAVEAT[0],
        "No 1-in-100-year flood zone, river or wetland affects the parcel. {nearest} "
        + CAVEAT[1],
    ),
    ("flood", "amber"): (
        "La parcelle est proche de l'eau ou d'une zone inondable : {reasons}. Vérifiez le terrain "
        "après de fortes pluies et interrogez les voisins sur les inondations passées. "
        + CAVEAT[0],
        "The parcel is close to water or a flood zone: {reasons}. Check the ground after heavy "
        "rain and ask neighbours about past flooding. " + CAVEAT[1],
    ),
}

GOOGLE_BUILDINGS = {
    "slug": "google-open-buildings",
    "name": "Google Open Buildings (building footprints)",
    "provider": "Google Research",
    "version": "v3",
    "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
    "attribution": "W. Sirko, S. Kashubin, M. Ritter, A. Annkah, Y.S.E. Bouchareb, Y. Dauphin, "
    "D. Keysers, M. Neumann, M. Cisse, J.A. Quinn. Continental-scale building detection from "
    "high resolution satellite imagery. arXiv:2107.12283, 2021. Google Open Buildings v3, "
    "CC BY 4.0. Footprints detected by a model; detections below the confidence threshold "
    "are left out.",
    "url": "https://sites.research.google/open-buildings/",
    "commercial_use_allowed": True,
}

ADD = {"building_min_confidence": 0.7, "flood_depth_red_m": 1}
REMOVE = ("height_above_water_amber_m", "water_distance_amber_m")


def seed(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    Dataset = apps.get_model("core", "Dataset")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    Dataset.objects.update_or_create(slug=GOOGLE_BUILDINGS["slug"], defaults=GOOGLE_BUILDINGS)
    Dataset.objects.filter(slug="jrc-flood-hazard").update(
        attribution="© European Union, Copernicus Emergency Management Service. Global river "
        "flood hazard maps (JRC). Changes: resampled to the 30 m surface-water grid. Covers "
        "river flooding from large catchments only."
    )
    setting = SiteSetting.objects.filter(key="analysis_thresholds").first()
    if setting is not None:
        value = {**ADD, **(setting.value or {})}
        setting.value = {k: v for k, v in value.items() if k not in REMOVE}
        setting.save()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0012_seed_worldpop_history")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
