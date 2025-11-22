import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

from utils.response_utils import build_task_response
from celery.utils.log import get_task_logger

from celery_app import celery
from supabase_storage import (
    is_supabase_configured,
    is_supabase_required,
    get_initialization_error,
    upload_file_to_supabase,
    upload_video_file,
    upload_log_file,
    build_storage_path,
    get_public_url,
)
from veo_generator import VeoVideoGenerator
from frame_editor import FrameEditor, AIFrameEditor
from video_composer import VideoComposer
from scene_manager import SceneManager
from utils.video_duration import probe_video_duration as get_video_duration
import uuid

logger = get_task_logger(__name__)

SUPABASE_REQUIRED = is_supabase_required()

if is_supabase_configured():
    logger.info("✓ Supabase client initialized in Celery worker")
else:
    init_error = get_initialization_error()
    if init_error:
        warning_message = f"⚠️  Supabase not available in Celery worker: {init_error}"
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


def _task_meta(progress: int, message: str, stage: str, video_id: str, step: Optional[str] = None) -> Dict[str, Any]:
    """
    Helper for consistent progress metadata.
    stage: pipeline stage (generate, extend, stitch, etc.)
    step: optional granular step (queued, composing, downloading, etc.)
    """
    return {
        "progress": progress,
        "message": message,
        "stage": stage,
        "step": step or stage,
        "video_id": video_id,
    }




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
                "message": f"{scene_id}の動画を生成中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "QUEUED",
            }
        )

        # Veo Video Generator初期化
        veo_config = _configure_veo_auth()
        
        veo = VeoVideoGenerator(**veo_config)

        # 画像から動画生成
        logger.info(f"Generating video with Veo API: {prompt[:100]}...")
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 20,
                "message": "Veo APIで動画生成中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "GENERATING",
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
        # Note: generate_video already waits for completion internally
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 50,
                "message": "動画生成完了を待機中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "WAITING",
            }
        )

        # 動画をダウンロード
        logger.info("Downloading generated video...")
        self.update_state(
            state="DOWNLOADING",
            meta={
                "progress": 80,
                "message": "動画をダウンロード中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "DOWNLOADING",
            }
        )

        # ローカルパスを生成 (temporary path; standardized path is set after duration is known)
        temp_output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "scenes")
        os.makedirs(temp_output_dir, exist_ok=True)
        temp_local_path = os.path.join(temp_output_dir, f"{scene_id}.mp4")

        # ダウンロード
        downloaded_path = veo.download_video(
            operation,
            temp_local_path
        )

        # 動画の長さを取得
        video_duration = get_video_duration(downloaded_path)

        # Supabaseにアップロード (standard structure: videos/{video_id}/output/)
        timestamp = int(video_duration * 1000)  # Use duration as unique identifier
        output_filename = f"{scene_id}_{timestamp}.mp4"

        storage_path = build_storage_path(session_id, "output", output_filename)
        standardized_local_path = os.path.join(LOCAL_UPLOAD_ROOT, storage_path)
        os.makedirs(os.path.dirname(standardized_local_path), exist_ok=True)

        if os.path.abspath(downloaded_path) != os.path.abspath(standardized_local_path):
            shutil.move(downloaded_path, standardized_local_path)
            downloaded_path = standardized_local_path

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=downloaded_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/{storage_path}"
        else:
            video_url = f"/uploads/local/{storage_path}"

        # SceneManagerに追加
        self.update_state(
            state="SAVING",
            meta={
                "progress": 90,
                "message": "シーンをタイムラインに追加中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "SAVING",
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

        if is_supabase_configured():
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
            log_path = build_storage_path(session_id, "logs", f"{self.request.id}.json")
            logger.info(f"Task log written: {log_path}")

        return result

    except Exception as exc:
        logger.exception(f"Video generation failed for {scene_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "message": f"エラー: {str(exc)}",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "generate",
                "step": "ERROR",
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

        return error_result


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
                "message": f"{previous_scene_id}を拡張中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "QUEUED",
            }
        )

        # SceneManagerから前のシーンを取得
        scene_manager = SceneManager(session_id)
        previous_scene = scene_manager.get_scene(previous_scene_id)

        if not previous_scene:
            raise ValueError(f"Previous scene not found: {previous_scene_id}")

        # Veo Video Generator初期化
        veo_config = _configure_veo_auth()
        
        veo = VeoVideoGenerator(**veo_config)

        # 前の動画を読み込み（Veo APIのprevious_video機能を使用）
        # TODO: VeoVideoGeneratorにload_video_objectメソッドを追加
        # 暫定: 前の動画パスから再度ロード
        logger.info(f"Loading previous video: {previous_scene.video_path}")

        # シーン拡張（Veo APIのprevious_video機能）
        self.update_state(
            state="EXTENDING",
            meta={
                "progress": 20,
                "message": "Veo APIでシーン拡張中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "GENERATING",
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
        # Note: generate_video already waits for completion internally
        self.update_state(
            state="EXTENDING",
            meta={
                "progress": 50,
                "message": "動画生成完了を待機中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "WAITING",
            }
        )

        # ダウンロード
        self.update_state(
            state="DOWNLOADING",
            meta={
                "progress": 80,
                "message": "動画をダウンロード中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "DOWNLOADING",
            }
        )

        output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "scenes")
        os.makedirs(output_dir, exist_ok=True)
        temp_local_path = os.path.join(output_dir, f"{scene_id}.mp4")

        downloaded_path = veo.download_video(
            operation,
            temp_local_path
        )

        # 動画の長さを取得
        video_duration = get_video_duration(downloaded_path)

        # Supabaseにアップロード (standard structure)
        timestamp = int(video_duration * 1000)
        output_filename = f"extended_{scene_id}_{timestamp}.mp4"

        storage_path = build_storage_path(session_id, "output", output_filename)
        standardized_local_path = os.path.join(LOCAL_UPLOAD_ROOT, storage_path)
        os.makedirs(os.path.dirname(standardized_local_path), exist_ok=True)

        if os.path.abspath(downloaded_path) != os.path.abspath(standardized_local_path):
            shutil.move(downloaded_path, standardized_local_path)
            downloaded_path = standardized_local_path

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=downloaded_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/{storage_path}"
        else:
            video_url = f"/uploads/local/{storage_path}"

        # SceneManagerに追加
        self.update_state(
            state="SAVING",
            meta={
                "progress": 90,
                "message": "シーンをタイムラインに追加中...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "SAVING",
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

        if is_supabase_configured():
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
            log_path = build_storage_path(session_id, "logs", f"{self.request.id}.json")
            logger.info(f"Task log written: {log_path}")

        return result

    except Exception as exc:
        logger.exception(f"Scene extension failed for {scene_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "message": f"エラー: {str(exc)}",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "ERROR",
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

        return error_result


@celery.task(bind=True, name="tasks.frame_based_extend_task")
def frame_based_extend_task(
    self,
    session_id: str,
    scene_id: str,
    source_video_path: str,
    frame_timestamp: float,
    frame_path: Optional[str],
    prompt: str,
    duration: str = "8s",
    aspect_ratio: str = "16:9",
    resolution: str = "720p"
) -> Dict[str, Any]:
    """
    Frame-based video extension task (v2.0)
    """
    logger.info(
        f"[v2.0] Starting frame-based extend: session_id={session_id}, "
        f"scene_id={scene_id}, frame_timestamp={frame_timestamp}s"
    )

    temp_dir = None

    try:
        frame_ts_value = float(frame_timestamp)
        if frame_ts_value <= 0:
            raise ValueError(f"Invalid frame_timestamp: {frame_timestamp}")

        normalized_source = source_video_path
        # Fix for double uploads path: if path starts with "uploads/", treat it as relative to project root
        if normalized_source.startswith("uploads/") or normalized_source.startswith("/uploads/"):
            project_root = os.path.dirname(LOCAL_UPLOAD_ROOT)
            if normalized_source.startswith("/"):
                normalized_source = normalized_source[1:]
            normalized_source = os.path.join(project_root, normalized_source)
        elif not os.path.isabs(normalized_source):
            normalized_source = os.path.join(LOCAL_UPLOAD_ROOT, source_video_path)

        if not os.path.exists(normalized_source):
            raise FileNotFoundError(f"Source video not found: {normalized_source}")

        temp_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "temp", scene_id)
        os.makedirs(temp_dir, exist_ok=True)

        # === Step 1: Extract frame ===
        self.update_state(
            state="EXTRACTING",
            meta=_task_meta(10, "Extracting frame as image...", "extend", session_id, "EXTRACTING")
        )

        if frame_path and os.path.exists(frame_path):
            extracted_frame_path = frame_path
            logger.info(f"[EXTRACT] Using provided frame: {frame_path}")
        else:
            extracted_frame_path = os.path.join(temp_dir, "extend_frame.png")
            extract_cmd = [
                "ffmpeg", "-y",
                "-ss", str(frame_ts_value),
                "-i", normalized_source,
                "-vframes", "1",
                "-q:v", "2",
                extracted_frame_path
            ]
            logger.info(f"[EXTRACT] Command: {' '.join(extract_cmd)}")

            try:
                subprocess.run(extract_cmd, capture_output=True, text=True, timeout=30, check=True)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Frame extraction timed out (30s)")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"FFmpeg extract failed: {e.stderr}")

        if not os.path.exists(extracted_frame_path):
            raise RuntimeError("Frame extraction failed - file not created")

        # === Step 2: Generate extension with Veo (with retries) ===
        self.update_state(
            state="GENERATING",
            meta=_task_meta(20, "Generating extended video with Veo API...", "extend", session_id, "GENERATING")
        )

        veo_config = _configure_veo_auth()
        veo = VeoVideoGenerator(**veo_config)

        # Keep API calls minimal; default to a single generation attempt unless overridden
        max_retries = max(1, int(os.getenv("EXTEND_MAX_GENERATE_ATTEMPTS", "1")))
        retry_delay = max(1, int(os.getenv("EXTEND_GENERATE_RETRY_DELAY", "5")))
        operation = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"[VEO] Attempt {attempt}/{max_retries}")
                operation = veo.generate_video(
                    image_path=extracted_frame_path,
                    prompt=f"{prompt} (extension from selected frame)",
                    duration=duration,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    generate_audio=False
                )
                if operation:
                    break
            except Exception as e:
                logger.warning(f"[VEO] Attempt {attempt} failed: {e}")
                if attempt < max_retries:
                    wait_time = retry_delay * (2 ** (attempt - 1))
                    time.sleep(wait_time)
                else:
                    raise

        if not operation:
            raise RuntimeError("Veo API returned no operation")

        self.update_state(
            state="GENERATING",
            meta=_task_meta(50, "Waiting for video generation completion...", "extend", session_id, "WAITING")
        )

        # === Step 3: Download video (with retries) ===
        self.update_state(
            state="DOWNLOADING",
            meta=_task_meta(70, "Downloading extended video...", "extend", session_id, "DOWNLOADING")
        )

        extended_video_path = os.path.join(temp_dir, "extended.mp4")
        downloaded_path = None

        max_download_attempts = max(1, int(os.getenv("EXTEND_MAX_DOWNLOAD_ATTEMPTS", "2")))
        for attempt in range(1, max_download_attempts + 1):
            try:
                downloaded_path = veo.download_video(operation, extended_video_path)
                if downloaded_path and os.path.exists(downloaded_path) and os.path.getsize(downloaded_path) > 0:
                    break
                raise RuntimeError("Downloaded video is invalid")
            except Exception as e:
                if attempt < max_download_attempts:
                    logger.warning(f"[DOWNLOAD] Attempt {attempt} failed ({e}), retrying...")
                    time.sleep(2)
                else:
                    raise RuntimeError(f"Download failed after {max_download_attempts} attempts: {e}")

        # === Step 4: Prepare final video path ===
        final_duration = get_video_duration(downloaded_path)

        self.update_state(
            state="UPLOADING",
            meta=_task_meta(90, "Uploading extended video...", "extend", session_id, "UPLOADING")
        )

        timestamp = int(final_duration * 1000)
        output_filename = f"extended_{scene_id}_{timestamp}.mp4"
        storage_path = build_storage_path(session_id, "output", output_filename)
        standardized_local_path = os.path.join(LOCAL_UPLOAD_ROOT, storage_path)
        os.makedirs(os.path.dirname(standardized_local_path), exist_ok=True)

        # Move downloaded video to final location
        if os.path.abspath(downloaded_path) != os.path.abspath(standardized_local_path):
            shutil.move(downloaded_path, standardized_local_path)
            final_video_path = standardized_local_path
        else:
            final_video_path = downloaded_path

        video_url = f"/uploads/local/{storage_path}"
        if is_supabase_configured():
            try:
                video_url_result, upload_error = upload_video_file(
                    local_path=final_video_path,
                    video_id=session_id,
                    filename=output_filename,
                    folder="output",
                )
                if video_url_result:
                    video_url = video_url_result
                elif upload_error:
                    logger.warning(f"[UPLOAD] Supabase upload failed, using local: {upload_error}")
            except Exception as e:
                logger.warning(f"[UPLOAD] Supabase exception, using local: {e}")

        # === Step 5: Save scene ===
        scene_manager = SceneManager(session_id)
        scene_manager.add_scene(
            scene_id=scene_id,
            video_path=final_video_path,
            video_url=video_url,
            duration=final_duration,
            prompt=prompt,
            metadata={
                "type": "frame_based_extend",
                "source_video": source_video_path,
                "frame_timestamp": frame_ts_value,
                "extended_duration": final_duration,
                "version": "2.0"
            }
        )

        logger.info(
            f"[COMPLETE] Frame-based extend: scene_id={scene_id}, "
            f"duration={final_duration}s, url={video_url}"
        )

        return {
            "status": "completed",
            "scene_id": scene_id,
            "video_path": storage_path,
            "video_url": video_url,
            "duration": final_duration,
            "metadata": {
                "type": "frame_based_extend",
                "frame_timestamp": frame_ts_value,
                "final_duration": final_duration,
                "version": "2.0"
            }
        }

    except Exception as e:
        logger.error(f"[ERROR] Frame-based extend failed: {e}", exc_info=True)
        self.update_state(
            state="FAILURE",
            meta=_task_meta(0, f"Error: {str(e)}", "extend", session_id, "ERROR")
        )
        
        error_result = build_task_response(
            task_id=self.request.id,
            video_id=session_id,
            stage="extend",
            status="error",
            error=str(e),
        )
        
        if is_supabase_configured():
            try:
                upload_log_file(error_result, session_id, self.request.id)
            except Exception:
                pass

        return error_result

    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.warning(f"[CLEANUP] Failed to remove temp directory: {cleanup_error}")


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
                "message": "シーンを連結中...",
                "video_id": session_id,
                "stage": "stitch",
                "step": "QUEUED",
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
                "message": f"{len(scenes)}つのシーンをFFmpegで連結中...",
                "video_id": session_id,
                "stage": "stitch",
                "step": "MERGING",
            }
        )

        composer = VideoComposer()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"stitched_{timestamp}.mp4"

        # 出力パス (standard structure)
        storage_path = build_storage_path(session_id, "output", output_filename)
        output_path = os.path.join(LOCAL_UPLOAD_ROOT, storage_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

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
                "message": "完成した動画をアップロード中...",
                "video_id": session_id,
                "stage": "stitch",
                "step": "UPLOADING",
            }
        )

        total_duration = get_video_duration(composed_path)

        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=composed_path,
                video_id=session_id,
                filename=output_filename,
                folder="output",
            )
            video_url = video_url_result if video_url_result else f"/uploads/local/{storage_path}"
        else:
            video_url = f"/uploads/local/{storage_path}"

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

        if is_supabase_configured():
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
            log_path = build_storage_path(session_id, "logs", f"{self.request.id}.json")
            logger.info(f"Task log written: {log_path}")

        return result

    except Exception as exc:
        logger.exception(f"Scene merge failed for session {session_id}")
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "message": f"エラー: {str(exc)}",
                "video_id": session_id,
                "stage": "stitch",
                "step": "ERROR",
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

        return error_result


