"""Draft bilingual content so every public page exists from the first deploy.

Terms, privacy and disclaimer are drafts flagged "pending legal review" (NFR-11, NFR-15):
a Cameroonian lawyer must review them before launch. All text is editable in the admin.
"""

from django.db import migrations

PAGES = {
    "about": {
        "version": "",
        "title": ("À propos", "About us"),
        "body": (
            "Acheter un terrain au Cameroun à distance est risqué : parcelle mal située, "
            "déjà construite, inondable ou située dans une zone d'utilité publique.\n\n"
            "Nous combinons l'imagerie satellite, des données ouvertes sur le relief, l'eau, "
            "les routes et la population, et une relecture par un analyste, pour vous donner "
            "une image claire du terrain avant que vous ne payiez le vendeur.\n\n"
            "Nous ne remplaçons ni le notaire ni le géomètre : nous vous aidons à savoir quoi "
            "leur demander.",
            "Buying land in Cameroon from abroad is risky: the parcel may be in the wrong "
            "place, already built on, prone to flooding or inside a public-utility zone.\n\n"
            "We combine satellite imagery, open data on terrain, water, roads and population, "
            "and a review by an analyst, to give you a clear picture of the land before you "
            "pay the seller.\n\n"
            "We do not replace a notary or a surveyor: we help you know what to ask them.",
        ),
    },
    "terms": {
        "version": "0.1",
        "title": ("Conditions générales de service", "Terms of service"),
        "body": (
            "1. Le service. Nous fournissons des rapports de vérification physique et "
            "environnementale de parcelles au Cameroun, établis à partir de données à "
            "distance et relus par un analyste.\n\n"
            "2. Ce que le service n'est pas. Le rapport n'est ni une vérification juridique "
            "du titre foncier, ni un bornage, ni une évaluation. Il ne confirme pas la "
            "propriété du terrain ni la validité d'un titre.\n\n"
            "3. Commande et paiement. La commande est confirmée à réception du paiement. "
            "Les délais indiqués courent à partir de cette confirmation.\n\n"
            "4. Responsabilité. Notre responsabilité est limitée au prix payé pour le rapport "
            "concerné.\n\n"
            "5. Remboursement. Si nous ne pouvons pas produire le rapport, vous êtes "
            "remboursé intégralement.\n\n"
            "6. Droit applicable. Les présentes conditions sont régies par le droit "
            "camerounais.",
            "1. The service. We provide physical and environmental due-diligence reports on "
            "land parcels in Cameroon, prepared from remote data and reviewed by an "
            "analyst.\n\n"
            "2. What the service is not. The report is not a legal title search, a survey or "
            "a valuation. It does not confirm who owns the land or whether a title is "
            "valid.\n\n"
            "3. Orders and payment. An order is confirmed when payment is received. Stated "
            "turnaround times start from that confirmation.\n\n"
            "4. Liability. Our liability is limited to the price paid for the report "
            "concerned.\n\n"
            "5. Refunds. If we cannot produce the report, you are refunded in full.\n\n"
            "6. Governing law. These terms are governed by the law of Cameroon.",
        ),
    },
    "privacy": {
        "version": "0.1",
        "title": ("Politique de confidentialité", "Privacy policy"),
        "body": (
            "Nous collectons uniquement ce dont une commande a besoin : vos coordonnées, la "
            "localisation de la parcelle, les documents que vous joignez et les informations "
            "de paiement traitées par nos prestataires de paiement.\n\n"
            "Vos parcelles et rapports ne sont jamais utilisés à des fins commerciales ni "
            "montrés à d'autres clients sans votre accord.\n\n"
            "Vous pouvez demander l'export ou la suppression de vos données à tout moment en "
            "nous contactant. Les rapports livrés sont conservés pendant une durée qui sera "
            "précisée ici.\n\n"
            "Nous appliquons la loi camerounaise n° 2024/017 sur la protection des données "
            "personnelles et, selon votre pays de résidence, le RGPD ou la LPRPDE.",
            "We collect only what an order needs: your contact details, the parcel location, "
            "the documents you attach and payment details handled by our payment "
            "providers.\n\n"
            "Your parcels and reports are never used in marketing or shown to other "
            "customers without your consent.\n\n"
            "You can ask us to export or delete your data at any time by contacting us. "
            "Delivered reports are kept for a retention period that will be stated here.\n\n"
            "We follow Cameroon's personal data protection law (Law No. 2024/017) and, "
            "depending on where you live, the GDPR or PIPEDA.",
        ),
    },
    "disclaimer": {
        "version": "0.1",
        "title": ("Avertissement sur les rapports", "Report disclaimer"),
        "body": (
            "Nos rapports constituent une vérification physique et environnementale à partir "
            "de données à distance : imagerie satellite, modèles d'élévation, données sur "
            "l'eau, les routes et la population, et signalements publics.\n\n"
            "Ils ne constituent ni une vérification juridique du titre foncier, ni un "
            "bornage, ni une évaluation. Ils ne confirment pas qui est propriétaire du "
            "terrain ni si un titre est valide.\n\n"
            "Les données ont des limites : l'imagerie peut dater de plusieurs mois, les "
            "modèles d'inondation et de population sont des estimations, et l'absence de "
            "signalement dans une zone ne signifie pas qu'il n'y a pas de litige.\n\n"
            "Avant tout paiement au vendeur, faites vérifier le titre à la conservation "
            "foncière par un notaire et les limites sur le terrain par un géomètre agréé.",
            "Our reports are physical and environmental due diligence from remote data: "
            "satellite imagery, elevation models, water, road and population data, and "
            "public reports.\n\n"
            "They are not a legal title search, a survey or a valuation. They do not confirm "
            "who owns the land or whether a title is valid.\n\n"
            "The data has limits: imagery may be several months old, flood and population "
            "models are estimates, and no reported issues in an area does not mean there are "
            "no disputes.\n\n"
            "Before paying the seller, have the title checked at the land registry by a "
            "notary and the boundaries checked on the ground by a licensed surveyor.",
        ),
    },
}

