from django.contrib.gis import admin
from modeltranslation.admin import TranslationAdmin

from .models import Incident, IncidentSource, Source, SourceItem


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["name", "source_type", "language", "is_active", "last_crawled_at"]
    list_filter = ["source_type", "language", "is_active"]
    search_fields = ["name", "url"]


@admin.register(SourceItem)
class SourceItemAdmin(admin.ModelAdmin):
    list_display = ["title", "outlet", "published_at", "retrieved_at"]
    list_filter = ["source"]
    search_fields = ["title", "url"]
    date_hierarchy = "published_at"


class IncidentSourceInline(admin.TabularInline):
    model = IncidentSource
    extra = 0
    raw_id_fields = ["source_item"]


@admin.register(Incident)
class IncidentAdmin(TranslationAdmin, admin.GISModelAdmin):
    list_display = ["incident_type", "event_date", "precision", "is_official_act", "review_status"]
    list_filter = ["review_status", "incident_type", "precision", "is_official_act"]
    search_fields = ["summary_fr", "summary_en"]
    date_hierarchy = "event_date"
    raw_id_fields = ["merged_into"]
    inlines = [IncidentSourceInline]
