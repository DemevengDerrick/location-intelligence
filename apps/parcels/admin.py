import json

from django.conf import settings
from django.contrib import messages
from django.contrib.gis import admin
from django.contrib.gis.geos import GEOSException, GEOSGeometry
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.core.audit import log_action
from apps.core.maps import basemap_url
from apps.orders.models import Attachment, AttachmentKind

from . import services
from .georeference import fit_affine
from .models import Parcel, ParcelGeometryHistory
from .parsers import CRS_CHOICES, GeometryInputError, parse_geometry_file
from .plans import render_plan

PLAN_TYPES = ("image/", "application/pdf")


class GeometryHistoryInline(admin.TabularInline):
    model = ParcelGeometryHistory
    extra = 0
    fields = ["input_method", "replaced_at", "replaced_by"]
    readonly_fields = fields
    can_delete = False


@admin.register(Parcel)
class ParcelAdmin(admin.GISModelAdmin):
    list_display = [
        "order",
        "input_method",
        "quartier",
        "commune",
        "computed_area_m2",
        "editor_link",
    ]
    list_filter = ["input_method", "region", "is_approximate"]
    search_fields = ["order__public_id", "quartier", "commune"]
    readonly_fields = ["computed_area_m2"]
    raw_id_fields = ["order"]
    inlines = [GeometryHistoryInline]

    @admin.display(description=gettext_lazy("boundary"))
    def editor_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:parcels_parcel_geometry", args=[obj.pk]),
            _("Open the editor"),
        )

    def get_urls(self):
        view = self.admin_site.admin_view
        return [
            path("<int:pk>/geometry/", view(self.geometry_view), name="parcels_parcel_geometry"),
            path(
                "<int:pk>/plan/<int:attachment_pk>.png",
                view(self.plan_image),
                name="parcels_parcel_plan",
            ),
            path(
                "<int:pk>/georeference/",
                view(require_POST(self.georeference_view)),
                name="parcels_parcel_georeference",
            ),
            path(
                "<int:pk>/coordinates/",
                view(require_POST(self.coordinates_view)),
                name="parcels_parcel_coordinates",
            ),
            *super().get_urls(),
        ]

    # --- helpers --------------------------------------------------------------------------

    def _parcel(self, request, pk):
        if not has_role(request.user, roles.ANALYST):
            raise PermissionDenied
        return get_object_or_404(Parcel.objects.select_related("order"), pk=pk)

    @staticmethod
    def _plans(parcel):
        """Attachments that can be shown as a plan: site plans first, then other images/PDFs."""
        plans = [
            a
            for a in parcel.order.attachments.order_by("pk")
            if a.content_type.startswith(PLAN_TYPES) or a.kind == AttachmentKind.SITE_PLAN
        ]
        return sorted(plans, key=lambda a: a.kind != AttachmentKind.SITE_PLAN)

    def _plan(self, parcel, attachment_pk):
        return get_object_or_404(Attachment.objects.filter(order=parcel.order_id), pk=attachment_pk)

    # --- views ----------------------------------------------------------------------------

    def geometry_view(self, request, pk):
        """FR-38/39: draw or edit the boundary, type coordinates, georeference a site plan."""
        parcel = self._parcel(request, pk)
        order = parcel.order
        if request.method == "POST":
            try:
                geom = GEOSGeometry(request.POST.get("geometry") or "", srid=4326)
            except (GEOSException, ValueError, TypeError):
                messages.error(request, _("Draw the boundary on the map before saving."))
            else:
                try:
                    _parcel, warnings, started = services.save_boundary(
                        parcel,
                        geom,
                        actor=request.user,
                        request=request,
                        note=request.POST.get("note", "").strip(),
                    )
                except GeometryInputError as exc:
                    messages.error(request, str(exc))
                else:
                    for warning in warnings:
                        messages.warning(request, warning)
                    messages.success(
                        request,
                        _("Boundary saved. The analysis has restarted with the new boundary.")
                        if started
                        else _("Boundary saved."),
                    )
                    return redirect("admin:orders_order_change", order.pk)

        plans = self._plans(parcel)
        config = {
            "basemapUrl": basemap_url(),
            "attribution": settings.BASEMAP_ATTRIBUTION,
            "geometry": json.loads(parcel.geometry.geojson) if parcel.geometry else None,
            "approximate": parcel.is_approximate,
            "history": [json.loads(h.geometry.geojson) for h in parcel.geometry_history.all()[:5]],
            "plans": [
                {
                    "id": a.pk,
                    "name": a.original_name or a.file.name.rsplit("/", 1)[-1],
                    "url": reverse("admin:parcels_parcel_plan", args=[parcel.pk, a.pk]),
                    "georeference": a.georeference,
                }
                for a in plans
            ],
            "urls": {
                "georeference": reverse("admin:parcels_parcel_georeference", args=[parcel.pk]),
                "coordinates": reverse("admin:parcels_parcel_coordinates", args=[parcel.pk]),
            },
            "labels": {
                "pickPlan": _("Click a point on the plan."),
                "pickMap": _("Now click the same point on the map."),
                "needMore": _("Add at least 3 control points."),
                "exact": _("3 points fit exactly: add a 4th to check the fit."),
                "rmse": _("Fit error (RMSE): %(m)s m"),
                "remove": _("Remove"),
                "point": _("Point"),
                "residual": _("Error (m)"),
                "noShape": _("Draw the boundary on the map before saving."),
            },
        }
        return TemplateResponse(
            request,
            "admin/parcels/parcel/geometry.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Boundary of order %(ref)s") % {"ref": str(order.public_id)[:8]},
                "parcel": parcel,
                "order": order,
                "config": config,
                "history": parcel.geometry_history.select_related("replaced_by")[:10],
                "crs_choices": [
                    ("wgs84", _("Longitude, latitude (WGS 84)")),
                    ("utm32n", _("UTM zone 32N (easting, northing)")),
                    ("utm33n", _("UTM zone 33N (easting, northing)")),
                ],
                "opts": self.model._meta,
                "editable": order.status in services.EDITABLE,
            },
        )

    def plan_image(self, request, pk, attachment_pk):
        parcel = self._parcel(request, pk)
        attachment = self._plan(parcel, attachment_pk)
        with attachment.file.open("rb") as handle:
            data = handle.read()
        try:
            png, _width, _height = render_plan(
                data, attachment.content_type, attachment.original_name or attachment.file.name
            )
        except GeometryInputError as exc:
            return HttpResponse(str(exc), status=422, content_type="text/plain; charset=utf-8")
        response = HttpResponse(png, content_type="image/png")
        response["Cache-Control"] = "private, max-age=3600"
        return response

    def georeference_view(self, request, pk):
        parcel = self._parcel(request, pk)
        try:
            payload = json.loads(request.body or b"{}")
            attachment = self._plan(parcel, int(payload["attachment"]))
            width, height = float(payload["width"]), float(payload["height"])
            fit = fit_affine(payload.get("points") or [], width, height)
        except GeometryInputError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        except (KeyError, TypeError, ValueError):
            return JsonResponse({"error": _("The control points are incomplete.")}, status=400)
        attachment.georeference = {
            "points": payload["points"],
            "width": width,
            "height": height,
            **fit.as_json(),
        }
        attachment.save(update_fields=["georeference", "updated_at"])
        log_action(
            "parcel.plan_georeferenced",
            actor=request.user,
            target=parcel,
            request=request,
            data={
                "attachment": attachment.pk,
                "points": len(payload["points"]),
                "rmse_m": fit.rmse_m,
            },
        )
        return JsonResponse(fit.as_json())

    def coordinates_view(self, request, pk):
        self._parcel(request, pk)
        crs = request.POST.get("crs", "wgs84")
        if crs not in CRS_CHOICES:
            crs = "wgs84"
        text = request.POST.get("text", "")
        try:
            geom = parse_geometry_file(SimpleUploadedFile("coordinates.csv", text.encode()), crs)
        except GeometryInputError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        return JsonResponse({"geometry": json.loads(geom.geojson)})
