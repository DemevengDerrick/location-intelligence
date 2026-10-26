"""Population history: 2015 joins the R2025A years, Global1 totals cover 2000–2010, and GHSL
population gives a second trend to compare with."""

from django.db import migrations

GLOBAL1 = {
    "slug": "worldpop-global1",
    "name": "WorldPop population counts, Cameroon (unconstrained, 100 m)",
    "provider": "WorldPop, University of Southampton",
    "version": "Global1, 2000–2010",
    "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
    "attribution": "WorldPop (www.worldpop.org), School of Geography and Environmental "
    "Science, University of Southampton. Global High Resolution Population Denominators "
    "Project (Global1), unconstrained counts. Modelled estimates, not census counts; another "
    "method than R2025A, so not directly comparable with it.",
    "url": "https://www.worldpop.org/",
    "commercial_use_allowed": True,
}

GHSL_POP = {
    "slug": "ghsl-pop",
    "name": "GHSL population grid (GHS-POP)",
    "provider": "European Commission Joint Research Centre",
    "version": "R2023A, epochs 2000–2030 (2025 and 2030 projected)",
    "licence": "Creative Commons Attribution 4.0 (CC BY 4.0)",
    "attribution": "Schiavina, M., Freire, S., Carioli, A., MacManus, K. (2023): GHS-POP R2023A "
    "- GHS population grid multitemporal (1975-2030). European Commission, Joint Research "
    "Centre (JRC). Modelled estimates, used here only to compare growth trends.",
    "url": "https://ghsl.jrc.ec.europa.eu/",
    "commercial_use_allowed": True,
}


def seed(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    for dataset in (GLOBAL1, GHSL_POP):
        Dataset.objects.update_or_create(slug=dataset["slug"], defaults=dataset)
    Dataset.objects.filter(slug="worldpop-r2025a").update(
        version="R2025A, 2015–2030 (2030 projected)"
    )


class Migration(migrations.Migration):
    dependencies = [("analysis", "0011_seed_red_flags")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
