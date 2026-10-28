"""Plainer, less categorical findings for non-specialist readers: each says what the data
suggests and what to do next. What the data cannot show moves to the "Limits" line that
every report section now carries."""

from django.db import migrations

WORDING = {
    ("access", "green"): (
        "The parcel appears well served: {road}. {times}",
        "La parcelle semble bien desservie : {road}. {times}",
    ),
    ("access", "amber"): (
        "Access may be difficult: {reasons}. {times} Visit the site to see how it is reached, "
        "in the dry and the rainy season.",
        "L'accès peut être difficile : {reasons}. {times} Rendez-vous sur place pour voir "
        "comment on y accède, en saison sèche comme en saison des pluies.",
    ),
    ("access", "red"): (
        "The maps we used show no road reaching the parcel: {reasons}. A track may exist that "
        "is not mapped. Visit the site, and check that a legal right of way exists before "
        "buying.",
        "Les cartes utilisées ne montrent aucune route jusqu'à la parcelle : {reasons}. Une "
        "piste non cartographiée peut exister. Rendez-vous sur place et vérifiez qu'un droit "
        "de passage existe avant d'acheter.",
    ),
    ("access", "grey"): (
        "We could not estimate access and nearby services for this parcel.",
        "Nous n'avons pas pu estimer l'accès et les services proches de cette parcelle.",
    ),
    ("buildings", "green"): (
        "The building map we used shows no building on the parcel or within {buffer} m of "
        "its boundary.",
        "La carte des bâtiments utilisée n'en montre aucun sur la parcelle ni à moins de "
        "{buffer} m de ses limites.",
    ),
    ("buildings", "amber"): (
        "No building appears on the parcel, but {near_count} building(s) appear within "
        "{buffer} m of its boundary. Check on site that nothing encroaches on the parcel.",
        "Aucun bâtiment n'apparaît sur la parcelle, mais {near_count} bâtiment(s) "
        "apparaissent à moins de {buffer} m de ses limites. Vérifiez sur place que rien "
        "n'empiète sur la parcelle.",
    ),
    ("buildings", "red"): (
        "The building map shows {inside_count} building(s) on the parcel, covering about "
        "{inside_footprint} m² ({inside_share} % of it). Find out who occupies them before "
        "buying.",
        "La carte des bâtiments en montre {inside_count} sur la parcelle, couvrant environ "
        "{inside_footprint} m² ({inside_share} % de sa surface). Renseignez-vous sur leurs "
        "occupants avant d'acheter.",
    ),
    ("buildings", "grey"): (
        "We could not check for buildings on the parcel.",
        "Nous n'avons pas pu vérifier la présence de bâtiments sur la parcelle.",
    ),
    ("change", "green"): (
        "Satellite images from {first_year} to {last_year} show no clear sign of recent "
        "clearing: vegetation covered about {veg_first} % of the parcel at the start and "
        "{veg_last} % at the end.",
        "Les images satellite de {first_year} à {last_year} ne montrent pas de défrichement "
        "récent net : la végétation couvrait environ {veg_first} % de la parcelle au début et "
        "{veg_last} % à la fin.",
    ),
    ("change", "amber"): (
        "Satellite images suggest part of the parcel was cleared recently: vegetation went "
        "from about {veg_ref} % in {ref_year} to {veg_last} % in {last_year}. Ask the seller "
        "who cleared it and why, and check on site.",
        "Les images satellite suggèrent qu'une partie de la parcelle a été défrichée "
        "récemment : la végétation est passée d'environ {veg_ref} % en {ref_year} à "
        "{veg_last} % en {last_year}. Demandez au vendeur qui l'a défrichée et pourquoi, et "
        "vérifiez sur place.",
    ),
    ("change", "red"): (
        "Satellite images suggest much of the parcel was cleared recently: vegetation went "
        "from about {veg_ref} % in {ref_year} to {veg_last} % in {last_year}. Ask the seller "
        "who cleared it and why, and check on site for recent work or construction.",
        "Les images satellite suggèrent qu'une grande partie de la parcelle a été défrichée "
        "récemment : la végétation est passée d'environ {veg_ref} % en {ref_year} à "
        "{veg_last} % en {last_year}. Demandez au vendeur qui l'a défrichée et pourquoi, et "
        "vérifiez sur place s'il y a des travaux ou une construction récente.",
    ),
    ("change", "grey"): (
        "There were too few clear satellite images to follow changes on the parcel over time.",
        "Il y avait trop peu d'images satellite nettes pour suivre l'évolution de la parcelle.",
    ),
    ("demographics", "green"): (
        "The area appears to be growing. About {people} people are estimated to live within "
        "5 km of the parcel ({density} per km²). The population changed by about {growth} % a "
        "year from {y1} to {y2}, and is expected to change by {projected} % a year to {y3}. "
        "{under15} % are under 15. {expansion}",
        "La zone semble en croissance. Environ {people} personnes vivraient à moins de 5 km "
        "de la parcelle ({density} par km²). La population a évolué d'environ {growth} % par "
        "an de {y1} à {y2} et devrait évoluer de {projected} % par an jusqu'en {y3}. "
        "{under15} % ont moins de 15 ans. {expansion}",
    ),
    ("demographics", "amber"): (
        "The area appears to be growing slowly. About {people} people are estimated to live "
        "within 5 km of the parcel ({density} per km²). The population changed by about "
        "{growth} % a year from {y1} to {y2}, and is expected to change by {projected} % a "
        "year to {y3}. {under15} % are under 15. {expansion}",
        "La zone semble croître lentement. Environ {people} personnes vivraient à moins de "
        "5 km de la parcelle ({density} par km²). La population a évolué d'environ {growth} % "
        "par an de {y1} à {y2} et devrait évoluer de {projected} % par an jusqu'en {y3}. "
        "{under15} % ont moins de 15 ans. {expansion}",
    ),
    ("demographics", "red"): (
        "The area's population appears to be falling. About {people} people are estimated to "
        "live within 5 km of the parcel ({density} per km²). The population changed by about "
        "{growth} % a year from {y1} to {y2}, and is expected to change by {projected} % a "
        "year to {y3}. {under15} % are under 15. {expansion}",
        "La population de la zone semble diminuer. Environ {people} personnes vivraient à "
        "moins de 5 km de la parcelle ({density} par km²). La population a évolué d'environ "
        "{growth} % par an de {y1} à {y2} et devrait évoluer de {projected} % par an "
        "jusqu'en {y3}. {under15} % ont moins de 15 ans. {expansion}",
    ),
    ("demographics", "grey"): (
        "We could not estimate the population around the parcel.",
        "Nous n'avons pas pu estimer la population autour de la parcelle.",
    ),
    ("flood", "green"): (
        "The flood data we used shows no 100-year river flood zone, river or wetland on the "
        "parcel. {nearest} Ask neighbours whether the land has flooded before.",
        "Les données d'inondation utilisées ne montrent ni zone inondable centennale, ni "
        "rivière, ni zone humide sur la parcelle. {nearest} Demandez aux voisins si le "
        "terrain a déjà été inondé.",
    ),
    ("flood", "amber"): (
        "The parcel is close to water or to a flood zone: {reasons}. Visit after heavy rain "
        "and ask neighbours about past floods.",
        "La parcelle est proche de l'eau ou d'une zone inondable : {reasons}. Rendez-vous sur "
        "place après une forte pluie et interrogez les voisins sur les inondations passées.",
    ),
    ("flood", "red"): (
        "The flood data we used suggests the parcel is exposed to flooding: {reasons}. Do not "
        "buy without seeing how the land behaves in the rainy season and asking neighbours "
        "about past floods.",
        "Les données d'inondation utilisées suggèrent que la parcelle est exposée aux "
        "inondations : {reasons}. N'achetez pas sans avoir vu le terrain en saison des pluies "
        "et interrogé les voisins sur les inondations passées.",
    ),
    ("flood", "grey"): (
        "We could not assess flood exposure for this parcel.",
        "Nous n'avons pas pu évaluer l'exposition de cette parcelle aux inondations.",
    ),
    ("imagery", "green"): (
        "Recent satellite images ({period}) show the parcel mostly covered by vegetation: "
        "about {vegetation} % vegetation and {open} % built-up or bare ground.",
        "Les images satellite récentes ({period}) montrent une parcelle surtout couverte de "
        "végétation : environ {vegetation} % de végétation et {open} % de sol bâti ou nu.",
    ),
    ("imagery", "amber"): (
        "Recent satellite images ({period}) show most of the parcel without vegetation: about "
        "{open} % looks built-up or bare. See the Buildings section and check on site.",
        "Les images satellite récentes ({period}) montrent la plus grande partie de la "
        "parcelle sans végétation : environ {open} % semble bâti ou nu. Voyez la section "
        "Bâtiments et vérifiez sur place.",
    ),
    ("imagery", "red"): (
        "Recent satellite images ({period}) show most of the parcel without vegetation: about "
        "{open} % looks built-up or bare. See the Buildings section and check on site.",
        "Les images satellite récentes ({period}) montrent la plus grande partie de la "
        "parcelle sans végétation : environ {open} % semble bâti ou nu. Voyez la section "
        "Bâtiments et vérifiez sur place.",
    ),
    ("imagery", "grey"): (
        "Recent satellite images do not show the parcel clearly (too much cloud), so we could "
        "not measure what covers it.",
        "Les images satellite récentes ne montrent pas clairement la parcelle (trop de "
        "nuages) : nous n'avons pas pu mesurer ce qui la couvre.",
    ),
    ("location", "green"): (
        "The boundary you gave covers {area} m², close to the {stated_area} m² stated by the "
        "seller. The parcel lies in {commune} ({admin_area}).",
        "Le contour fourni couvre {area} m², proche des {stated_area} m² annoncés par le "
        "vendeur. La parcelle se trouve dans la commune de {commune} ({admin_area}).",
    ),
    ("location", "amber"): (
        "The boundary you gave covers {area} m², {difference} % different from the "
        "{stated_area} m² stated by the seller. Ask a surveyor (géomètre) to confirm the "
        "boundary. The parcel lies in {commune} ({admin_area}).",
        "Le contour fourni couvre {area} m², soit {difference} % d'écart avec les "
        "{stated_area} m² annoncés par le vendeur. Faites confirmer les limites par un "
        "géomètre. La parcelle se trouve dans la commune de {commune} ({admin_area}).",
    ),
    ("location", "red"): (
        "The boundary you gave covers {area} m², {difference} % different from the "
        "{stated_area} m² stated by the seller. Do not pay before a surveyor (géomètre) has "
        "confirmed the boundary. The parcel lies in {commune} ({admin_area}).",
        "Le contour fourni couvre {area} m², soit {difference} % d'écart avec les "
        "{stated_area} m² annoncés par le vendeur. Ne payez pas avant qu'un géomètre ait "
        "confirmé les limites. La parcelle se trouve dans la commune de {commune} "
        "({admin_area}).",
    ),
    ("location", "grey"): (
        "The parcel lies in {commune} ({admin_area}). We could not compare its area with the "
        "seller's, because the exact boundary or the stated area is missing.",
        "La parcelle se trouve dans la commune de {commune} ({admin_area}). Nous n'avons pas "
        "pu comparer sa surface à celle du vendeur, faute de contour exact ou de surface "
        "annoncée.",
    ),
    ("red_flags", "green"): (
        "The maps we used show no protected area, public-utility zone or setback strip on the "
        "parcel. Other rules can still apply: ask the commune's urban planning office.",
        "Les cartes utilisées ne montrent ni aire protégée, ni zone d'utilité publique, ni "
        "bande de recul sur la parcelle. D'autres règles peuvent s'appliquer : renseignez-vous "
        "au service d'urbanisme de la commune.",
    ),
    ("red_flags", "amber"): (
        "Check these possible constraints before buying: {items}. {note} Ask the commune's "
        "urban planning office which rules apply.",
        "Vérifiez ces contraintes possibles avant d'acheter : {items}. {note} Demandez au "
        "service d'urbanisme de la commune quelles règles s'appliquent.",
    ),
    ("red_flags", "red"): (
        "The maps we used suggest the parcel is affected by constraints: {items}. {note} Part "
        "of the land may not be buildable or may belong to the State: get written "
        "confirmation from the commune's urban planning office and the land registry before "
        "paying.",
        "Les cartes utilisées suggèrent que la parcelle est concernée par des contraintes : "
        "{items}. {note} Une partie du terrain pourrait être inconstructible ou appartenir au "
        "domaine de l'État : obtenez une confirmation écrite du service d'urbanisme de la "
        "commune et des Domaines avant de payer.",
    ),
    ("red_flags", "grey"): (
        "We could not check for regulatory constraints.",
        "Nous n'avons pas pu vérifier les contraintes réglementaires.",
    ),
    ("signals", "grey"): (
        "We could not search for land issues reported in the area. This does not mean there "
        "are none.",
        "Nous n'avons pas pu rechercher les problèmes fonciers signalés dans la zone. Cela ne "
        "veut pas dire qu'il n'y en a pas.",
    ),
    ("terrain", "green"): (
        "The ground is fairly flat: average slope {slope_mean}°, height {elevation_min} to "
        "{elevation_max} m above sea level. Slope is unlikely to cause erosion.",
        "Le terrain est plutôt plat : pente moyenne de {slope_mean}°, altitude de "
        "{elevation_min} à {elevation_max} m. La pente ne devrait pas causer d'érosion.",
    ),
    ("terrain", "amber"): (
        "The ground slopes moderately: average slope {slope_mean}° (up to {slope_max}°), "
        "height {elevation_min} to {elevation_max} m above sea level. {steep_share} % of the "
        "parcel is steeper than {threshold}°. Plan for drainage and watch for erosion.",
        "Le terrain est en pente modérée : pente moyenne de {slope_mean}° (jusqu'à "
        "{slope_max}°), altitude de {elevation_min} à {elevation_max} m. {steep_share} % de "
        "la parcelle dépasse {threshold}°. Prévoyez l'évacuation des eaux et surveillez "
        "l'érosion.",
    ),
    ("terrain", "red"): (
        "The ground is steep: average slope {slope_mean}° (up to {slope_max}°). "
        "{steep_share} % of the parcel is steeper than {threshold}°, where erosion and "
        "landslides are a risk. Building may need terraces and retaining walls: have the site "
        "checked by a professional.",
        "Le terrain est en forte pente : pente moyenne de {slope_mean}° (jusqu'à "
        "{slope_max}°). {steep_share} % de la parcelle dépasse {threshold}°, où l'érosion et "
        "les glissements de terrain sont un risque. Construire peut demander des terrasses et "
        "des murs de soutènement : faites examiner le site par un professionnel.",
    ),
    ("terrain", "grey"): (
        "We could not measure the slope of the parcel.",
        "Nous n'avons pas pu mesurer la pente de la parcelle.",
    ),
}


def reword(apps, schema_editor):
    FindingTemplate = apps.get_model("analysis", "FindingTemplate")
    for (module, rating), (en, fr) in WORDING.items():
        FindingTemplate.objects.update_or_create(
            module=module,
            rating=rating,
            defaults={"text": fr, "text_fr": fr, "text_en": en},
        )


class Migration(migrations.Migration):
    dependencies = [("analysis", "0017_plain_dataset_text")]

    operations = [migrations.RunPython(reword, migrations.RunPython.noop)]
