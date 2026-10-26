from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _


def _sync_roles(sender, using, **kwargs):
    from django.apps import apps
    from django.contrib.auth.management import create_permissions

    from .roles import sync_role_groups

    # post_migrate fires app by app, so permissions of apps listed after this one may not
    # exist yet. Create them all first (idempotent) before assigning them to role groups.
    for app_config in apps.get_app_configs():
        create_permissions(app_config, verbosity=0, using=using)
    sync_role_groups()


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = _("Accounts")

    def ready(self):
        from . import signals  # noqa: F401

        post_migrate.connect(_sync_roles, sender=self)
