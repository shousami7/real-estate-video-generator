import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from celery.utils.log import get_task_logger
from dotenv import load_dotenv

from celery_app import celery
from generate_property_video import PropertyVideoGenerator
from supabase_storage import (
    is_supabase_configured,
    upload_file_to_supabase,
)

logger = get_task_logger(__name__)

load_dotenv()

if is_supabase_configured():
    logger.info("✓ Supabase client initialized in Celery worker")
else:
    logger.warning(
        "⚠️  SUPABASE_URL or SUPABASE_KEY not set in Celery worker. Generated videos will be served from local storage."
    )

LOCAL_UPLOAD_ROOT = os.path.abspath(os.environ.get("LOCAL_UPLOAD_ROOT", "uploads"))
os.makedirs(LOCAL_UPLOAD_ROOT, exist_ok=True)


def _local_generated_video_path(session_id: str, file_name: str) -> Tuple[str, str]:
    """
    Returns the (relative_path, absolute_path) for storing generated videos locally.
    """
    relative_path = os.path.join(session_id, "generated", file_name)
    absolute_path = os.path.join(LOCAL_UPLOAD_ROOT, relative_path)
    os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
    # Normalize for URLs
    normalized_relative = relative_path.replace("\\", "/")
    return normalized_relative, absolute_path


