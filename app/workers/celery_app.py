from celery import Celery
from celery.schedules import schedule

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "order_integration",
    broker=settings.celery_broker_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        "publish-outbox-events": {
            "task": "app.workers.tasks.publish_outbox_events",
            "schedule": schedule(5.0),
        }
    },
)
