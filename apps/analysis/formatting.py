"""Locale-aware number formatting shared by findings, chart titles and key figures."""

from django.utils.formats import number_format
from django.utils.translation import gettext as _


def fmt(value, decimals=None):
    """Format for the active language: 1 250,5 in French, 1,250.5 in English."""
    if value is None:
        return "–"
    if isinstance(value, bool):
        return _("yes") if value else _("no")
    if isinstance(value, int | float):
        if decimals is None:
            decimals = 0 if float(value).is_integer() or abs(value) >= 100 else 1
        # number_format truncates; round first so 1599.6 m² reads "1 600", not "1 599".
        return number_format(round(value, decimals), decimals, force_grouping=True)
    return str(value)
