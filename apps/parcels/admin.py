from django.contrib.gis import admin

from .models import Parcel, ParcelGeometryHistory


class GeometryHistoryInline(admin.TabularInline):
    model = ParcelGeometryHistory
    extra = 0
    fields = ["input_method", "replaced_at", "replaced_by"]
    readonly_fields = fields
    can_delete = False


@admin.register(Parcel)
class ParcelAdmin(admin.GISModelAdmin):
    list_display = ["order", "input_method", "quartier", "commune", "computed_area_m2"]
    list_filter = ["input_method", "region", "is_approximate"]
    search_fields = ["order__public_id", "quartier", "commune"]
    readonly_fields = ["computed_area_m2"]
    raw_id_fields = ["order"]
    inlines = [GeometryHistoryInline]
