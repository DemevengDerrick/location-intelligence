"""Land cover reports vegetation vs "built-up or bare ground": Sentinel-2 at 10 m cannot tell
buildings from cleared soil. New wording and thresholds for imagery and change."""

from django.db import migrations

TEMPLATES = {
    ("imagery", "green"): (
        "L'imagerie satellite récente ({period}) montre une parcelle surtout végétalisée : environ "
        "{vegetation} % de végétation et {open} % de surface bâtie ou de sol nu.",
        "Recent satellite imagery ({period}) shows the parcel mostly vegetated: about {vegetation} % "
        "vegetation and {open} % built-up or bare ground.",
    ),
    ("imagery", "amber"): (
        "L'imagerie satellite récente ({period}) montre une parcelle en grande partie sans "
        "végétation : environ {open} % de surface bâtie ou de sol nu. L'imagerie ne distingue pas "
        "les bâtiments d'un sol défriché : voyez la section Bâtiments et vérifiez sur place.",
        "Recent satellite imagery ({period}) shows most of the parcel without vegetation: about "
        "{open} % is built-up or bare ground. The imagery cannot tell buildings from cleared soil: "
        "see the Buildings section and check on site.",
    ),
    ("change", "green"): (
        "Entre {first_year} et {last_year}, la végétation couvrait {veg_first} % de la parcelle au "
        "début et {veg_last} % à la fin. Aucun défrichement récent n'a été détecté.",
        "Between {first_year} and {last_year}, vegetation covered {veg_first} % of the parcel at the "
        "start and {veg_last} % at the end. No recent clearing was detected.",
    ),
    ("change", "amber"): (
        "Une partie de la parcelle a été défrichée récemment : la végétation est passée de "
        "{veg_ref} % en {ref_year} à {veg_last} % en {last_year}. Demandez au vendeur qui a "
        "défriché et pourquoi, et vérifiez sur place s'il y a des travaux ou des constructions.",
        "Part of the parcel was cleared recently: vegetation fell from {veg_ref} % in {ref_year} to "
        "{veg_last} % in {last_year}. Ask the seller who cleared it and why, and check on site for "
        "recent work or construction.",
    ),
}
# An analyst may raise these sections to red; the amber wording fits that case too.
TEMPLATES[("imagery", "red")] = TEMPLATES[("imagery", "amber")]
TEMPLATES[("change", "red")] = TEMPLATES[("change", "amber")]

REMOVED = ["built_amber_pct", "built_red_pct", "built_increase_red_pts",
           "vegetation_loss_amber_pts", "ndbi_built", "ndvi_built_max"]
ADDED = {"open_amber_pct": 50, "clearing_amber_pts": 20}


def update(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    SiteSetting = apps.get_model("core", "SiteSetting")
    for (module, rating), (fr, en) in TEMPLATES.items():
        FindingTemplate.objects.update_or_create(
            module=module, rating=rating, defaults={"text": fr, "text_fr": fr, "text_en": en}
        )
    setting = SiteSetting.objects.filter(key="analysis_thresholds").first()
    if setting is not None:
        value = {k: v for k, v in (setting.value or {}).items() if k not in REMOVED}
        setting.value = {**ADDED, **value}
        setting.save()


class Migration(migrations.Migration):
    dependencies = [("analysis", "0005_seed_imagery_change")]

    operations = [migrations.RunPython(update, migrations.RunPython.noop)]
