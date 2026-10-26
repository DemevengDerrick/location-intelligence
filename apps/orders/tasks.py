from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from .models import Message, Order


def _context(order, **extra):
    return {
        "order": order,
        "customer": order.customer,
        "ref": str(order.public_id)[:8],
        "site_name": settings.SITE_NAME,
        **extra,
    }


def _send(template, context, recipients, language):
    with translation.override(language):
        # URLs are reversed inside the override so links use the recipient's language.
        context["order_link"] = settings.SITE_URL + reverse(
            "portal:order", args=[context["order"].public_id]
        )
        subject = render_to_string(f"emails/{template}_subject.txt", context).strip()
        body = render_to_string(f"emails/{template}.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_status_email(order_id, status):
    """One email per status change, in the customer's language (FR-21)."""
    order = Order.objects.select_related("customer").get(pk=order_id)
    _send(
        "order_status",
        _context(order, status=status),
        [order.customer.email],
        order.customer.language,
    )


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_message_reply(message_id):
    message = Message.objects.select_related("order__customer").get(pk=message_id)
    order = message.order
    _send(
        "message_reply",
        _context(order, message=message),
        [order.customer.email],
        order.customer.language,
    )


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def notify_staff_of_message(message_id):
    if not settings.ADMIN_NOTIFICATION_EMAILS:
        return
    message = Message.objects.select_related("order__customer").get(pk=message_id)
    order = message.order
    context = _context(
        order,
        message=message,
        admin_link=f"{settings.SITE_URL}/fr/admin/orders/order/{order.pk}/change/",
    )
    _send("message_to_staff", context, settings.ADMIN_NOTIFICATION_EMAILS, settings.LANGUAGE_CODE)
