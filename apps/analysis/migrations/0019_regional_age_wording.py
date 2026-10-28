"""WorldPop applies one age-sex profile to each region, so the share of under-15s describes the
region, not the neighbourhood: the demographics findings now say so."""

from django.db import migrations

EN = ("{under15} % are under 15.", "In the region, {under15} % of people are under 15.")
FR = ("{under15} % ont moins de 15 ans.", "Dans la région, {under15} % des habitants ont moins de 15 ans.")


def reword(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    for template in FindingTemplate.objects.filter(module="demographics"):
        template.text_en = (template.text_en or "").replace(*EN)
        template.text_fr = (template.text_fr or "").replace(*FR)
        template.text = template.text_fr  # the base column holds French
        template.save()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0018_plain_finding_wording")]

    operations = [migrations.RunPython(reword, migrations.RunPython.noop)]
