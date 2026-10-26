from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GazetteerConfig(AppConfig):
    name = "apps.gazetteer"
    label = "gazetteer"
    verbose_name = _("Gazetteer")
