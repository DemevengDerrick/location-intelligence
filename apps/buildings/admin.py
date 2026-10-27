from django.contrib import admin

from .models import BuildingRelease


@admin.register(BuildingRelease)
class BuildingReleaseAdmin(admin.ModelAdmin):
    list_display = ("created_at", "version", "status", "count", "finished_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in BuildingRelease._meta.fields]

    def has_add_permission(self, request):
        return False
