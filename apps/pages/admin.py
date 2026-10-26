from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import FAQItem, Lead, Page, SampleReport


@admin.register(Page)
class PageAdmin(TranslationAdmin):
    list_display = ["slug", "title", "version", "is_draft", "updated_at"]


@admin.register(FAQItem)
class FAQItemAdmin(TranslationAdmin):
    list_display = ["question", "sort_order", "is_published"]
    list_editable = ["sort_order", "is_published"]


@admin.register(SampleReport)
class SampleReportAdmin(TranslationAdmin):
    list_display = ["title", "sort_order", "is_published"]
    list_editable = ["sort_order", "is_published"]


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ["created_at", "name", "email", "phone", "language", "handled"]
    list_filter = ["handled", "language"]
    list_editable = ["handled"]
    search_fields = ["name", "email", "phone", "message"]
    readonly_fields = ["name", "email", "phone", "message", "language", "source_path"]
    date_hierarchy = "created_at"
