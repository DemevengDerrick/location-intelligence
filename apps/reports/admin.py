from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.analysis.models import Rating
from apps.analysis.modules import MODULES
from apps.analysis.style import RATING_COLOURS
from apps.analysis.tasks import start_analysis
from apps.orders.models import OrderStatus

from . import services
from .models import Report, ReportVersion


class ReportVersionInline(admin.TabularInline):
    model = ReportVersion
    extra = 0
    fields = ["number", "language", "sha256", "approved_by", "approved_at", "pdf"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["reference", "order", "order_status", "latest_number", "review_link"]
    search_fields = ["reference", "order__public_id", "order__customer__email"]
    list_filter = ["order__status"]
    raw_id_fields = ["order", "run"]
    readonly_fields = ["reference", "draft"]
    inlines = [ReportVersionInline]

    @admin.display(description=_("order status"))
    def order_status(self, obj):
        return obj.order.get_status_display()

    @admin.display(description=_("review"))
    def review_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:reports_report_review", args=[obj.pk]),
            _("Open review"),
        )

    def get_urls(self):
        review = self.admin_site.admin_view(self.review_view)
        return [path("<int:pk>/review/", review, name="reports_report_review"), *super().get_urls()]

    def review_view(self, request, pk):
        """FR-41/42: findings and ratings beside their maps; edit, override, hide, approve."""
        if not has_role(request.user, roles.ANALYST):
            raise PermissionDenied
        report = get_object_or_404(Report.objects.select_related("order"), pk=pk)
        order = report.order
        action = request.POST.get("action") if request.method == "POST" else None

        if action in ("save", "approve"):
            try:
                services.apply_edits(report, request.POST)
                if action == "approve":
                    number = services.approve(report, analyst=request.user, request=request)
                    messages.success(
                        request,
                        _("Version %(n)s approved and delivered to the customer.") % {"n": number},
                    )
                    return redirect("admin:reports_report_review", pk=pk)
                messages.success(request, _("Draft saved."))
                return redirect("admin:reports_report_review", pk=pk)
            except services.ReviewError as exc:
                messages.error(request, str(exc))
        elif action == "rerun" and order.status in (OrderStatus.PROCESSING, OrderStatus.IN_REVIEW):
            start_analysis.delay(order.pk)
            messages.info(
                request,
                _(
                    "Analysis restarted. The draft will be rebuilt when it finishes; "
                    "current edits will be replaced."
                ),
            )
            return redirect("admin:reports_report_review", pk=pk)
        elif action == "reopen" and order.status == OrderStatus.DELIVERED:
            services.reopen(report, analyst=request.user, request=request)
            messages.info(request, _("Report reopened. Approving again creates a new version."))
            return redirect("admin:reports_report_review", pk=pk)

        findings = []
        for i, finding in enumerate(report.draft.get("findings", [])):
            maps = finding.get("maps", {})
            findings.append(
                {
                    **finding,
                    "index": i,
                    "title": MODULES[finding["module"]].title,
                    "colour": RATING_COLOURS[finding["rating"]],
                    "map_urls": [
                        default_storage.url(by_language["en"])
                        for by_language in maps.values()
                        if by_language.get("en")
                    ],
                }
            )
        return TemplateResponse(
            request,
            "admin/reports/review.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Review report %(ref)s") % {"ref": str(report.reference)[:8]},
                "report": report,
                "order": order,
                "parcel": order.parcels.first(),
                "findings": findings,
                "ratings": Rating.choices,
                "editable": order.status == OrderStatus.IN_REVIEW,
                "opts": self.model._meta,
                "versions": report.versions.order_by("-number", "language"),
            },
        )
