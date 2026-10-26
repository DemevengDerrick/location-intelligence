from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .audit import log_action
from .models import SiteSetting
from .site_settings import clear_setting_cache


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    log_action("auth.login", actor=user, target=user, request=request)


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request=None, **kwargs):
    log_action(
        "auth.login_failed",
        data={"email": credentials.get("email") or credentials.get("username", "")},
        request=request,
    )


@receiver([post_save, post_delete], sender=SiteSetting)
def refresh_setting_cache(sender, instance, **kwargs):
    clear_setting_cache(instance.key)
