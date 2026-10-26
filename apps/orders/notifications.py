"""Emails triggered by order events (FR-21) and by messages on an order (FR-20)."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Message, Order, OrderStatus
from .status import order_status_changed
from .tasks import notify_staff_of_message, send_message_reply, send_status_email

# The payment receipt already tells the customer their order is paid and what happens next,
# so these steps of the payment cascade don't get a separate email.
COVERED_BY_RECEIPT = {
    (OrderStatus.SUBMITTED, OrderStatus.PAID),
    (OrderStatus.PAID, OrderStatus.PROCESSING),
    (OrderStatus.PAID, OrderStatus.NEEDS_GEOREFERENCING),
}


@receiver(order_status_changed, sender=Order)
def email_customer_on_status_change(sender, order, old_status, new_status, **kwargs):
    if (old_status, new_status) in COVERED_BY_RECEIPT:
        return
    transaction.on_commit(lambda: send_status_email.delay(order.pk, new_status))


@receiver(post_save, sender=Message)
def email_on_new_message(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.author_id == instance.order.customer_id:
        transaction.on_commit(lambda: notify_staff_of_message.delay(instance.pk))
    else:
        transaction.on_commit(lambda: send_message_reply.delay(instance.pk))
