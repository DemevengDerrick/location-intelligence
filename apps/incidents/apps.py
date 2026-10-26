from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class IncidentsConfig(AppConfig):
    name = "apps.incidents"
    label = "incidents"
    verbose_name = _("Incidents")