def _upload_final_video_to_supabase(session_id: str, local_video_path: str) -> str:
    """
    Upload the final generated video to Supabase Storage and return its public URL.
    """
    if not os.path.exists(local_video_path):
        raise FileNotFoundError(f"Generated video not found at: {local_video_path}")

    file_name = os.path.basename(local_video_path)
    storage_path = f"{session_id}/generated/{file_name}"

    public_url: Optional[str] = None

    if is_supabase_configured():
        logger.info(f"Uploading final video to Supabase: {local_video_path} -> {storage_path}")
        public_url, upload_error = upload_file_to_supabase(
            storage_path=storage_path,
            local_file_path=local_video_path,
            content_type="video/mp4",
            cache_control="3600",
        )
        if upload_error:
            public_url = None
            logger.warning(
                "Supabase upload failed, falling back to local delivery: %s",
                upload_error,
            )
    else:
        logger.warning("Supabase client not initialized in Celery worker. Using local storage for final video.")

    if public_url:
        try:
            os.remove(local_video_path)
            logger.info(f"Removed local video file after upload: {local_video_path}")
        except Exception as cleanup_error:
            logger.warning(f"Could not remove local video file: {cleanup_error}")
        return public_url

    relative_path, absolute_path = _local_generated_video_path(session_id, file_name)
    if os.path.abspath(local_video_path) != os.path.abspath(absolute_path):
        shutil.move(local_video_path, absolute_path)
    else:
        logger.info("Final video already located at %s", absolute_path)

    fallback_url = f"/uploads/local/{relative_path}"
    logger.info(f"Serving final video locally at {fallback_url}")

    return fallback_url

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
    project_id: Optional[str] = None,
    location: str = "us-central1",
    use_vertex_ai: bool = False,
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
        api_key: Google API key (for Google AI Studio mode, optional, defaults to env var)
        project_id: GCP Project ID (for Vertex AI mode, optional, defaults to env var)
        location: GCP region for Vertex AI (default: us-central1)
        use_vertex_ai: Whether to use Vertex AI instead of Google AI Studio
        options: Optional generation parameters

    Returns:
        Dict containing result metadata
    """
    options = options or {}
    clip_duration = int(options.get("clip_duration", 8))
    transition_type = options.get("transition_type", "fade")
    transition_duration = float(options.get("transition_duration", 0.5))
    output_name = options.get("output_name", "final_property_video.mp4")
    prompts = options.get("prompts")

    # Get authentication parameters from environment if not provided
    if use_vertex_ai:
        if not project_id:
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            if not project_id:
                raise ValueError("project_id required for Vertex AI mode (set GOOGLE_CLOUD_PROJECT env var)")
        logger.info(f"🚀 Using Vertex AI Mode - Project: {project_id}")
    else:
        if not api_key:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise ValueError("GOOGLE_API_KEY not found in environment")
        logger.info("Using Google AI Studio Mode")

    normalized_paths = _normalize_image_paths(image_paths)

    # Warn about API costs
    mode_name = "Vertex AI (GCP Credits)" if use_vertex_ai else "Google AI Studio"
    logger.warning(
        f"⚠️  Task {db_task_id}: Generating {len(image_paths)} clips = {len(image_paths)} billable API calls ({mode_name})"
    )

    logger.info(f"Starting property video generation for task {db_task_id} (celery task {self.request.id})")

    # Update progress: Starting
    self.update_state(
        state="PROGRESS",
        meta=_task_meta(10, "Starting video generation", "STARTING"),
    )

    generator = PropertyVideoGenerator(
        api_key=api_key,
        project_id=project_id,
        location=location,
        use_vertex_ai=use_vertex_ai,
        output_dir="output",
        session_name=session_id,
    )

    try:
        # Update progress: Generating clips (20%)
        self.update_state(
            state="PROGRESS",
            meta=_task_meta(20, f"Starting generation of {len(image_paths)} AI video clips", "GENERATING_CLIPS"),
        )

        # Define progress callback for detailed updates
        def clip_progress_callback(current: int, total: int, message: str):
            # Calculate progress: 20% to 80% for clip generation
            base_progress = 20
            clip_range = 60
            progress = base_progress + int((current / total) * clip_range)

            self.update_state(
                state="GENERATING_CLIPS",
                meta=_task_meta(progress, message, "GENERATING_CLIPS"),
            )
            logger.info(f"Progress update: {progress}% - {message}")

        video_clips = generator.generate_video_clips(
            image_paths=normalized_paths,
            prompts=prompts,
            duration=clip_duration,
            progress_callback=clip_progress_callback,
        )

        # Update progress: Composing (80%)
        self.update_state(
            state="PROGRESS",
            meta=_task_meta(80, "Composing final video with transitions", "COMPOSING"),
        )

        final_video_path = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

        final_video_url = _upload_final_video_to_supabase(session_id, final_video_path)

        # Success - 100%
        result = {
            "final_video": final_video_url,
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
    api_key: Optional[str] = None,
    project_id: Optional[str] = None,
    location: str = "us-central1",
    use_vertex_ai: bool = False,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task that generates the real estate marketing video in the background.

    Args:
        session_id: User session ID
        image_paths: List of image paths
        api_key: Google API key (for Google AI Studio mode)
        project_id: GCP Project ID (for Vertex AI mode)
        location: GCP region for Vertex AI
        use_vertex_ai: Whether to use Vertex AI instead of Google AI Studio
        options: Optional generation parameters
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
        project_id=project_id,
        location=location,
        use_vertex_ai=use_vertex_ai,
        output_dir="output",
        session_name=session_id,
    )

    try:
        self.update_state(
            state="GENERATING_CLIPS",
            meta=_task_meta(20, "Starting generation of AI video clips", "GENERATING_CLIPS"),
        )

        # Define progress callback for detailed updates
        def clip_progress_callback(current: int, total: int, message: str):
            # Calculate progress: 20% to 70% for clip generation
            base_progress = 20
            clip_range = 50
            progress = base_progress + int((current / total) * clip_range)

            self.update_state(
                state="GENERATING_CLIPS",
                meta=_task_meta(progress, message, "GENERATING_CLIPS"),
            )
            logger.info(f"Progress update: {progress}% - {message}")

        video_clips = generator.generate_video_clips(
            image_paths=normalized_paths,
            prompts=prompts,
            duration=clip_duration,
            progress_callback=clip_progress_callback,
        )

        self.update_state(
            state="COMPOSING",
            meta=_task_meta(70, "Composing final video", "COMPOSING"),
        )
        final_video_path = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

    except Exception as exc:
        logger.exception("Video generation failed for session %s", session_id)
        raise exc

    final_video_url = _upload_final_video_to_supabase(session_id, final_video_path)

    result = {
        "final_video": final_video_url,
        "session_id": session_id,
        "session_dir": str(generator.session_dir),
    }

    logger.info("Completed background generation for session %s", session_id)
    return result

