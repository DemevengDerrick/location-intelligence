"""Area signals: finding templates and dataset entries. The finding is "for information"
(no traffic light); the FR-34 statement is added by the report template, not here."""

from django.db import migrations

TEMPLATES = {
    ("signals", "info"): ("{summary}", "{summary}"),
    ("signals", "grey"): (
        "La recherche de signalements fonciers dans la zone n'a pas pu être faite. Cela ne "
        "signifie pas qu'il n'y en a pas.",
        "The search for reported land issues in the area could not be run. It does not mean "
        "that there are none.",
    ),
}

DATASETS = [
    {
        "slug": "gdelt",
        "name": "GDELT DOC 2.0 news index",
        "provider": "The GDELT Project",
        "version": "",
        "licence": "Free for any academic, commercial or governmental use, with citation",
        "attribution": "News articles found through the GDELT Project (gdeltproject.org). "
        "Only links and short neutral summaries are shown; each article belongs to its outlet.",
        "url": "https://www.gdeltproject.org/",
        "commercial_use_allowed": True,
    },
    {
        "slug": "news-outlets",
        "name": "Cameroonian news outlets (public feeds)",
        "provider": "Journal du Cameroun, Actu Cameroun, Mimi Mefo Info, Data Cameroon, "
        "Le Bled Parle, Cameroon News Agency and outlets added by the provider",
        "version": "",
        "licence": "Articles © their publishers; only links and short summaries are shown",
        "attribution": "Read through the outlets' public RSS and search feeds, respecting "
        "robots.txt. Summaries are written fresh and reviewed by an analyst.",
        "url": "",
        "commercial_use_allowed": True,
    },
]


def seed(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    Dataset = apps.get_model("core", "Dataset")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    for dataset in DATASETS:
        Dataset.objects.update_or_create(slug=dataset["slug"], defaults=dataset)


class Migration(migrations.Migration):
    dependencies = [("analysis", "0014_alter_findingtemplate_rating_and_more"), ("core", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
