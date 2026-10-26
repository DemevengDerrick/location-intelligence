"""Regulatory red flags: finding templates, setback rules, dataset entry and thresholds."""

from django.db import migrations

TEMPLATES = {
    ("red_flags", "green"): (
        "Aucune aire protégée, zone d'utilité publique ou bande de recul ne touche la parcelle "
        "d'après les données cartographiées. Des règles d'urbanisme peuvent tout de même "
        "s'appliquer : renseignez-vous au service de l'urbanisme de la commune.",
        "No protected area, public-utility zone or setback strip affects the parcel, as far as "
        "the mapped data shows. Planning rules can still apply: check with the commune's urban "
        "planning office.",
    ),
    ("red_flags", "amber"): (
        "Vérifiez ces contraintes avant d'acheter : {items}. {note} Faites confirmer les règles "
        "applicables par le service de l'urbanisme de la commune.",
        "Check these constraints before buying: {items}. {note} Have the rules that apply "
        "confirmed by the commune's urban planning office.",
    ),
    ("red_flags", "red"): (
        "La parcelle est touchée par des contraintes réglementaires : {items}. {note} Une partie "
        "du terrain peut être inconstructible ou relever du domaine public : obtenez une "
        "confirmation écrite du service de l'urbanisme et de la conservation foncière avant de "
        "payer.",
        "The parcel is affected by regulatory constraints: {items}. {note} Part of the land may "
        "not be buildable or may be public domain: get written confirmation from the commune's "
        "urban planning office and the land registry before paying.",
    ),
    ("red_flags", "grey"): (
        "Les contraintes réglementaires n'ont pas pu être vérifiées.",
        "Regulatory constraints could not be checked.",
    ),
}

DATASETS = [
    {
        "slug": "reference-layers",
        "name": "Official constraint layers (public-utility zones, corridors, risk zones)",
        "provider": "Uploaded by the report provider from official sources",
        "version": "",
        "licence": "As published by the issuing administration",
        "attribution": "Each feature records its source (decree, ministry or map) in the "
        "reference layers.",
        "url": "",
        "commercial_use_allowed": True,
    },
]

THRESHOLDS = {"setback_red_pct": 10, "constraint_near_m": 200}


def seed(apps, schema_editor):
    from apps.analysis.config import DEFAULT_SETBACK_RULES, SETBACK_KEY

    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    Dataset = apps.get_model("core", "Dataset")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    for dataset in DATASETS:
        Dataset.objects.update_or_create(slug=dataset["slug"], defaults=dataset)
    SiteSetting.objects.get_or_create(key=SETBACK_KEY, defaults={"value": DEFAULT_SETBACK_RULES})
    setting = SiteSetting.objects.filter(key="analysis_thresholds").first()
    if setting is not None:
        setting.value = {**THRESHOLDS, **(setting.value or {})}
        setting.save()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0010_seed_demographics"), ("core", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
