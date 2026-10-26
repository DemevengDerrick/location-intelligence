from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OsmConfig(AppConfig):
    name = "apps.osm"
    label = "osm"
    verbose_name = _("OpenStreetMap extract")
