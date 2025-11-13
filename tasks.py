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

