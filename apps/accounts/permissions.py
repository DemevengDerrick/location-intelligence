from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from . import roles


def has_role(user, *wanted):
    """True if the user holds one of `wanted`. Admins (group or superuser) hold every role."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    names = set(user.groups.values_list("name", flat=True))
    return roles.ADMIN in names or bool(names.intersection(wanted))


def role_required(*wanted):
    """View decorator: anonymous users go to login, users without the role get 403."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_role(request.user, *wanted):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class HasRole(BasePermission):
    """DRF permission. Set `required_roles` on the view."""

    def has_permission(self, request, view):
        return has_role(request.user, *getattr(view, "required_roles", ()))
