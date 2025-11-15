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
            client = redis.Redis(host=host, port=port, socket_connect_timeout=1, socket_timeout=1)
            client.ping()
            logger.info(f"✓ Redis connection successful at {host}:{port}")
            return True
        else:
            logger.debug(f"Broker URL does not start with redis://: {broker_url}")
            return False
    except ImportError:
        logger.warning("⚠️  Redis module not installed. Install with: pip install redis")
        return False
    except Exception as e:
        logger.info(f"Redis connection check failed: {e}")
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
        print("\n" + "="*80)
        print("⚠️  REDIS NOT AVAILABLE - Running in SYNCHRONOUS mode")
        print("="*80)
        print("Tasks will execute immediately and block the web request.")
        print("\nTo enable async processing (recommended for production):")
        print("  macOS:  brew services start redis")
        print("  Linux:  sudo systemctl start redis")
        print("  Docker: docker run -d -p 6379:6379 redis:latest")
        print("\nThen start a Celery worker:")
        print("  celery -A celery_app worker --loglevel=info")
        print("="*80 + "\n")
        logger.warning("⚠️  Redis is not available. Running in SYNCHRONOUS mode (tasks will block).")
        logger.warning("⚠️  To enable async processing, start Redis and a Celery worker")
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
        print("✓ Celery configured in SYNCHRONOUS mode (CELERY_ALWAYS_EAGER=True)")
        print("  - Video generation will block the web request")
        print("  - Progress updates may not work as expected\n")
        logger.info("✓ Celery configured in SYNCHRONOUS mode (CELERY_ALWAYS_EAGER=True)")
    else:
        print("✓ Celery configured in ASYNC mode with Redis")
        print("  - Make sure to start a Celery worker: celery -A celery_app worker --loglevel=info\n")
        logger.info("✓ Celery configured in ASYNC mode with Redis")

    return celery_app


celery = make_celery()

