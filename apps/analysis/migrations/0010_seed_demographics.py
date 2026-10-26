"""Demographics and area growth: finding templates, dataset licences and thresholds."""

from django.db import migrations

BODY_FR = (
    "Environ {people} personnes vivent à moins de 5 km de la parcelle ({density} par km²). "
    "La population a évolué de {growth} % par an de {y1} à {y2} et devrait évoluer de "
    "{projected} % par an jusqu'en {y3}. {under15} % ont moins de 15 ans. {expansion} Ce sont "
    "des estimations modélisées (WorldPop {release}), pas des chiffres de recensement."
)
BODY_EN = (
    "About {people} people live within 5 km of the parcel ({density} per km²). The population "
    "changed by {growth} % a year from {y1} to {y2} and is projected to change by {projected} % "
    "a year to {y3}. {under15} % are under 15. {expansion} These are modelled estimates "
    "(WorldPop {release}), not census counts."
)
TEMPLATES = {
    ("demographics", "green"): ("La zone est en croissance. " + BODY_FR,
                                "The area is growing. " + BODY_EN),
    ("demographics", "amber"): ("La zone croît lentement. " + BODY_FR,
                                "The area is growing slowly. " + BODY_EN),
    ("demographics", "red"): ("La population de la zone diminue. " + BODY_FR,
                              "The area's population is falling. " + BODY_EN),
    ("demographics", "grey"): (
        "Les données de population n'ont pas pu être calculées.",
        "Population figures could not be computed.",
    ),
}  # fmt: skip

DATASETS = [
    {
        "slug": "worldpop-r2025a",
        "name": "WorldPop age and sex structures, Cameroon (constrained, 100 m)",
        "provider": "WorldPop, University of Southampton",
        "version": "R2025A, 2020–2030 (2030 projected)",
        "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
        "attribution": "WorldPop (www.worldpop.org), School of Geography and Environmental "
        "Science, University of Southampton. Global2 age and sex structures, release R2025A. "
        "Modelled estimates, not census counts.",
        "url": "https://www.worldpop.org/",
        "commercial_use_allowed": True,
    },
    {
        "slug": "ghsl-built-s",
        "name": "GHSL built-up surface (GHS-BUILT-S)",
        "provider": "European Commission Joint Research Centre",
        "version": "R2023A, epochs 1975–2020",
        "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
        "attribution": "Pesaresi, M., Politis, P. (2023): GHS-BUILT-S R2023A - GHS built-up "
        "surface grid, derived from Sentinel2 composite and Landsat, multitemporal (1975-2030). "
        "European Commission, Joint Research Centre (JRC).",
        "url": "https://ghsl.jrc.ec.europa.eu/",
        "commercial_use_allowed": True,
    },
]

THRESHOLDS = {"growth_green_pct": 2.0, "growth_red_pct": 0.0, "ghsl_built_share": 0.1}


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
    dependencies = [("analysis", "0009_populationstat")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