FAQ = [
    (
        "Vérifiez-vous le titre foncier ?",
        "Do you verify the land title?",
        "Non. Nous ne vérifions pas la validité juridique des titres. Le rapport décrit la "
        "situation physique et environnementale du terrain. Faites vérifier le titre par un "
        "notaire à la conservation foncière.",
        "No. We do not verify the legal validity of titles. The report describes the "
        "physical and environmental situation of the land. Have the title checked by a "
        "notary at the land registry.",
    ),
    (
        "De quoi avez-vous besoin pour localiser la parcelle ?",
        "What do you need to locate the parcel?",
        "Un repère sur la carte, un contour dessiné, un fichier de coordonnées (KML, GeoJSON, "
        "CSV…) ou une photo du plan de situation remis par le vendeur.",
        "A pin on the map, a drawn boundary, a coordinates file (KML, GeoJSON, CSV…) or a "
        "photo of the site plan given by the seller.",
    ),
    (
        "Combien de temps faut-il pour recevoir le rapport ?",
        "How long does it take to receive the report?",
        "Le rapport à distance est livré en 3 jours ouvrables après le paiement. La "
        "vérification terrain dépend de la disponibilité des partenaires dans la région.",
        "The desk report is delivered within 3 business days of payment. Field verification "
        "depends on partner availability in the region.",
    ),
    (
        "Comment puis-je payer ?",
        "How can I pay?",
        "Par carte bancaire ou par mobile money (MTN Mobile Money, Orange Money).",
        "By card or by mobile money (MTN Mobile Money, Orange Money).",
    ),
    (
        "Qui voit mes informations ?",
        "Who sees my information?",
        "Seuls notre équipe et, pour la vérification terrain, le partenaire assigné. Vos "
        "parcelles ne sont jamais montrées à d'autres clients.",
        "Only our team and, for field verification, the assigned partner. Your parcels are "
        "never shown to other customers.",
    ),
]


def seed(apps, schema_editor):
    Page = apps.get_model("pages", "Page")
    FAQItem = apps.get_model("pages", "FAQItem")
    SiteSetting = apps.get_model("core", "SiteSetting")

    for slug, page in PAGES.items():
        (title_fr, title_en), (body_fr, body_en) = page["title"], page["body"]
        Page.objects.update_or_create(
            slug=slug,
            defaults={
                "title": title_fr,
                "title_fr": title_fr,
                "title_en": title_en,
                "body": body_fr,
                "body_fr": body_fr,
                "body_en": body_en,
                "version": page["version"],
                "is_draft": True,
            },
        )

    if not FAQItem.objects.exists():
        for order, (q_fr, q_en, a_fr, a_en) in enumerate(FAQ, start=1):
            FAQItem.objects.create(
                question=q_fr,
                question_fr=q_fr,
                question_en=q_en,
                answer=a_fr,
                answer_fr=a_fr,
                answer_en=a_en,
                sort_order=order,
            )

    SiteSetting.objects.get_or_create(
        key="whatsapp_number",
        defaults={
            "value": "",
            "description": "WhatsApp number in international format, e.g. 237600000000. "
            "Leave empty to hide the WhatsApp button.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("pages", "0001_initial"), ("core", "0002_set_site_name")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
