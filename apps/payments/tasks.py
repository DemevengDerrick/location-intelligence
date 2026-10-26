from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation

from .models import Payment


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def send_receipt(payment_id):
    """Automatic receipt in the customer's language (FR-16)."""
    payment = Payment.objects.select_related("order__customer").get(pk=payment_id)
    customer = payment.order.customer
    with translation.override(customer.language):
        context = {
            "payment": payment,
            "order": payment.order,
            "customer": customer,
            "site_name": settings.SITE_NAME,
            "site_url": settings.SITE_URL,
            "order_url": reverse("portal:order", args=[payment.order.public_id]),
        }
        subject = render_to_string("emails/receipt_subject.txt", context).strip()
        body = render_to_string("emails/receipt.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [customer.email])
