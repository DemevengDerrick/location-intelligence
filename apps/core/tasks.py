from celery import shared_task


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def ping(self):
    """End-to-end check that the broker and a worker are alive."""
    return "pong"
