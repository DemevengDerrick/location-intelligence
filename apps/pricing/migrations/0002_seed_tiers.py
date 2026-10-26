"""Initial tiers and prices. Every value is editable in the admin afterwards.

Desk report: 10,000 XAF at launch. Other currencies are set by hand near the XAF price
(not live FX). The field tier price is a placeholder until partner rates are known.
"""

from decimal import Decimal

from django.db import migrations

TIERS = [
    {
        "code": "desk",
        "sort_order": 1,
        "name": ("Rapport à distance", "Desk report"),
        "tagline": (
            "Analyse satellite et données ouvertes, relue par un analyste.",
            "Satellite and open-data analysis, reviewed by an analyst.",
        ),
        "features": (
            "Vérification de la localisation et de la superficie\n"
            "Occupation actuelle et évolution sur 5 à 10 ans\n"
            "Risques d'inondation, de pente et d'érosion\n"
            "Accès aux routes et services\n"
            "Population et croissance de la zone\n"
            "Signaux d'alerte réglementaires\n"
            "Rapport PDF et carte interactive",
            "Location and area check\n"
            "Current occupation and change over 5 to 10 years\n"
            "Flood, slope and erosion risks\n"
            "Access to roads and services\n"
            "Population and area growth\n"
            "Regulatory red flags\n"
            "PDF report and interactive map",
        ),
        "prices": {"XAF": "10000", "EUR": "15", "USD": "17", "CAD": "23"},
    },
    {
        "code": "field",
        "sort_order": 2,
        "name": ("Rapport + vérification terrain", "Report + field verification"),
        "tagline": (
            "Tout le rapport à distance, plus une visite par un géomètre ou un notaire agréé.",
            "Everything in the desk report, plus a visit by a licensed surveyor or notary.",
        ),
        "features": (
            "Tout le contenu du rapport à distance\n"
            "Visite du terrain avec photos géolocalisées\n"
            "Relevé GPS des bornes\n"
            "Observations sur l'occupation et l'accès\n"
            "Constats signés par le professionnel",
            "Everything in the desk report\n"
            "Site visit with geotagged photos\n"
            "GPS survey of boundary markers\n"
            "Occupation and access observations\n"
            "Findings signed by the professional",
        ),
        "prices": {"XAF": "50000", "EUR": "76", "USD": "87", "CAD": "120"},
    },
]


def seed(apps, schema_editor):
    Product = apps.get_model("pricing", "Product")
    ProductPrice = apps.get_model("pricing", "ProductPrice")
    for tier in TIERS:
        fields = {"kind": "tier", "sort_order": tier["sort_order"]}
        for name in ("name", "tagline", "features"):
            fr, en = tier[name]
            fields.update({name: fr, f"{name}_fr": fr, f"{name}_en": en})
        product, _ = Product.objects.update_or_create(code=tier["code"], defaults=fields)
        for currency, amount in tier["prices"].items():
            ProductPrice.objects.get_or_create(
                product=product, currency=currency, defaults={"amount": Decimal(amount)}
            )


class Migration(migrations.Migration):
    dependencies = [("pricing", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
