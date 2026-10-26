from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AnalysisConfig(AppConfig):
    name = "apps.analysis"
    label = "analysis"
    verbose_name = _("Analysis")
