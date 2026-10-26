from django import forms
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.analysis.tasks import start_analysis
from apps.payments.models import Payment
from apps.payments.services import mark_paid_manually

from .models import Attachment, IntakeDraft, Message, Order, OrderStatus


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
        "currency",
        "price_amount",
        "created_at",
    ]
    list_filter = ["status", "tier", "currency"]
    search_fields = ["public_id", "customer__email"]
    date_hierarchy = "created_at"
    raw_id_fields = ["customer", "organization"]
    # Status changes go through apps.orders.status (audited, emails), never a plain edit.
    readonly_fields = ["status", "paid_at", "delivered_at", "terms_version", "terms_accepted_at"]
    inlines = [PaymentInline, AttachmentInline, MessageInline]
    actions = ["mark_paid", "run_analysis"]

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
