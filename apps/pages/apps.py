from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PagesConfig(AppConfig):
    name = "apps.pages"
    label = "pages"
    verbose_name = _("Public site")
