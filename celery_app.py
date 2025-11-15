import os
import logging
from celery import Celery
from dotenv import load_dotenv

# Ensure .env variables are available when Celery worker starts
load_dotenv()

logger = logging.getLogger(__name__)


def check_redis_available(broker_url: str) -> bool:
    """
    Check if Redis is available by attempting a connection.

    Args:
        broker_url: Redis connection URL

    Returns:
        True if Redis is available, False otherwise
    """
    try:
        import redis
        # Parse the URL to get connection parameters
        if broker_url.startswith("redis://"):
            # Extract host and port from URL
            url_parts = broker_url.replace("redis://", "").split("/")[0].split(":")
            host = url_parts[0] if len(url_parts) > 0 else "localhost"
            port = int(url_parts[1]) if len(url_parts) > 1 else 6379

            # Try to connect with a short timeout
            client = redis.Redis(host=host, port=port, socket_connect_timeout=1)
            client.ping()
            return True
    except Exception as e:
        logger.debug(f"Redis connection check failed: {e}")
        return False


def make_celery() -> Celery:
    """
    Initialize the Celery application with sane defaults.
    Checks Redis availability and configures accordingly.
    """
    broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    backend_url = os.getenv("CELERY_RESULT_BACKEND", broker_url)

    # Check if we should force synchronous mode
    force_sync = os.getenv("CELERY_ALWAYS_EAGER", "").lower() in ("true", "1", "yes")

    # Check Redis availability
    redis_available = check_redis_available(broker_url)

    if not redis_available and not force_sync:
        logger.warning("⚠️  Redis is not available. Running in SYNCHRONOUS mode (tasks will block).")
        logger.warning("⚠️  To enable async processing, start Redis: brew services start redis (macOS) or sudo systemctl start redis (Linux)")
        force_sync = True

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
        task_always_eager=force_sync,  # Run tasks synchronously if Redis unavailable
        task_eager_propagates=True,    # Propagate exceptions in eager mode
    )

    if force_sync:
        logger.info("✓ Celery configured in SYNCHRONOUS mode (CELERY_ALWAYS_EAGER=True)")
    else:
        logger.info("✓ Celery configured in ASYNC mode with Redis")

    return celery_app


celery = make_celery()

