from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import admin, messages
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from apps.accounts import roles
from apps.accounts.permissions import has_role

from . import services
from .models import DiscountCode, Payment, PaymentStatus, Refund, WebhookEvent


class RefundForm(forms.Form):
    amount = forms.DecimalField(label=_("Amount to refund"), min_value=Decimal("0.01"))
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea(attrs={"rows": 3}))


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0
    fields = ["created_at", "amount", "reason", "provider_reference", "created_by"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "order",
        "method",
        "provider",
        "amount",
        "currency",
        "status",
        "refunded_amount",
    ]
    list_filter = ["status", "method", "provider", "currency"]
    search_fields = [
        "provider_reference",
        "public_id",
        "order__public_id",
        "order__customer__email",
    ]
    date_hierarchy = "created_at"
    readonly_fields = [
        "public_id",
        "order",
        "provider",
        "method",
        "provider_reference",
        "amount",
        "currency",
        "discount_code",
        "discount_amount",
        "status",
        "succeeded_at",
        "refunded_amount",
        "raw_webhook",
    ]
    inlines = [RefundInline]
    actions = ["refund_payment"]

    def has_add_permission(self, request):
        return False  # payments come from providers or the order's "mark as paid" action

    def has_delete_permission(self, request, obj=None):
        return False

    def has_refund_permission(self, request):
        return has_role(request.user, roles.ADMIN)

    @admin.action(description=_("Refund the selected payment"), permissions=["refund"])
    def refund_payment(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, _("Select exactly one payment to refund."), messages.ERROR)
            return None
        payment = queryset.get()
        if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED):
            self.message_user(
                request, _("Only successful payments can be refunded."), messages.ERROR
            )
            return None

        form = RefundForm(
            request.POST if "apply" in request.POST else None,
            initial={"amount": payment.refundable_amount},
        )
        if form.is_valid():
            try:
                services.refund(
                    payment,
                    amount=form.cleaned_data["amount"],
                    reason=form.cleaned_data["reason"],
                    actor=request.user,
                    request=request,
                )
            except (services.PaymentError, ValueError, InvalidOperation) as exc:
                self.message_user(request, str(exc), messages.ERROR)
            except Exception as exc:  # provider errors (e.g. Stripe) must reach the admin
                self.message_user(
                    request, _("Refund failed: %(error)s") % {"error": exc}, messages.ERROR
                )
            else:
                self.message_user(request, _("Refund recorded."), messages.SUCCESS)
            return None
        return TemplateResponse(
            request,
            "admin/payments/refund.html",
            {
                **self.admin_site.each_context(request),
                "title": _("Refund payment"),
                "payment": payment,
                "form": form,
                "opts": self.model._meta,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "action_name": "refund_payment",
                "object_pk": payment.pk,
            },
        )


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["received_at", "provider", "event_type", "event_id", "outcome", "processed_at"]
    list_filter = ["provider", "event_type", "outcome"]
    search_fields = ["event_id"]
    readonly_fields = [f.name for f in WebhookEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AdminRoleOnlyMixin:
    """Visible and editable only by the admin role (prices and discounts are FR-15/FR-49)."""

    def _is_admin(self, request):
        return has_role(request.user, roles.ADMIN)

    def has_module_permission(self, request):
        return self._is_admin(request)

    def has_view_permission(self, request, obj=None):
        return self._is_admin(request)

    def has_add_permission(self, request):
        return self._is_admin(request)

    def has_change_permission(self, request, obj=None):
        return self._is_admin(request)

    def has_delete_permission(self, request, obj=None):
        return self._is_admin(request)


@admin.register(DiscountCode)
class DiscountCodeAdmin(AdminRoleOnlyMixin, admin.ModelAdmin):
    list_display = [
        "code",
        "kind",
        "value",
        "currency",
        "times_used",
        "usage_limit",
        "expires_at",
        "is_active",
    ]
    list_filter = ["kind", "is_active"]
    search_fields = ["code"]
    readonly_fields = ["times_used"]
