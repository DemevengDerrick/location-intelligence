"""The four roles from TRD §2, stored as Django groups."""

from django.contrib.auth.models import Group, Permission

CUSTOMER = "customer"
ANALYST = "analyst"
PARTNER = "partner"
ADMIN = "admin"

ALL_ROLES = (CUSTOMER, ANALYST, PARTNER, ADMIN)

# Model-level permissions used by the Django admin. Customers get none: their access to
# their own orders is enforced object by object in views.
_ANALYST_APPS = ("orders", "parcels", "analysis", "reports", "incidents", "gazetteer")
_ANALYST_ACTIONS = ("view", "add", "change")
_PARTNER_PERMS = (
    ("partners", "view_fieldjob"),
    ("partners", "view_fieldobservation"),
    ("partners", "add_fieldobservation"),
)


def sync_role_groups():
    """Create the role groups and (re)assign their base permissions. Idempotent."""
    groups = {name: Group.objects.get_or_create(name=name)[0] for name in ALL_ROLES}

    analyst_perms = Permission.objects.filter(
        content_type__app_label__in=_ANALYST_APPS,
        codename__regex=rf"^({'|'.join(_ANALYST_ACTIONS)})_",
    )
    groups[ANALYST].permissions.set(analyst_perms)

    partner_perms = [
        p
        for app, codename in _PARTNER_PERMS
        for p in Permission.objects.filter(content_type__app_label=app, codename=codename)
    ]
    groups[PARTNER].permissions.set(partner_perms)

    groups[ADMIN].permissions.set(Permission.objects.all())
    return groups
