from allauth.account.signals import user_signed_up
from django.contrib.auth.models import Group
from django.dispatch import receiver
from django.utils import translation

from . import roles


@receiver(user_signed_up)
def assign_customer_role(sender, request, user, **kwargs):
    """Every self-registered account (email or Google) starts as a customer."""
    user.groups.add(Group.objects.get_or_create(name=roles.CUSTOMER)[0])
    language = translation.get_language()
    if language and user.language != language:
        user.language = language
        user.save(update_fields=["language"])
