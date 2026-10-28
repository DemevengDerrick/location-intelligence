from modeltranslation.translator import TranslationOptions, register

from .models import Dataset


@register(Dataset)
class DatasetTranslationOptions(TranslationOptions):
    fields = ("use", "limitation")
