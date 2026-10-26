from modeltranslation.translator import TranslationOptions, register

from .models import FAQItem, Page, SampleReport


@register(Page)
class PageTranslationOptions(TranslationOptions):
    fields = ("title", "body")


@register(FAQItem)
class FAQItemTranslationOptions(TranslationOptions):
    fields = ("question", "answer")


@register(SampleReport)
class SampleReportTranslationOptions(TranslationOptions):
    fields = ("title", "summary")
