import os
from celery import Celery
from dotenv import load_dotenv

# Ensure .env variables are available when Celery worker starts
load_dotenv()


def make_celery() -> Celery:
    """
    Initialize the Celery application with sane defaults.
    """
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend_url = os.getenv("CELERY_RESULT_BACKEND", broker_url)

    celery_app = Celery(
        "real_estate_video_generator",
        broker=broker_url,
        backend=backend_url,
        include=["tasks"],
    )

    celery_app.conf.update(
        task_track_started=True,
        result_extended=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )

    return celery_app


celery = make_celery()

