"""Analysis runs: one run per parcel, one task per module (TRD §4).

Each module writes its own result, so one failing module never blocks the others. When the
last module finishes, the run completes, the report draft is built and the order moves to
"In review" for the analyst.
"""

import json
import logging

import httpx
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.orders.models import Order, OrderStatus
from apps.orders.status import transition

from .models import AnalysisRun, ModuleResult, ModuleStatus, Rating, RunStatus
from .modules import MODULES

logger = logging.getLogger(__name__)


class RetryLater(Exception):
    """A module hit a network error worth retrying (busy public server, timeout)."""


def is_transient(exc):
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)  # timeouts, refused or dropped connections


def start_runs(order):
    """Create a run (and pending module results) per parcel with a boundary; return them."""
    runs = []
    for parcel in order.parcels.filter(geometry__isnull=False):
        run = AnalysisRun.objects.create(
            parcel=parcel,
            status=RunStatus.RUNNING,
            geometry_snapshot=json.loads(parcel.geometry.geojson),
            started_at=timezone.now(),
        )
        for name in MODULES:
            ModuleResult.objects.create(run=run, module=name)
        runs.append(run)
    return runs


def execute_module(result_id, can_retry=False):
    result = ModuleResult.objects.select_related("run__parcel").get(pk=result_id)
    module = MODULES[result.module]
    try:
        output = module.run(result.run.parcel)
    except Exception as exc:  # recorded, shown as "unavailable"; never blocks other modules
        if can_retry and is_transient(exc):
            logger.warning("Module %s on run %s: %r, retrying", result.module, result.run_id, exc)
            raise RetryLater from exc
        logger.exception("Module %s failed on run %s", result.module, result.run_id)
        result.status = ModuleStatus.FAILED
        result.rating = Rating.GREY
        result.error = f"{type(exc).__name__}: {exc}"[:2000]
    else:
        result.status = output.status
        result.rating = output.rating
        result.results = output.results
        result.parameters = output.parameters
        result.dataset_versions = output.datasets
        result.charts = output.charts
        result.maps = {
            name: {
                language: default_storage.save(
                    f"analysis/run-{result.run_id}/{result.module}-{name}-{language}.svg",
                    ContentFile(svg),
                )
                for language, svg in by_language.items()
            }
            for name, by_language in output.maps.items()
        }
        result.layers = [_store_layer(result, layer) for layer in output.layers]
    result.ran_at = timezone.now()
    result.save()
    finish_run_if_complete(result.run_id)


def _store_layer(result, layer):
    """Image layers: save the PNG and keep its storage key instead of the bytes."""
    if "png" not in layer:
        return layer
    stored = {k: v for k, v in layer.items() if k != "png"}
    stored["image"] = default_storage.save(
        f"analysis/run-{result.run_id}/{result.module}-layer-{layer['id']}.png",
        ContentFile(layer["png"]),
    )
    return stored


@transaction.atomic
def finish_run_if_complete(run_id):
    run = AnalysisRun.objects.select_for_update().get(pk=run_id)
    if run.status != RunStatus.RUNNING:
        return False
    if run.module_results.filter(status=ModuleStatus.PENDING).exists():
        return False
    run.status = RunStatus.COMPLETED
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at", "updated_at"])

    from apps.reports.drafts import store_draft  # reports depends on analysis, not the reverse

    order = Order.objects.select_for_update().get(pk=run.parcel.order_id)
    store_draft(order, run)
    if order.status == OrderStatus.PROCESSING:
        transition(order, OrderStatus.IN_REVIEW, note="analysis complete")
    return True
