import logging

from celery import shared_task
from django.db import transaction

from apps.orders.models import Order

from . import pipeline

logger = logging.getLogger(__name__)


@shared_task
def start_analysis(order_id):
    """Entry point, enqueued when an order is paid (or an analyst re-runs the analysis)."""
    order = Order.objects.get(pk=order_id)
    with transaction.atomic():
        runs = pipeline.start_runs(order)
    if not runs:
        logger.info("Order %s has no boundary yet (site plan to georeference).", order_id)
    for run in runs:
        for result in run.module_results.all():
            run_module.delay(result.pk)


@shared_task(bind=True, acks_late=True, max_retries=2)
def run_module(self, result_id):
    """Network errors (busy public servers) are retried after 1 then 2 minutes; anything else,
    or a third failure, is recorded and the section shown as unavailable."""
    try:
        pipeline.execute_module(result_id, can_retry=self.request.retries < self.max_retries)
    except pipeline.RetryLater as exc:
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1)) from exc
