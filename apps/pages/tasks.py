from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation

from .models import Lead


@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
def notify_new_lead(lead_id):
    recipients = settings.ADMIN_NOTIFICATION_EMAILS
    if not recipients:
        return
    lead = Lead.objects.get(pk=lead_id)
    with translation.override(settings.LANGUAGE_CODE):
        context = {"lead": lead, "admin_url": f"{settings.SITE_URL}/fr/admin/pages/lead/{lead.pk}/"}
        subject = render_to_string("emails/new_lead_subject.txt", context).strip()
        body = render_to_string("emails/new_lead.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
