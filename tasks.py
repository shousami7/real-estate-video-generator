import os
import shutil
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from utils.response_utils import build_task_response
from celery.utils.log import get_task_logger

from celery_app import celery
from generate_property_video import PropertyVideoGenerator
from supabase_storage import (
    is_supabase_configured,
    is_supabase_required,
    upload_file_to_supabase,
    upload_video_file,
    upload_log_file,
    build_storage_path,
    get_public_url,
)
from veo_generator import VeoVideoGenerator
from video_composer import VideoComposer
from scene_manager import SceneManager
from utils.video_duration import probe_video_duration as get_video_duration

logger = get_task_logger(__name__)

SUPABASE_REQUIRED = is_supabase_required()

if is_supabase_configured():
    logger.info("✓ Supabase client initialized in Celery worker")
else:
    warning_message = (
        "⚠️  SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set in Celery worker. Generated videos will be served from local storage."
    )
    if SUPABASE_REQUIRED:
        raise RuntimeError(
            "SUPABASE_REQUIRED=1 but the Celery worker could not initialize the Supabase client."
        )
    logger.warning(warning_message)

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
    Upload the final generated video to Supabase Storage using standard folder structure.
    Path: videos/{session_id}/output/{filename}
    """
    if not os.path.exists(local_video_path):
        raise FileNotFoundError(f"Generated video not found at: {local_video_path}")

    file_name = os.path.basename(local_video_path)

    # Use timestamp-based filename for generated videos
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"generate_{timestamp}.mp4"

    public_url: Optional[str] = None

    if is_supabase_configured():
        logger.info(f"Uploading final video to Supabase: videos/{session_id}/output/{output_filename}")
        public_url, upload_error = upload_video_file(
            local_path=local_video_path,
            video_id=session_id,
            filename=output_filename,
            folder="output",
        )
        if upload_error:
            public_url = None
            logger.error(
                "Supabase upload failed, falling back to local delivery: %s",
                upload_error,
            )
    else:
        if SUPABASE_REQUIRED:
            raise RuntimeError("Supabase uploads are required but the client is unavailable in the worker.")
        logger.warning("Supabase client not initialized in Celery worker. Using local storage for final video.")

    if public_url:
        try:
            os.remove(local_video_path)
            logger.info(f"Removed local video file after upload: {local_video_path}")
        except Exception as cleanup_error:
            logger.warning(f"Could not remove local video file: {cleanup_error}")
        return public_url

    if SUPABASE_REQUIRED:
        raise RuntimeError("Supabase uploads are required but the final video could not be uploaded.")

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


def _task_meta(progress: int, message: str, stage: str, video_id: str) -> Dict[str, Any]:
    """
    Helper for consistent progress metadata.
    """
    return {
        "progress": progress,
        "message": message,
        "stage": stage,
        "video_id": video_id,
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
        meta=_task_meta(10, "Starting video generation", "STARTING", session_id),
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
            meta=_task_meta(20, f"Starting generation of {len(image_paths)} AI video clips", "GENERATING_CLIPS", session_id),
        )

        # Define progress callback for detailed updates
        def clip_progress_callback(current: int, total: int, message: str):
            # Calculate progress: 20% to 80% for clip generation
            base_progress = 20
            clip_range = 60
            progress = base_progress + int((current / total) * clip_range)

            self.update_state(
                state="GENERATING_CLIPS",
                meta=_task_meta(progress, message, "GENERATING_CLIPS", session_id),
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
            meta=_task_meta(80, "Composing final video with transitions", "COMPOSING", session_id),
        )

        final_video_path = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

        final_video_url = _upload_final_video_to_supabase(session_id, final_video_path)

        # Success - 100%
        result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="completed",
            output_url=final_video_url,
        )

        # Add extra metadata for compatibility
        result.update({
            "final_video": final_video_url,  # backward compat
            "clips_generated": len(video_clips),
            "api_calls_used": len(image_paths),
        })

        # Write task log
        if is_supabase_configured():
            # Log MUST match unified format exactly (no extra fields)
            unified_log = {k: result[k] for k in ["task_id", "video_id", "stage", "status", "output_url", "frames", "error"]}
            upload_log_file(unified_log, session_id, self.request.id)
            logger.info(f"Task log written: videos/{session_id}/logs/{self.request.id}.json")

        logger.info(f"Completed property video generation for task {db_task_id}")
        logger.info(f"API calls made: {len(image_paths)}")

        return result

    except Exception as exc:
        logger.exception(f"Video generation failed for task {db_task_id}")

        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="error",
            error=str(exc),
        )

        # Write error log
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass  # Don't fail if log upload fails

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
        meta=_task_meta(5, "Queued background task", "QUEUED", session_id),
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
            meta=_task_meta(20, "Starting generation of AI video clips", "GENERATING_CLIPS", session_id),
        )

        # Define progress callback for detailed updates
        def clip_progress_callback(current: int, total: int, message: str):
            # Calculate progress: 20% to 70% for clip generation
            base_progress = 20
            clip_range = 50
            progress = base_progress + int((current / total) * clip_range)

            self.update_state(
                state="GENERATING_CLIPS",
                meta=_task_meta(progress, message, "GENERATING_CLIPS", session_id),
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
            meta=_task_meta(70, "Composing final video", "COMPOSING", session_id),
        )
        final_video_path = generator.compose_final_video(
            video_clips=video_clips,
            output_name=output_name,
            transition_type=transition_type,
            transition_duration=transition_duration,
        )

        final_video_url = _upload_final_video_to_supabase(session_id, final_video_path)

        result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="completed",
            output_url=final_video_url,
        )

        # Add backward compat fields
        result.update({
            "final_video": final_video_url,
            "session_dir": str(generator.session_dir),
        })

        # Write task log
        if is_supabase_configured():
            # Log MUST match unified format exactly
            unified_log = {k: result[k] for k in ["task_id", "video_id", "stage", "status", "output_url", "frames", "error"]}
            upload_log_file(unified_log, session_id, self.request.id)
            logger.info(f"Task log written: videos/{session_id}/logs/{self.request.id}.json")

        logger.info("Completed background generation for session %s", session_id)
        return result

    except Exception as exc:
        logger.exception("Video generation failed for session %s", session_id)

        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="error",
            error=str(exc),
        )
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass
        raise exc


# -----------------------------------------------------------------------------
# Chat-Based Video Generation Tasks - チャット機能用タスク
# -----------------------------------------------------------------------------

@celery.task(bind=True, name="tasks.generate_video_from_chat_task")
def generate_video_from_chat_task(
    self,
    session_id: str,
    scene_id: str,
    image_path: str,
    prompt: str,
    duration: str = "8s",
    aspect_ratio: str = "16:9",
    resolution: str = "720p"
) -> Dict[str, Any]:
    """
    ① 動画生成タスク（チャット用）

    Args:
        session_id: セッションID
        scene_id: シーンID
        image_path: 画像ファイルパス
        prompt: 動画生成プロンプト
        duration: 動画の長さ（例: "8s"）
        aspect_ratio: アスペクト比（"16:9" or "9:16"）
        resolution: 解像度（"720p" or "1080p"）

    Returns:
        {
            "status": str,
            "scene_id": str,
            "video_path": str,
            "video_url": str,
            "duration": float
        }
    """
    logger.info(
        f"Starting video generation from chat: session_id={session_id}, "
        f"scene_id={scene_id}, image={image_path}"
    )

    try:
        # タスクステータス更新
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 10,
                "status": f"{scene_id}の動画を生成中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        # Veo Video Generator初期化
        api_key = os.getenv("GOOGLE_API_KEY")
        project_id = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "us-central1")

        veo = VeoVideoGenerator(
            api_key=api_key,
            project_id=project_id,
            location=location
        )

        # 画像から動画生成
        logger.info(f"Generating video with Veo API: {prompt[:100]}...")
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 20,
                "status": "Veo APIで動画生成中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        operation = veo.generate_video(
            image_path=image_path,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            generate_audio=False
        )

        # 完了まで待機（ポーリング）
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 50,
                "status": "動画生成完了を待機中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        video_response = veo.wait_for_completion(operation)

        # 動画をダウンロード
        logger.info("Downloading generated video...")
        self.update_state(
            state="DOWNLOADING",
            meta={
                "progress": 80,
                "status": "動画をダウンロード中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        # ローカルパスを生成
        output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "scenes")
        os.makedirs(output_dir, exist_ok=True)
        local_video_path = os.path.join(output_dir, f"{scene_id}.mp4")

        # ダウンロード
        downloaded_path = veo.download_video(
            video_response=video_response,
            output_path=local_video_path
        )

        # 動画の長さを取得
        video_duration = get_video_duration(downloaded_path)

        # Supabaseにアップロード (standard structure: videos/{video_id}/output/)
        timestamp = int(video_duration * 1000)  # Use duration as unique identifier
        output_filename = f"{scene_id}_{timestamp}.mp4"

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=downloaded_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/videos/{session_id}/output/{output_filename}"
        else:
            video_url = f"/uploads/local/videos/{session_id}/output/{output_filename}"

        # Upload task log
        if is_supabase_configured():
            # Log MUST match unified format exactly
            unified_log = {
                "task_id": result["task_id"],
                "video_id": result["video_id"],
                "stage": result["stage"],
                "status": result["status"],
                "output_url": result["output_url"],
                "frames": result["frames"],
                "error": result["error"],
            }
            upload_log_file(unified_log, session_id, self.request.id)
            logger.info(f"Task log written: videos/{session_id}/logs/{self.request.id}.json")

        # SceneManagerに追加
        self.update_state(
            state="SAVING",
            meta={
                "progress": 90,
                "status": "シーンをタイムラインに追加中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        scene_manager = SceneManager(session_id)
        scene_manager.add_scene(
            scene_id=scene_id,
            video_path=downloaded_path,
            video_url=video_url,
            duration=video_duration,
            prompt=prompt,
            metadata={
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "generation_method": "chat_create"
            }
        )

        logger.info(f"Video generation completed: {scene_id}")

        result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="completed",
            output_url=video_url,
        )

        # Add extra fields for compatibility
        result.update({
            "scene_id": scene_id,
            "duration": video_duration,
            "message": f"{scene_id}の生成が完了しました！",
        })

        return result

    except Exception as exc:
        logger.exception(f"Video generation failed for {scene_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "status": f"エラー: {str(exc)}",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="generate",
            status="error",
            error=str(exc),
        )
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass

        raise exc


@celery.task(bind=True, name="tasks.extend_scene_task")
def extend_scene_task(
    self,
    session_id: str,
    scene_id: str,
    previous_scene_id: str,
    new_image_path: str,
    prompt: str,
    duration: str = "8s",
    aspect_ratio: str = "16:9",
    resolution: str = "720p"
) -> Dict[str, Any]:
    """
    ② シーン拡張タスク（チャット用）

    Args:
        session_id: セッションID
        scene_id: 新しいシーンID
        previous_scene_id: 前のシーンID
        new_image_path: 新しい画像ファイルパス
        prompt: 動画生成プロンプト
        duration: 動画の長さ
        aspect_ratio: アスペクト比
        resolution: 解像度

    Returns:
        {
            "status": str,
            "scene_id": str,
            "video_path": str,
            "video_url": str,
            "duration": float
        }
    """
    logger.info(
        f"Starting scene extension: session_id={session_id}, "
        f"new_scene={scene_id}, previous={previous_scene_id}"
    )

    try:
        # タスクステータス更新
        self.update_state(
            state="EXTENDING",
            meta={
                "progress": 10,
                "status": f"{previous_scene_id}を拡張中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        # SceneManagerから前のシーンを取得
        scene_manager = SceneManager(session_id)
        previous_scene = scene_manager.get_scene(previous_scene_id)

        if not previous_scene:
            raise ValueError(f"Previous scene not found: {previous_scene_id}")

        # Veo Video Generator初期化
        api_key = os.getenv("GOOGLE_API_KEY")
        project_id = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "us-central1")

        veo = VeoVideoGenerator(
            api_key=api_key,
            project_id=project_id,
            location=location
        )

        # 前の動画を読み込み（Veo APIのprevious_video機能を使用）
        # TODO: VeoVideoGeneratorにload_video_objectメソッドを追加
        # 暫定: 前の動画パスから再度ロード
        logger.info(f"Loading previous video: {previous_scene.video_path}")

        # シーン拡張（Veo APIのprevious_video機能）
        self.update_state(
            state="EXTENDING",
            meta={
                "progress": 20,
                "status": "Veo APIでシーン拡張中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        # TODO: previous_videoの実装
        # MVPでは、新しい画像から通常の動画生成を行う
        # 将来的には、Veo APIのシーン拡張機能を活用
        operation = veo.generate_video(
            image_path=new_image_path,
            prompt=f"{prompt} (続きのシーン)",
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            generate_audio=False
            # previous_video=previous_video_object  # TODO: 実装
        )

        # 完了まで待機
        self.update_state(
            state="EXTENDING",
            meta={
                "progress": 50,
                "status": "動画生成完了を待機中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        video_response = veo.wait_for_completion(operation)

        # ダウンロード
        self.update_state(
            state="DOWNLOADING",
            meta={
                "progress": 80,
                "status": "動画をダウンロード中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "scenes")
        os.makedirs(output_dir, exist_ok=True)
        local_video_path = os.path.join(output_dir, f"{scene_id}.mp4")

        downloaded_path = veo.download_video(
            video_response=video_response,
            output_path=local_video_path
        )

        # 動画の長さを取得
        video_duration = get_video_duration(downloaded_path)

        # Supabaseにアップロード (standard structure)
        timestamp = int(video_duration * 1000)
        output_filename = f"extended_{scene_id}_{timestamp}.mp4"

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=downloaded_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/videos/{session_id}/output/{output_filename}"

            # Upload task log
            # Log MUST match unified format exactly
            unified_log = {
                "task_id": self.request.id,
                "video_id": session_id,
                "stage": "extend",
                "status": "completed",
                "output_url": video_url,
                "frames": None,
                "error": None,
            }
            upload_log_file(unified_log, session_id, self.request.id)
            logger.info(f"Task log written: videos/{session_id}/logs/{self.request.id}.json")
        else:
            video_url = f"/uploads/local/videos/{session_id}/output/{output_filename}"

        # SceneManagerに追加
        self.update_state(
            state="SAVING",
            meta={
                "progress": 90,
                "status": "シーンをタイムラインに追加中...",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        scene_manager.add_scene(
            scene_id=scene_id,
            video_path=downloaded_path,
            video_url=video_url,
            duration=video_duration,
            prompt=prompt,
            previous_scene_id=previous_scene_id,
            metadata={
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "generation_method": "chat_extend"
            }
        )

        logger.info(f"Scene extension completed: {scene_id}")

        result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="extend",
            status="completed",
            output_url=video_url,
        )

        # Add extra fields
        result.update({
            "scene_id": scene_id,
            "previous_scene_id": previous_scene_id,
            "duration": video_duration,
            "message": f"{scene_id}の生成が完了しました！",
        })

        return result

    except Exception as exc:
        logger.exception(f"Scene extension failed for {scene_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "status": f"エラー: {str(exc)}",
                "scene_id": scene_id,
                "video_id": session_id,
            }
        )

        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="extend",
            status="error",
            error=str(exc),
        )
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass

        raise exc


@celery.task(bind=True, name="tasks.merge_scenes_task")
def merge_scenes_task(
    self,
    session_id: str,
    transition_type: str = "cut"
) -> Dict[str, Any]:
    """
    ③ シーン連結タスク（チャット用）

    Args:
        session_id: セッションID
        transition_type: トランジションタイプ（"cut", "fade", "wipeleft", etc.）

    Returns:
        {
            "status": str,
            "final_video_path": str,
            "final_video_url": str,
            "scene_count": int,
            "total_duration": float
        }
    """
    logger.info(
        f"Starting scene merge: session_id={session_id}, "
        f"transition={transition_type}"
    )

    try:
        # タスクステータス更新
        self.update_state(
            state="MERGING",
            meta={
                "progress": 10,
                "status": "シーンを連結中...",
                "video_id": session_id,
            }
        )

        # SceneManagerから全シーンを取得
        scene_manager = SceneManager(session_id)
        scenes = scene_manager.get_all_scenes()

        if len(scenes) < 2:
            raise ValueError("At least 2 scenes are required for merging")

        # 動画パスのリストを取得
        video_paths = scene_manager.get_video_paths()

        logger.info(f"Merging {len(scenes)} scenes with {transition_type} transition")

        # VideoComposerで連結
        self.update_state(
            state="MERGING",
            meta={
                "progress": 30,
                "status": f"{len(scenes)}つのシーンをFFmpegで連結中...",
                "video_id": session_id,
            }
        )

        composer = VideoComposer()

        # 出力パス
        output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "merged")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "final_video.mp4")

        # トランジション設定
        transition_duration = 0.5 if transition_type != "cut" else 0.0

        # 連結実行
        composed_path = composer.compose_with_transitions(
            video_paths=video_paths,
            output_path=output_path,
            transition_type=transition_type,
            transition_duration=transition_duration
        )

        # 動画の長さを取得
        self.update_state(
            state="UPLOADING",
            meta={
                "progress": 80,
                "status": "完成した動画をアップロード中...",
                "video_id": session_id,
            }
        )

        total_duration = get_video_duration(composed_path)

        # Supabaseにアップロード (standard structure: stitched)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"stitched_{timestamp}.mp4"

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=composed_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/videos/{session_id}/output/{output_filename}"

            # Upload task log
            # Log MUST match unified format exactly
            unified_log = {
                "task_id": self.request.id,
                "video_id": session_id,
                "stage": "stitch",
                "status": "completed",
                "output_url": video_url,
                "frames": None,
                "error": None,
            }
            upload_log_file(unified_log, session_id, self.request.id)
            logger.info(f"Task log written: videos/{session_id}/logs/{self.request.id}.json")
        else:
            video_url = f"/uploads/local/videos/{session_id}/output/{output_filename}"

        logger.info(f"Scene merge completed: {composed_path}")

        result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="stitch",
            status="completed",
            output_url=video_url,
        )

        # Add extra fields
        result.update({
            "scene_count": len(scenes),
            "total_duration": total_duration,
            "transition_type": transition_type,
            "message": f"{len(scenes)}つのシーンを連結した動画が完成しました！",
        })

        return result

    except Exception as exc:
        logger.exception(f"Scene merge failed for session {session_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "status": f"エラー: {str(exc)}",
                "video_id": session_id,
            }
        )

        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="stitch",
            status="error",
            error=str(exc),
        )
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass

        raise exc
