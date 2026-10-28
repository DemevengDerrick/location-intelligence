"""Say, in everyday words, what each data source is used for and what it cannot show: the
report's sources section lists these for non-specialist readers."""

from django.db import migrations

# slug: (use EN, use FR, limits EN, limits FR)
PLAIN = {
    "copernicus-dem-glo30": (
        "Ground height and slope",
        "Altitude et pente du terrain",
        "About 30 m detail, and it includes buildings and trees, so slopes in towns and "
        "forests are approximate.",
        "Précision d'environ 30 m ; les bâtiments et les arbres sont inclus, donc les pentes "
        "en ville et en forêt sont approximatives.",
    ),
    "sentinel-2-l2a": (
        "Recent satellite images and changes over time",
        "Images satellite récentes et évolution dans le temps",
        "Each pixel covers 10 m by 10 m: the images show what generally covers the land, not "
        "small buildings. Clouds hide some dates.",
        "Chaque pixel couvre 10 m sur 10 m : les images montrent l'occupation générale du sol, "
        "pas les petits bâtiments. Les nuages masquent certaines dates.",
    ),
    "forest-atlas": (
        "Protected areas, forest reserves and concessions",
        "Aires protégées, réserves forestières et concessions",
        "Official maps from the Ministry of Forests (MINFOF) and WRI. Boundaries can be "
        "approximate or out of date.",
        "Cartes officielles du ministère des Forêts (MINFOF) et du WRI. Les limites peuvent "
        "être approximatives ou anciennes.",
    ),
    "gdelt": (
        "Online news search (when switched on)",
        "Recherche d'articles en ligne (lorsqu'elle est activée)",
        "Only covers the articles it has collected, mostly from the last three months.",
        "Ne couvre que les articles qu'il a collectés, surtout ceux des trois derniers mois.",
    ),
    "ghsl-built-s": (
        "How much land around the parcel was built on, from 1975 to today",
        "Surface bâtie autour de la parcelle, de 1975 à aujourd'hui",
        "A global model at 100 m: it shows trends, not individual buildings.",
        "Un modèle mondial à 100 m : il montre des tendances, pas des bâtiments un par un.",
    ),
    "ghsl-pop": (
        "Long-term population trends",
        "Évolution de la population sur le long terme",
        "Estimates from a computer model at 100 m, not census counts.",
        "Estimations d'un modèle informatique à 100 m, pas des chiffres de recensement.",
    ),
    "jrc-flood-hazard": (
        "Areas flooded by large rivers about once every 100 years",
        "Zones inondées par les grands cours d'eau environ une fois tous les 100 ans",
        "About 90 m detail. It covers large rivers only, not flooding from heavy rain, "
        "blocked drains or the sea.",
        "Précision d'environ 90 m. Ne couvre que les grands cours d'eau, pas les inondations "
        "dues aux fortes pluies, aux caniveaux bouchés ou à la mer.",
    ),
    "google-open-buildings": (
        "Building outlines on and around the parcel",
        "Contours des bâtiments sur et autour de la parcelle",
        "Drawn by computer from satellite images taken a few years ago. It can miss small or "
        "recent buildings, or show some that are not there.",
        "Tracés par ordinateur à partir d'images satellite de quelques années. Peut manquer "
        "des bâtiments petits ou récents, ou en montrer qui n'existent pas.",
    ),
    "jrc-gsw": (
        "Where satellites have seen water since 1984",
        "Endroits où les satellites ont vu de l'eau depuis 1984",
        "About 30 m detail: small streams and short floods can be missed.",
        "Précision d'environ 30 m : les petits ruisseaux et les crues courtes peuvent échapper.",
    ),
    "reference-layers": (
        "Official constraint maps added by our analysts",
        "Cartes officielles de contraintes ajoutées par nos analystes",
        "Only as complete as the maps the administrations publish.",
        "Aussi complètes que les cartes publiées par les administrations, pas plus.",
    ),
    "osm-buildings": (
        "Building outlines (earlier reports)",
        "Contours des bâtiments (rapports plus anciens)",
        "Mapped by volunteers; coverage varies from place to place.",
        "Cartographiés par des bénévoles ; la couverture varie selon les endroits.",
    ),
    "osm-roads-services": (
        "Roads, schools, health centres, markets and water points",
        "Routes, écoles, centres de santé, marchés et points d'eau",
        "Mapped by volunteers (OpenStreetMap): some roads and services are missing or out "
        "of date.",
        "Cartographiés par des bénévoles (OpenStreetMap) : certaines routes et certains "
        "services manquent ou sont anciens.",
    ),
    "osm-water": (
        "Rivers, lakes and wetlands",
        "Rivières, lacs et zones humides",
        "Mapped by volunteers: small streams and ditches may be missing.",
        "Cartographiés par des bénévoles : les petits ruisseaux et fossés peuvent manquer.",
    ),
    "worldpop-r2025a": (
        "How many people live nearby, and their ages",
        "Nombre d'habitants à proximité et leur âge",
        "Estimates from a computer model at 100 m, not census counts; less reliable for small "
        "areas. Future figures are projections.",
        "Estimations d'un modèle informatique à 100 m, pas des chiffres de recensement ; moins "
        "fiables pour les petites zones. Les chiffres futurs sont des projections.",
    ),
    "worldpop-global1": (
        "Population trends since 2000",
        "Évolution de la population depuis 2000",
        "Estimates from an older computer model: only growth rates are shown, not counts.",
        "Estimations d'un modèle plus ancien : seuls les taux de croissance sont montrés.",
    ),
    "news-outlets": (
        "Land issues reported in the press",
        "Problèmes fonciers signalés dans la presse",
        "Only what the news outlets we follow published online, checked by an analyst. Many "
        "disputes are never reported.",
        "Seulement ce que les médias suivis ont publié en ligne, vérifié par un analyste. "
        "Beaucoup de litiges ne sont jamais rapportés.",
    ),
}
BOUNDARIES = (
    "Country, region, department and commune boundaries",
    "Limites du pays, des régions, des départements et des communes",
    "Approximate boundaries that can differ from official ones.",
    "Limites approximatives, qui peuvent différer des limites officielles.",
)


def fill(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    for dataset in Dataset.objects.all():
        texts = PLAIN.get(dataset.slug)
        if texts is None and dataset.slug.startswith("geoboundaries-"):
            texts = BOUNDARIES
        if texts is None:
            continue
        use_en, use_fr, limits_en, limits_fr = texts
        # the base columns hold the default language (French)
        dataset.use = dataset.use_fr = use_fr
        dataset.use_en = use_en
        dataset.limitation = dataset.limitation_fr = limits_fr
        dataset.limitation_en = limits_en
        dataset.save()


class Migration(migrations.Migration):
    dependencies = [
        ("analysis", "0016_seed_forest_atlas"),
        ("core", "0004_dataset_plain_language"),
        ("incidents", "0005_ignore_tracking_params"),
    ]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
