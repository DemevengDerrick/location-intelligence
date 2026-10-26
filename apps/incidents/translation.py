from modeltranslation.translator import TranslationOptions, register

from .models import Incident


@register(Incident)
class IncidentTranslationOptions(TranslationOptions):
    fields = ("summary",)
