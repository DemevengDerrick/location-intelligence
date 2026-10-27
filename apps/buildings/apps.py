from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class BuildingsConfig(AppConfig):
    name = "apps.buildings"
    label = "buildings"
    verbose_name = _("Building footprints")
