from django.contrib.gis import admin

from .models import FieldJob, FieldObservation, Partner


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ["name", "profession", "registration_number", "status"]
    list_filter = ["profession", "status"]
    search_fields = ["name", "registration_number"]
    raw_id_fields = ["user"]


class FieldObservationInline(admin.TabularInline):
    model = FieldObservation
    extra = 0
    fields = ["kind", "taken_at", "file", "distance_from_parcel_m"]


@admin.register(FieldJob)
class FieldJobAdmin(admin.ModelAdmin):
    list_display = ["order", "partner", "status", "due_date", "fee_amount", "payout_status"]
    list_filter = ["status", "payout_status"]
    raw_id_fields = ["order", "partner"]
    inlines = [FieldObservationInline]


@admin.register(FieldObservation)
class FieldObservationAdmin(admin.GISModelAdmin):
    list_display = ["job", "kind", "taken_at", "distance_from_parcel_m"]
    list_filter = ["kind"]
    raw_id_fields = ["job"]
