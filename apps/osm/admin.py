from django.contrib import admin, messages
from django.utils.translation import gettext_lazy as _

from .models import OsmImport
from .tasks import refresh_osm


@admin.register(OsmImport)
class OsmImportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "data_timestamp", "status", "counts", "finished_at")
    list_filter = ("status",)
    readonly_fields = [f.name for f in OsmImport._meta.fields]
    actions = ["refresh_now"]

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Download and load the latest extract now"))
    def refresh_now(self, request, queryset):
        refresh_osm.delay()
        self.message_user(request, _("The refresh runs in the background."), messages.INFO)
