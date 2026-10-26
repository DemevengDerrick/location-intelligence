from django.contrib import admin
from modeltranslation.admin import TranslationAdmin

from .models import AnalysisRun, FindingTemplate, ModuleResult


class ModuleResultInline(admin.TabularInline):
    model = ModuleResult
    extra = 0
    fields = ["module", "status", "rating", "ran_at"]
    readonly_fields = fields


@admin.register(AnalysisRun)
class AnalysisRunAdmin(admin.ModelAdmin):
    list_display = ["parcel", "status", "started_at", "finished_at"]
    list_filter = ["status"]
    raw_id_fields = ["parcel"]
    inlines = [ModuleResultInline]


@admin.register(ModuleResult)
class ModuleResultAdmin(admin.ModelAdmin):
    list_display = ["run", "module", "status", "rating", "ran_at"]
    list_filter = ["module", "status", "rating"]
    raw_id_fields = ["run"]


@admin.register(FindingTemplate)
class FindingTemplateAdmin(TranslationAdmin):
    """Report wording per module and rating. Placeholders such as {area} are filled in."""

    list_display = ["module", "rating", "text"]
    list_filter = ["module", "rating"]
