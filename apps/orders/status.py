"""The only place order statuses change: checks the transition, stamps dates, audits it,
and announces it (emails hook in through `order_status_changed`)."""

from django.dispatch import Signal
from django.utils import timezone

from apps.core.audit import log_action

from .models import Order, OrderStatus

S = OrderStatus

ALLOWED = {
    S.SUBMITTED: {S.PAID, S.REFUNDED},
    S.PAID: {S.PROCESSING, S.NEEDS_GEOREFERENCING, S.REFUNDED},
    S.NEEDS_GEOREFERENCING: {S.PROCESSING, S.REFUNDED},
    S.PROCESSING: {S.IN_REVIEW, S.REFUNDED},
    S.IN_REVIEW: {S.DELIVERED, S.PROCESSING, S.REFUNDED},
    S.DELIVERED: {S.FIELD_VISIT_SCHEDULED, S.IN_REVIEW, S.REFUNDED},
    S.FIELD_VISIT_SCHEDULED: {S.FIELD_REPORT_DELIVERED, S.REFUNDED},
    S.FIELD_REPORT_DELIVERED: {S.REFUNDED},
    S.REFUNDED: set(),
}

# Sent after every change: sender=Order, order, old_status, new_status, actor.
order_status_changed = Signal()


class InvalidTransition(Exception):
    pass


def transition(order: Order, new_status, *, actor=None, request=None, note=""):
    old_status = order.status
    if new_status not in ALLOWED[old_status]:
        raise InvalidTransition(f"{old_status} → {new_status}")
    order.status = new_status
    fields = ["status", "updated_at"]
    if new_status == S.PAID and order.paid_at is None:
        order.paid_at = timezone.now()
        fields.append("paid_at")
    if new_status in (S.DELIVERED, S.FIELD_REPORT_DELIVERED):
        order.delivered_at = timezone.now()
        fields.append("delivered_at")
    order.save(update_fields=fields)
    log_action(
        "order.status",
        actor=actor,
        target=order,
        request=request,
        data={"from": old_status, "to": new_status, "note": note},
    )
    order_status_changed.send(
        sender=Order, order=order, old_status=old_status, new_status=new_status, actor=actor
    )
    return order
