from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.analysis.tasks import start_analysis
from apps.core.models import AuditLog
from apps.payments.models import Payment
from apps.payments.services import mark_paid_manually

from . import service_levels
from .models import Attachment, IntakeDraft, Message, Order, OrderStatus


class RegionFilter(admin.SimpleListFilter):
    title = _("region")
    parameter_name = "region"

    def lookups(self, request, model_admin):
        from apps.parcels.models import Parcel

        regions = Parcel.objects.exclude(region="").values_list("region", flat=True).distinct()
        return [(r, r) for r in sorted(regions)]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(parcels__region=self.value()).distinct()
        return queryset


class DeadlineFilter(admin.SimpleListFilter):
    """The customer's own deadline, if they gave one."""

    title = _("customer deadline")
    parameter_name = "deadline"

    def lookups(self, request, model_admin):
        return [
            ("past", _("Passed")),
            ("week", _("In the next 7 days")),
            ("later", _("Later")),
            ("none", _("None given")),
        ]

    def queryset(self, request, queryset):
        today = timezone.localdate()
        week = today + timedelta(days=7)
        return {
            "past": queryset.filter(deadline__lt=today),
            "week": queryset.filter(deadline__gte=today, deadline__lte=week),
            "later": queryset.filter(deadline__gt=week),
            "none": queryset.filter(deadline__isnull=True),
        }.get(self.value(), queryset)


class AgeFilter(admin.SimpleListFilter):
    """Time since payment."""

    title = _("age since payment")
    parameter_name = "age"

    def lookups(self, request, model_admin):
        return [
            ("1", _("Under 1 day")),
            ("3", _("1 to 3 days")),
            ("7", _("3 to 7 days")),
            ("older", _("Over 7 days")),
        ]

    def queryset(self, request, queryset):
        now = timezone.now()
        day = timedelta(days=1)
        return {
            "1": queryset.filter(paid_at__gte=now - day),
            "3": queryset.filter(paid_at__lt=now - day, paid_at__gte=now - 3 * day),
            "7": queryset.filter(paid_at__lt=now - 3 * day, paid_at__gte=now - 7 * day),
            "older": queryset.filter(paid_at__lt=now - 7 * day),
        }.get(self.value(), queryset)


class OverdueFilter(admin.SimpleListFilter):
    """FR-36: open orders past their service-level target."""

    title = _("service level")
    parameter_name = "overdue"

    def lookups(self, request, model_admin):
        return [("yes", _("Past target")), ("no", _("Within target"))]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(service_levels.overdue_filter())
        if self.value() == "no":
            return queryset.filter(status__in=service_levels.OPEN).exclude(
                service_levels.overdue_filter()
            )
        return queryset


class MarkPaidForm(forms.Form):
    reference = forms.CharField(
        label=_("Bank transfer reference"),
        max_length=200,
        help_text=_("As shown on the bank statement."),
    )


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ["created_at", "method", "provider", "amount", "currency", "status", "refunded_amount"]
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    fields = ["kind", "file", "original_name", "size_bytes"]
    readonly_fields = ["size_bytes"]


