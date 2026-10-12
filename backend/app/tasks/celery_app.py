from celery import Celery
from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_code_visualizer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(task_track_started=True, timezone="Asia/Singapore", enable_utc=False)
