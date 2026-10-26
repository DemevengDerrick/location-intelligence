from django.db import models
from django.utils.translation import gettext_lazy as _


class InputMethod(models.TextChoices):
    PIN = "pin", _("Map pin")
    DRAWN = "drawn", _("Drawn polygon")
    FILE = "file", _("Coordinates file")
    SITE_PLAN = "site_plan", _("Site plan")
    ANALYST = "analyst", _("Digitized by analyst")
