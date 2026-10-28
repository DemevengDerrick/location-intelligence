"""FAQ: delivery takes from 1 hour to 3 business days, depending on whether a field visit is
needed. Only the seeded answer is replaced, so an answer an admin has rewritten stays."""

from django.db import migrations

OLD_FR = (
    "Le rapport à distance est livré en 3 jours ouvrables après le paiement. La "
    "vérification terrain dépend de la disponibilité des partenaires dans la région."
)
OLD_EN = (
    "The desk report is delivered within 3 business days of payment. Field verification "
    "depends on partner availability in the region."
)
NEW_FR = (
    "Entre 1 heure et 3 jours ouvrables après le paiement, selon qu'une visite sur le terrain "
    "est nécessaire ou non : environ 1 heure sans visite, jusqu'à 3 jours ouvrables avec."
)
NEW_EN = (
    "From 1 hour to 3 business days after payment, depending on whether a field visit is "
    "needed: about 1 hour without a visit, up to 3 business days with one."
)


def reword(apps, schema_editor):
    FAQItem = apps.get_model("pages", "FAQItem")
    for item in FAQItem.objects.filter(answer_en=OLD_EN):
        item.answer_en = NEW_EN
        if item.answer_fr == OLD_FR:
            item.answer_fr = NEW_FR
        item.answer = item.answer_fr  # the base column holds the default language (French)
        item.save()


class Migration(migrations.Migration):
    dependencies = [("pages", "0003_plain_wording")]

    operations = [migrations.RunPython(reword, migrations.RunPython.noop)]
