import json

from django import forms
from django.contrib import admin, messages
from django.contrib.gis import admin as gis_admin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin

from apps.core import llm
from apps.core.maps import basemap_url

from . import geocode, manual, services
from .models import (
    AreaSearch,
    Incident,
    IncidentSource,
    IncidentType,
    ReviewStatus,
    Source,
    SourceItem,
    UnmatchedPlace,
)


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["name", "source_type", "language", "is_active", "has_search", "last_crawled_at"]
    list_filter = ["source_type", "language", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["name", "url"]

    @admin.display(boolean=True, description=_("search feed"))
    def has_search(self, source):
        return bool(source.search_url)


class AddItemForm(forms.Form):
    url = forms.URLField(label=_("Article or notice URL"), required=False, assume_scheme="https")
    pdf = forms.FileField(label=_("Or a PDF notice"), required=False, help_text=_("10 MB maximum."))
    title = forms.CharField(
        label=_("Title"), required=False, help_text=_("Taken from the page or PDF if empty.")
    )
    outlet = forms.CharField(label=_("Outlet or issuer"), required=False)
    published_at = forms.DateField(label=_("Publication date"), required=False)

    def clean(self):
        data = super().clean()
        if not data.get("url") and not data.get("pdf"):
            raise forms.ValidationError(_("Give a URL or upload a PDF."))
        pdf = data.get("pdf")
        if pdf and pdf.size > 10 * 1024 * 1024:
            raise forms.ValidationError(_("The PDF is larger than 10 MB."))
        return data


@admin.register(SourceItem)
class SourceItemAdmin(admin.ModelAdmin):
    list_display = ["title", "outlet", "published_at", "extracted", "incident_count"]
    list_filter = ["source", "language", ("extracted_at", admin.EmptyFieldListFilter)]
    search_fields = ["title", "url", "outlet"]
    date_hierarchy = "published_at"
    readonly_fields = ["content_hash", "retrieved_at", "extracted_at", "extraction_error"]
    actions = ["extract", "create_incident"]
    change_list_template = "admin/incidents/sourceitem/change_list.html"

    @admin.display(boolean=True, description=_("extracted"))
    def extracted(self, item):
        return item.extracted_at is not None

    @admin.display(description=_("incidents"))
    def incident_count(self, item):
        return item.incidents.count()

    def get_urls(self):
        return [
            path(
                "add-by-url/",
                self.admin_site.admin_view(self.add_by_url),
                name="incidents_sourceitem_add_by_url",
            ),
            *super().get_urls(),
        ]

    def add_by_url(self, request):
        """FR-23: add an item by pasting a URL or uploading a PDF notice."""
        form = AddItemForm(request.POST or None, request.FILES or None)
        if request.method == "POST" and form.is_valid():
            try:
                item, created = manual.add_item(**form.cleaned_data)
            except manual.ManualItemError as exc:
                form.add_error(None, str(exc))
            else:
                if created:
                    messages.success(request, _("Item added."))
                else:
                    messages.info(request, _("This item was already collected."))
                return redirect("admin:incidents_sourceitem_change", item.pk)
        return TemplateResponse(
            request,
            "admin/incidents/sourceitem/add_by_url.html",
            {**self.admin_site.each_context(request), "title": _("Add an item"), "form": form},
        )

    @admin.action(description=_("Extract incidents with the LLM"))
    def extract(self, request, queryset):
        if not llm.available():
            self.message_user(
                request,
                _("LLM extraction is off: set ANTHROPIC_API_KEY. Create incidents by hand."),
                messages.WARNING,
            )
            return
        from .tasks import extract_items

        queryset.update(extracted_at=None)
        extract_items.delay(list(queryset.values_list("pk", flat=True)))
        self.message_user(
            request, _("Extraction queued for %(n)s item(s).") % {"n": queryset.count()}
        )

    @admin.action(description=_("Create an incident by hand from the item"))
    def create_incident(self, request, queryset):
        item = queryset.first()
        incident = services.incident_from_item(item)
        self.message_user(request, _("Incident created: fill in its type, summary and place."))
        return redirect("admin:incidents_incident_change", incident.pk)


class IncidentSourceInline(admin.TabularInline):
    model = IncidentSource
    extra = 0
    raw_id_fields = ["source_item"]


class ConfirmNamesForm(forms.Form):
    no_private_names = forms.BooleanField(
        label=_(
            "I have checked that these summaries name no private individual (FR-31). Public "
            "bodies and officials acting in office may be named."
        )
    )


@admin.register(Incident)
class IncidentAdmin(TranslationAdmin, gis_admin.GISModelAdmin):
    list_display = [
        "incident_type",
        "event_date",
        "place",
        "precision",
        "is_official_act",
        "confidence",
        "review_status",
    ]
    list_filter = ["review_status", "incident_type", "precision", "is_official_act"]
    search_fields = ["summary_fr", "summary_en", "place__name"]
    date_hierarchy = "event_date"
    raw_id_fields = ["merged_into", "place"]
    readonly_fields = ["reviewed_by", "reviewed_at", "confidence"]
    inlines = [IncidentSourceInline]
    actions = ["approve", "reject", "merge", "mark_official", "relocate"]
    change_list_template = "admin/incidents/incident/change_list.html"

    def get_urls(self):
        return [
            path("map/", self.admin_site.admin_view(self.map_view), name="incidents_incident_map"),
            path(
                "map/data/",
                self.admin_site.admin_view(self.map_data),
                name="incidents_incident_map_data",
            ),
            *super().get_urls(),
        ]

    @admin.action(description=_("Approve (shown in reports)"))
    def approve(self, request, queryset):
        form = ConfirmNamesForm(request.POST if "confirm" in request.POST else None)
        if form.is_valid():
            count = services.approve(queryset, request.user)
            self.message_user(request, _("%(n)s incident(s) approved.") % {"n": count})
            return None
        return TemplateResponse(
            request,
            "admin/incidents/incident/approve.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Approve incidents"),
                "incidents": queryset,
                "form": form,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "opts": self.model._meta,
            },
        )

    @admin.action(description=_("Reject"))
    def reject(self, request, queryset):
        count = queryset.update(
            review_status=ReviewStatus.REJECTED,
            reviewed_by=request.user,
            reviewed_at=timezone.now(),
        )
        self.message_user(request, _("%(n)s incident(s) rejected.") % {"n": count})

    @admin.action(description=_("Merge duplicates into the oldest selected"))
    def merge(self, request, queryset):
        if queryset.count() < 2:
            self.message_user(request, _("Select at least two incidents."), messages.WARNING)
            return
        kept = services.merge(queryset, request.user)
        self.message_user(request, _("Merged into incident %(pk)s.") % {"pk": kept.pk})

    @admin.action(description=_("Mark as official act"))
    def mark_official(self, request, queryset):
        queryset.update(is_official_act=True)

    @admin.action(description=_("Locate again from the place names"))
    def relocate(self, request, queryset):
        for incident in queryset:
            geocode.locate(incident)
            incident.save(update_fields=["place", "geometry", "precision", "updated_at"])
        self.message_user(request, _("%(n)s incident(s) located again.") % {"n": queryset.count()})

    def map_view(self, request):
        """FR-35: every incident on a map, filterable by type, date and status."""
        return TemplateResponse(
            request,
            "admin/incidents/incident/map.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Incident map"),
                "types": IncidentType.choices,
                "statuses": ReviewStatus.choices,
                "config": {
                    "basemapUrl": basemap_url(),
                    "dataUrl": reverse("admin:incidents_incident_map_data"),
                    "changeUrl": reverse("admin:incidents_incident_change", args=[0]),
                },
            },
        )

    def map_data(self, request):
        incidents = services.filtered(request.GET).select_related("place")
        features = []
        for incident in incidents[:5000]:
            point = incident.geometry.point_on_surface
            features.append(
                {
                    "type": "Feature",
                    "geometry": json.loads(point.geojson),
                    "properties": {
                        "id": incident.pk,
                        "type": incident.get_incident_type_display(),
                        "type_key": incident.incident_type,
                        "date": incident.event_date.isoformat() if incident.event_date else "",
                        "status": incident.get_review_status_display(),
                        "precision": incident.get_precision_display(),
                        "place": incident.place.name if incident.place else "",
                        "official": incident.is_official_act,
                        "summary": incident.summary_fr or incident.summary_en or "",
                    },
                }
            )
        return JsonResponse({"type": "FeatureCollection", "features": features})


