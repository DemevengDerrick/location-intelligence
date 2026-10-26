from django.contrib.contenttypes.models import ContentType

from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(action, *, actor=None, target=None, data=None, request=None):
    """Write one audit-log entry. `target` may be any model instance."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        action=action,
        actor=actor,
        target_type=ContentType.objects.get_for_model(target) if target is not None else None,
        target_id=str(target.pk) if target is not None else "",
        data=data or {},
        ip_address=client_ip(request),
    )
