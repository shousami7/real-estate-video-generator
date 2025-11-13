import os
from typing import Any, Dict, List, Optional

from celery.utils.log import get_task_logger

from celery_app import celery
from generate_property_video import PropertyVideoGenerator

logger = get_task_logger(__name__)


def _normalize_image_paths(image_paths: List[str]) -> List[str]:
    """
    Ensure all image paths are absolute so the Celery worker can access them.
    """
    normalized = []
    for path in image_paths:
        abs_path = os.path.abspath(path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Image not found: {abs_path}")
        normalized.append(abs_path)
    return normalized


def _task_meta(progress: int, message: str, stage: str) -> Dict[str, Any]:
    """
    Helper for consistent progress metadata.
    """
    return {
        "progress": progress,
        "message": message,
        "stage": stage,
    }


@celery.task(
    bind=True,
    name="tasks.property_video_generation_task",
    max_retries=0,
    soft_time_limit=1800,
    time_limit=2400
)
def property_video_generation_task(
    self,
    db_task_id: str,
    session_id: str,
    image_paths: List[str],
    user_id: str,
    api_key: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task for generating property videos with Supabase integration.

    WARNING: Uses paid Veo API calls. Each image = 1 billable API request.
    For 3 images, this creates 3 billable API calls.

    Args:
        db_task_id: Supabase task record ID
        session_id: User session ID
        image_paths: List of image paths (exactly 3 required)
        user_id: User ID
        api_key: Google API key (optional, defaults to env var)
        options: Optional generation parameters

    Returns:
        Dict containing result metadata
    """
    from generate_property_video import PropertyVideoGenerator

    options = options or {}
    clip_duration = int(options.get("clip_duration", 8))
    transition_type = options.get("transition_type", "fade")
    transition_duration = float(options.get("transition_duration", 0.5))
    output_name = options.get("output_name", "final_property_video.mp4")
    prompts = options.get("prompts")

    # Get API key from options or environment
    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment")

    normalized_paths = _normalize_image_paths(image_paths)

    # Warn about API costs
    logger.warning(f"⚠️  Task {db_task_id}: Generating {len(image_paths)} clips = {len(image_paths)} billable Veo API calls")

    logger.info(f"Starting property video generation for task {db_task_id} (celery task {self.request.id})")

    # Update progress: Starting
    self.update_state(
        state="PROGRESS",
        meta=_task_meta(10, "Starting video generation", "STARTING"),
    )

    generator = PropertyVideoGenerator(
        api_key=api_key,
        output_dir="output",
        session_name=session_id,
    )

    try:
        # Update progress: Generating clips (50%)
        self.update_state(
            state="PROGRESS",
            meta=_task_meta(50, f"Generating {len(image_paths)} AI video clips", "GENERATING_CLIPS"),
        )

        video_clips = generator.generate_video_clips(
            image_paths=normalized_paths,
            prompts=prompts,
            duration=clip_duration,
        )

        # Update progress: Composing (80%)
        self.update_state(
            state="PROGRESS",
            meta=_task_meta(80, "Composing final video with transitions", "COMPOSING"),
        )

        final_video = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

        # Success - 100%
        result = {
            "final_video": final_video,
            "session_id": session_id,
            "session_dir": str(generator.session_dir),
            "clips_generated": len(video_clips),
            "api_calls_used": len(image_paths),
            "db_task_id": db_task_id,
            "user_id": user_id,
        }

        logger.info(f"Completed property video generation for task {db_task_id}")
        logger.info(f"API calls made: {len(image_paths)}")

        return result

    except Exception as exc:
        logger.exception(f"Video generation failed for task {db_task_id}")
        raise exc


@celery.task(bind=True, name="tasks.generate_property_video_task")
def generate_property_video_task(
    self,
    session_id: str,
    image_paths: List[str],
    api_key: str,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task that generates the real estate marketing video in the background.
    """
    options = options or {}
    clip_duration = int(options.get("clip_duration", 8))
    transition_type = options.get("transition_type", "fade")
    transition_duration = float(options.get("transition_duration", 0.5))
    output_name = options.get("output_name", "final_property_video.mp4")
    prompts = options.get("prompts")

    normalized_paths = _normalize_image_paths(image_paths)

    logger.info("Starting background generation for session %s (task %s)", session_id, self.request.id)
    self.update_state(
        state="STARTED",
        meta=_task_meta(5, "Queued background task", "QUEUED"),
    )

    generator = PropertyVideoGenerator(
        api_key=api_key,
        output_dir="output",
        session_name=session_id,
    )

    try:
        self.update_state(
            state="GENERATING_CLIPS",
            meta=_task_meta(20, "Generating AI video clips", "GENERATING_CLIPS"),
        )
        video_clips = generator.generate_video_clips(
            image_paths=normalized_paths,
            prompts=prompts,
            duration=clip_duration,
        )

        self.update_state(
            state="COMPOSING",
            meta=_task_meta(70, "Composing final video", "COMPOSING"),
        )
        final_video = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

    except Exception as exc:
        logger.exception("Video generation failed for session %s", session_id)
        raise exc

    result = {
        "final_video": final_video,
        "session_id": session_id,
        "session_dir": str(generator.session_dir),
    }

    logger.info("Completed background generation for session %s", session_id)
    return result

