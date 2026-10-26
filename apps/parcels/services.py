"""Analyst edits to a parcel boundary (FR-38, FR-40): validate, keep the old boundary in the
history, then re-run the analysis so every module uses the new boundary."""

from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.audit import log_action
from apps.orders.models import Order, OrderStatus
from apps.orders.status import transition

from .choices import InputMethod
from .models import Parcel, ParcelGeometryHistory
from .parsers import GeometryInputError
from .validation import check_polygon

# Statuses in which the boundary can still change. Later ones (field visit, refunded) are closed.
EDITABLE = (
    OrderStatus.SUBMITTED,
    OrderStatus.PAID,
    OrderStatus.NEEDS_GEOREFERENCING,
    OrderStatus.PROCESSING,
    OrderStatus.IN_REVIEW,
    OrderStatus.DELIVERED,
)


@transaction.atomic
def save_boundary(parcel, geom, *, actor, request=None, note=""):
    """Returns (parcel, warnings, analysis_started). Raises GeometryInputError."""
    parcel = Parcel.objects.select_for_update().get(pk=parcel.pk)
    order = Order.objects.select_for_update().get(pk=parcel.order_id)
    if order.status not in EDITABLE:
        raise GeometryInputError(
            _("The boundary can no longer be changed: the order is %(status)s.")
            % {"status": order.get_status_display()}
        )
    checked = check_polygon(geom)

    if parcel.geometry is not None:
        ParcelGeometryHistory.objects.create(
            parcel=parcel,
            geometry=parcel.geometry,
            input_method=parcel.input_method,
            replaced_by=actor,
        )
    previous_method = parcel.input_method
    parcel.geometry = checked.geometry
    parcel.is_approximate = False
    parcel.input_method = InputMethod.ANALYST
    parcel.save()
    log_action(
        "parcel.boundary_saved",
        actor=actor,
        target=parcel,
        request=request,
        data={
            "area_m2": round(checked.area_m2, 1),
            "previous_input_method": previous_method,
            "warnings": checked.warnings,
            "note": note,
        },
    )

    started = _rerun(order, actor=actor, request=request)
    return parcel, checked.warnings, started


def _rerun(order, *, actor, request):
    """Move the order back to processing and start a fresh run (FR-40)."""
    from apps.analysis.tasks import start_analysis

    note = "boundary changed"
    if order.status == OrderStatus.DELIVERED:
        transition(order, OrderStatus.IN_REVIEW, actor=actor, request=request, note=note)
    if order.status in (OrderStatus.NEEDS_GEOREFERENCING, OrderStatus.IN_REVIEW):
        transition(order, OrderStatus.PROCESSING, actor=actor, request=request, note=note)
    if order.status != OrderStatus.PROCESSING:
        return False  # not paid yet: the analysis starts with the payment
    transaction.on_commit(lambda: start_analysis.delay(order.pk))
    return True
