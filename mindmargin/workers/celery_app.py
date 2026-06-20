from celery import Celery
from mindmargin.config import settings

app = Celery(
    "mindmargin",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    worker_concurrency=1,
    worker_prefetch_multiplier=1,
)
