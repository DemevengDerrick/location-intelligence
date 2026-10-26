from modeltranslation.translator import TranslationOptions, register

from .models import FindingTemplate


@register(FindingTemplate)
class FindingTemplateTranslationOptions(TranslationOptions):
    fields = ("text",)