@admin.register(UnmatchedPlace)
class UnmatchedPlaceAdmin(admin.ModelAdmin):
    """FR-28: names the gazetteer does not know. Map one to a place to add it as an alias."""

    list_display = ["name", "occurrences", "resolved_place", "ignored", "example"]
    list_filter = ["ignored", ("resolved_place", admin.EmptyFieldListFilter)]
    search_fields = ["name"]
    autocomplete_fields = ["resolved_place"]
    raw_id_fields = ["example"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.resolved_place_id and "resolved_place" in form.changed_data:
            relocated = geocode.resolve(obj)
            self.message_user(
                request,
                _("“%(name)s” added as an alias of %(place)s; %(n)s incident(s) located again.")
                % {"name": obj.name, "place": obj.resolved_place, "n": relocated},
            )


@admin.register(AreaSearch)
class AreaSearchAdmin(admin.ModelAdmin):
    list_display = ["place", "provider", "searched_at", "ok", "item_count"]
    list_filter = ["provider", "ok"]
    search_fields = ["place__name"]
    readonly_fields = ["place", "provider", "query", "searched_at", "ok", "error", "items"]
    actions = ["expire"]

    @admin.display(description=_("items"))
    def item_count(self, search):
        return search.items.count()

    @admin.action(description=_("Search again on the next order"))
    def expire(self, request, queryset):
        queryset.update(searched_at=None)

    def has_add_permission(self, request):
        return False
