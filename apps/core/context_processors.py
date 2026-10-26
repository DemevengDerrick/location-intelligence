from django.conf import settings


def site(request):
    return {
        "SITE_NAME": settings.SITE_NAME,
        # Development only: where outgoing email (sign-in codes, receipts) can be read.
        "DEV_MAILBOX_URL": settings.DEV_MAILBOX_URL if settings.DEBUG else "",
    }