def _configure_veo_auth() -> Dict[str, Any]:
    """
    Configure Veo authentication (Google AI Studio).
    """
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        logger.error("Missing GOOGLE_API_KEY for Google AI Studio auth")
        raise ValueError("Authentication missing: set GOOGLE_API_KEY for Google AI Studio.")

    logger.info(f"Using Google AI Studio with API key authentication")
    return {
        "api_key": api_key,
    }


@celery.task(bind=True, name="tasks.extract_frames_task")
def extract_frames_task(
    self,
    video_id: str,
    video_path: Optional[str] = None,
    fps: float = 1.0
) -> Dict[str, Any]:
    """
    Extract frames from a video.
    """
    logger.debug(f"Starting frame extraction: video_id={video_id}")
    try:
        self.update_state(state="EXTRACTING", meta={"progress": 10, "message": "Initializing extraction..."})

        if not video_path:
            # Try to find video path from SceneManager if not provided
            scene_manager = SceneManager(video_id)
            last_scene = scene_manager.get_last_scene()
            if last_scene:
                video_path = last_scene.video_path
            else:
                raise ValueError(f"Video path not provided and no scenes found for {video_id}")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        frames_dir = os.path.join(LOCAL_UPLOAD_ROOT, video_id, 'extracted')
        os.makedirs(frames_dir, exist_ok=True)

        frame_editor = FrameEditor(video_path, frames_dir)
        
        # Calculate frame count
        video_duration = get_video_duration(video_path)
        frame_count = min(int(video_duration * fps), 100)
        
        self.update_state(state="EXTRACTING", meta={"progress": 30, "message": f"Extracting {frame_count} frames..."})
        
        extracted_frames = frame_editor.extract_frames(frame_count=frame_count)
        
        # Format response
        frames_response = []
        for frame in extracted_frames:
            # In a real scenario, we might upload these to Supabase here
            # For now, return local paths/URLs
            frame_filename = os.path.basename(frame['path'])
            # Assuming a route exists to serve these or they are uploaded
            # If using Supabase, we would upload here.
            
            frame_url = f"/uploads/local/{video_id}/extracted/{frame_filename}"
            
            frames_response.append({
                "index": frame['frame_id'],
                "timestamp": frame['seconds'],
                "url": frame_url,
                "path": frame['path']
            })

        result = build_task_response(
            task_id=self.request.id,
            video_id=video_id,
            stage="extract",
            status="completed",
            frames=frames_response
        )
        return result

    except Exception as exc:
        logger.exception(f"Frame extraction failed: {exc}")
        return build_task_response(
            task_id=self.request.id,
            video_id=video_id,
            stage="extract",
            status="error",
            error=str(exc)
        )