class MessageInline(admin.StackedInline):
    model = Message
    extra = 0
    fields = ["author", "body", "created_at", "read_at"]
    readonly_fields = ["author", "created_at", "read_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        "public_id",
        "customer",
        "status",
        "tier",
        "region",
        "paid_at",
        "due",
        "deadline",
        "price_amount",
        "currency",
    ]
    list_filter = [
        OverdueFilter,
        "status",
        "tier",
        RegionFilter,
        DeadlineFilter,
        AgeFilter,
        "currency",
    ]
    search_fields = ["public_id", "customer__email"]
    date_hierarchy = "created_at"
    raw_id_fields = ["customer", "organization"]
    # Status changes go through apps.orders.status (audited, emails), never a plain edit.
    readonly_fields = ["status", "paid_at", "delivered_at", "terms_version", "terms_accepted_at"]
    inlines = [PaymentInline, AttachmentInline, MessageInline]
    actions = ["mark_paid", "run_analysis"]
    change_form_template = "admin/orders/order/change_form.html"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("customer").prefetch_related("parcels")

    @admin.display(description=_("region"))
    def region(self, obj):
        return ", ".join(sorted({p.region for p in obj.parcels.all() if p.region})) or "–"

    @admin.display(description=_("due"), ordering="paid_at")
    def due(self, obj):
        due = service_levels.due_at(obj)
        if due is None:
            return "–"
        text = due.strftime("%Y-%m-%d %H:%M")
        if service_levels.is_overdue(obj):
            return format_html('<strong style="color:#b91c1c">⚠ {} ({})</strong>', text, _("late"))
        return text

    def change_view(self, request, object_id, form_url="", extra_context=None):
        order = self.get_object(request, object_id)
        if order is not None:
            extra_context = {**(extra_context or {}), **self._order_panels(order)}
        return super().change_view(request, object_id, form_url, extra_context)

    def _order_panels(self, order):
        """FR-37: pipeline status per module, the audit trail and the staff tools."""
        from apps.analysis.models import AnalysisRun
        from apps.parcels.models import Parcel
        from apps.payments.models import Payment
        from apps.reports.models import Report

        run = (
            AnalysisRun.objects.filter(parcel__order=order)
            .order_by("-created_at")
            .prefetch_related("module_results")
            .first()
        )
        report = Report.objects.filter(order=order).first()
        targets = Q(target_type=ContentType.objects.get_for_model(Order), target_id=str(order.pk))
        for model, ids in (
            (Parcel, order.parcels.values_list("pk", flat=True)),
            (Payment, order.payments.values_list("pk", flat=True)),
            (Report, [report.pk] if report else []),
        ):
            targets |= Q(
                target_type=ContentType.objects.get_for_model(model),
                target_id__in=[str(pk) for pk in ids],
            )
        return {
            "run": run,
            "module_results": run.module_results.order_by("pk") if run else [],
            "audit_entries": AuditLog.objects.filter(targets).select_related("actor")[:100],
            "parcels": order.parcels.all(),
            "report": report,
            "due": service_levels.due_at(order),
            "overdue": service_levels.is_overdue(order),
            "review_url": reverse("admin:reports_report_review", args=[report.pk])
            if report
            else None,
        }

    def save_formset(self, request, form, formset, change):
        if formset.model is Message:
            for message in formset.save(commit=False):
                if message.author_id is None:
                    message.author = request.user  # a reply to the customer
                message.save()
            formset.save_m2m()
            return
        super().save_formset(request, form, formset, change)

    def has_run_analysis_permission(self, request):
        return has_role(request.user, roles.ANALYST)

    @admin.action(description=_("Run the analysis"), permissions=["run_analysis"])
    def run_analysis(self, request, queryset):
        started = 0
        for order in queryset.filter(status__in=[OrderStatus.PROCESSING, OrderStatus.IN_REVIEW]):
            start_analysis.delay(order.pk)
            started += 1
        self.message_user(
            request,
            _("Analysis started for %(n)s order(s). Orders must be processing or in review.")
            % {"n": started},
            messages.SUCCESS if started else messages.WARNING,
        )

    def has_mark_paid_permission(self, request):
        return has_role(request.user, roles.ADMIN)

    @admin.action(description=_("Mark as paid (bank transfer)"), permissions=["mark_paid"])
    def mark_paid(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, _("Select exactly one order."), messages.ERROR)
            return None
        order = queryset.get()
        if order.status != OrderStatus.SUBMITTED:
            self.message_user(
                request, _("Only unpaid orders can be marked as paid."), messages.ERROR
            )
            return None
        form = MarkPaidForm(request.POST if "apply" in request.POST else None)
        if form.is_valid():
            mark_paid_manually(
                order, reference=form.cleaned_data["reference"], actor=request.user, request=request
            )
            self.message_user(request, _("Order marked as paid."), messages.SUCCESS)
            return None
        return TemplateResponse(
            request,
            "admin/orders/mark_paid.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Mark as paid"),
                "order": order,
                "form": form,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "action_name": "mark_paid",
                "object_pk": order.pk,
            },
        )


@admin.register(IntakeDraft)
class IntakeDraftAdmin(admin.ModelAdmin):
    """Read-only view of order-form progress, e.g. to follow up abandoned orders."""

    list_display = [
        "token",
        "user",
        "contact_name",
        "input_method",
        "tier",
        "step_reached",
        "updated_at",
    ]
    list_filter = ["step_reached", "input_method", "tier"]
    search_fields = ["token", "user__email", "contact_name", "contact_phone"]
    date_hierarchy = "updated_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
