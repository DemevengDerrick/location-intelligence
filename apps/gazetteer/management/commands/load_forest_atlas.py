"""Load official protected areas, forest estate and concessions from the Forest Atlas of
Cameroon (MINFOF/WRI) as reference layers for the red-flags check.

    manage.py load_forest_atlas                       # every layer, from the feature services
    manage.py load_forest_atlas plantations hunting_zones
    manage.py load_forest_atlas protected_areas --file input/.../Aires_protegées_de_la_faune.shp

Re-running a layer replaces the features loaded before from it.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.gazetteer import forest_atlas


class Command(BaseCommand):
    help = "Load protected areas, forest estate and concessions from the Forest Atlas of Cameroon"

    def add_arguments(self, parser):
        parser.add_argument("layers", nargs="*", help=", ".join(forest_atlas.LAYERS))
        parser.add_argument(
            "--file", help="A local export of the one layer named (shapefile, GeoJSON...)"
        )

    def handle(self, *args, **options):
        keys = options["layers"] or list(forest_atlas.LAYERS)
        unknown = set(keys) - set(forest_atlas.LAYERS)
        if unknown:
            raise CommandError(f"Unknown layer(s): {', '.join(sorted(unknown))}")
        if options["file"] and len(keys) != 1:
            raise CommandError("--file needs exactly one layer name")
        for key in keys:
            layer = forest_atlas.LAYERS[key]
            if options["file"]:
                features = forest_atlas.read_file(options["file"])
            else:
                features = forest_atlas.fetch_features(layer)
            try:
                count = forest_atlas.load(layer, features)
            except Exception as exc:
                raise CommandError(f"{key}: {exc}") from exc
            self.stdout.write(f"{key}: {count} features ({layer.source})")