@celery.task(bind=True, name="tasks.edit_frame_task")
def edit_frame_task(
    self,
    video_id: str,
    frame_index: int,
    instruction: str,
    scene_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Edit a specific frame using AI.
    """
    logger.info(f"Starting frame edit: video_id={video_id}, frame={frame_index}")
    try:
        # For frame editing, we currently rely on the same auth config
        # Note: AIFrameEditor might need specific handling if it doesn't support Vertex AI yet.
        # Assuming AIFrameEditor takes an api_key. If using Vertex AI, we might need to adapt AIFrameEditor.
        # For now, we'll try to get an API key if available, or error out if AIFrameEditor strictly needs it.
        
        veo_config = _configure_veo_auth()
        
        
        self.update_state(state="EDITING", meta={"progress": 10, "message": "Preparing frame for editing..."})

        scene_manager = SceneManager(video_id)
        if scene_id:
            scene = scene_manager.get_scene(scene_id)
            if not scene:
                raise ValueError(f"Scene {scene_id} not found")
            video_path = scene.video_path
        else:
            last_scene = scene_manager.get_last_scene()
            if not last_scene:
                raise ValueError(f"No scenes found for {video_id}")
            video_path = last_scene.video_path

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Extract the specific frame
        temp_dir = os.path.join(LOCAL_UPLOAD_ROOT, video_id, 'temp_edit')
        os.makedirs(temp_dir, exist_ok=True)
        frame_editor = FrameEditor(video_path, temp_dir)
        
        # Extract enough frames to reach the index
        extracted = frame_editor.extract_frames(frame_count=frame_index + 5)
        if frame_index >= len(extracted):
             raise ValueError(f"Frame index {frame_index} out of range")
             
        target_frame_path = extracted[frame_index]['path']
        
        self.update_state(state="EDITING", meta={"progress": 40, "message": "Generating AI edits..."})
        
        ai_editor = AIFrameEditor()
        variations = ai_editor.generate_frame_variations(
            base_image_path=target_frame_path,
            prompt=instruction,
            variation_count=1
        )
        
        if not variations:
            raise RuntimeError("Failed to generate variations")
            
        # Save result
        edited_dir = os.path.join(LOCAL_UPLOAD_ROOT, video_id, 'edited')
        os.makedirs(edited_dir, exist_ok=True)
        edited_filename = f"edited_{frame_index}_{uuid.uuid4().hex[:8]}.png"
        edited_path = os.path.join(edited_dir, edited_filename)
        
        # Save base64 to file
        import base64
        variation = variations[0]
        if 'image_url' in variation and variation['image_url'].startswith('data:image'):
            base64_str = variation['image_url'].split(',')[1]
            image_data = base64.b64decode(base64_str)
            with open(edited_path, 'wb') as f:
                f.write(image_data)
                
        edited_url = f"/uploads/local/{video_id}/edited/{edited_filename}"
        
        result = build_task_response(
            task_id=self.request.id,
            video_id=video_id,
            stage="edit",
            status="completed",
            frames=[{
                "index": frame_index,
                "original_path": target_frame_path,
                "edited_url": edited_url,
                "instruction": instruction
            }]
        )
        return result

    except Exception as exc:
        logger.exception(f"Frame editing failed: {exc}")
        return build_task_response(
            task_id=self.request.id,
            video_id=video_id,
            stage="edit",
            status="error",
            error=str(exc)
        )


# -----------------------------------------------------------------------------
# Aliases for Backward Compatibility / External Callers
# -----------------------------------------------------------------------------
# These aliases map the "unregistered" task names seen in logs to the actual implementations.
task_generate_video = generate_video_from_chat_task
task_extend_video = extend_scene_task
task_stitch_videos = merge_scenes_task
task_extract_frames = extract_frames_task
task_edit_frame = edit_frame_task
