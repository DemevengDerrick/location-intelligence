"""Plainer wording for non-specialist readers in the seeded pages: "due diligence from remote
data" becomes "a first look from free public data". Only exact seeded sentences are replaced,
so pages an admin has already rewritten stay as they are."""

from django.db import migrations

REPLACE = {
    "about": [
        (
            "We combine satellite imagery, open data on terrain, water, roads and population, and "
            "a review by an analyst, to give you a clear picture of the land before you pay the "
            "seller.",
            "We combine satellite images and free public maps of the ground, water, roads and "
            "population, checked by an analyst, to give you a first look at the land before you "
            "pay the seller.",
            "Nous combinons l'imagerie satellite, des données ouvertes sur le relief, l'eau, les "
            "routes et la population, et une relecture par un analyste, pour vous donner une image "
            "claire du terrain avant que vous ne payiez le vendeur.",
            "Nous combinons des images satellite et des cartes publiques gratuites du relief, de "
            "l'eau, des routes et de la population, vérifiées par un analyste, pour vous donner "
            "un premier regard sur le terrain avant que vous ne payiez le vendeur.",
        ),
    ],
    "disclaimer": [
        (
            "Our reports are physical and environmental due diligence from remote data: satellite "
            "imagery, elevation models, water, road and population data, and public reports.",
            "Our reports are a first look at a location from free public data: satellite images, "
            "ground height, water, road and population maps, and news reports.",
            "Nos rapports constituent une vérification physique et environnementale à partir de "
            "données à distance : imagerie satellite, modèles d'élévation, données sur l'eau, les "
            "routes et la population, et signalements publics.",
            "Nos rapports sont un premier regard sur un lieu à partir de données publiques "
            "gratuites : images satellite, altitude, cartes de l'eau, des routes et de la "
            "population, et articles de presse.",
        ),
        (
            "The data has limits: imagery may be several months old, flood and population models "
            "are estimates, and no reported issues in an area does not mean there are no "
            "disputes.",
            "The data has limits: it can be coarse, incomplete or out of date, flood and "
            "population figures are estimates, and finding no reported issue does not mean there "
            "is no dispute. More detailed data or a visit may show something different.",
            "Les données ont des limites : l'imagerie peut dater de plusieurs mois, les modèles "
            "d'inondation et de population sont des estimations, et l'absence de signalement dans "
            "une zone ne signifie pas qu'il n'y a pas de litige.",
            "Les données ont des limites : elles peuvent être grossières, incomplètes ou "
            "anciennes, les chiffres d'inondation et de population sont des estimations, et "
            "l'absence de signalement ne signifie pas qu'il n'y a pas de litige. Des données plus "
            "détaillées ou une visite peuvent montrer autre chose.",
        ),
    ],
    "terms": [
        (
            "1. The service. We provide physical and environmental due-diligence reports on land "
            "parcels in Cameroon, prepared from remote data and reviewed by an analyst.",
            "1. The service. We provide location reports on land in Cameroon, prepared from free "
            "public data and checked by an analyst.",
            "1. Le service. Nous fournissons des rapports de vérification physique et "
            "environnementale de parcelles au Cameroun, établis à partir de données à distance et "
            "relus par un analyste.",
            "1. Le service. Nous fournissons des rapports d'analyse de localisation sur des "
            "terrains au Cameroun, établis à partir de données publiques gratuites et vérifiés "
            "par un analyste.",
        ),
    ],
}


def reword(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    for slug, changes in REPLACE.items():
        page = Page.objects.filter(slug=slug).first()
        if page is None:
            continue
        for old_en, new_en, old_fr, new_fr in changes:
            page.body_en = (page.body_en or "").replace(old_en, new_en)
            page.body_fr = (page.body_fr or "").replace(old_fr, new_fr)
        page.body = page.body_fr  # the base column holds the default language (French)
        page.save()


class Migration(migrations.Migration):
    dependencies = [("pages", "0002_seed_content")]

    operations = [migrations.RunPython(reword, migrations.RunPython.noop)]
