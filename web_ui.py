import os
import uuid
import logging
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (
    Blueprint, render_template, request, jsonify, session, send_from_directory
)
from werkzeug.utils import secure_filename
from celery import states
from celery.result import AsyncResult

from frame_editor import FrameEditor, AIFrameEditor
from celery_app import celery
from tasks import generate_property_video_task, property_video_generation_task
from supabase_storage import (
    is_supabase_configured,
    is_supabase_required,
    upload_bytes_to_supabase,
)
from chat_command_handler import ChatCommandHandler, CommandIntent
from scene_manager import SceneManager
from datetime import datetime

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

web_ui_blueprint = Blueprint('web_ui', __name__, template_folder='templates', static_folder='static')
# -----------------------------------------------------------------------------
# Supabase Client Initialization
# -----------------------------------------------------------------------------
LOCAL_UPLOAD_ROOT = os.path.abspath(os.environ.get("LOCAL_UPLOAD_ROOT", "uploads"))
os.makedirs(LOCAL_UPLOAD_ROOT, exist_ok=True)

SUPABASE_REQUIRED = is_supabase_required()

if is_supabase_configured():
    logger.info("✓ Supabase client ready (web process)")
else:
    message = "⚠️  SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set. Falling back to local storage only."
    if SUPABASE_REQUIRED:
        raise RuntimeError(
            "SUPABASE_REQUIRED=1 but no Supabase credentials were found. Configure SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    logger.warning(message)


def _local_storage_full_path(relative_path: str) -> str:
    """
    Build an absolute path inside the uploads directory while preventing traversal.
    """
    safe_relative = os.path.normpath(relative_path).lstrip(os.sep)
    full_path = os.path.join(LOCAL_UPLOAD_ROOT, safe_relative)
    if os.path.commonpath([LOCAL_UPLOAD_ROOT, os.path.abspath(full_path)]) != os.path.abspath(LOCAL_UPLOAD_ROOT):
        raise ValueError("Invalid storage path outside upload root")
    return full_path


def _save_bytes_to_local_storage(relative_path: str, file_bytes: bytes) -> str:
    """
    Persist bytes to LOCAL_UPLOAD_ROOT/relative_path and return the absolute path.
    """
    full_path = _local_storage_full_path(relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as destination:
        destination.write(file_bytes)
    return full_path

@web_ui_blueprint.route('/')
def index():
    """Web UIのエントリーポイントです。"""
    # Ensure every new launch of the UI starts from a clean slate. Without this,
    # Flask's signed session cookie can keep the previous run's status, causing
    # the browser to show stale progress when the server restarts.
    session.clear()

    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    session_id = session['session_id']

    # Reset generation state on initial page load
    session.pop('generation_status', None)
    session.pop('generation_progress', None)
    session.pop('generation_error', None)
    session.pop('final_video', None)

    print(f"ユーザーID: {session_id} で接続 (セッション状態をリセット)")
    return render_template('luxury_video_ui.html', session_id=session_id)

@web_ui_blueprint.route('/upload', methods=['POST'])
def upload_files():
    """
    Handle image uploads.
    """
    try:
        # デバッグ: セッション情報を確認
        print(f"[UPLOAD DEBUG] Session keys: {list(session.keys())}")
        print(f"[UPLOAD DEBUG] Request files: {list(request.files.keys())}")
        print(f"[UPLOAD DEBUG] Request form: {list(request.form.keys())}")
        print(f"[UPLOAD DEBUG] Content-Type: {request.content_type}")

        # セッション確認
        if 'session_id' not in session:
            print("[UPLOAD ERROR] Session not found")
            return jsonify({
                "error": "Session not found",
                "detail": "セッションが見つかりません。ページをリロードしてください。"
            }), 400

        session_id = session['session_id']
        print(f"[UPLOAD] Processing upload for session: {session_id}")

        supabase_available = is_supabase_configured()
        if not supabase_available:
            if SUPABASE_REQUIRED:
                raise RuntimeError(
                    "Supabase uploads are required but the client is unavailable. Check your credentials."
                )
            logger.warning("Supabase client not available. Uploads will be stored locally only.")

        uploaded_file_records: List[Dict[str, str]] = []
        response_file_urls: List[str] = []

        # ファイルチェック（詳細なエラーメッセージ付き）
        for i in range(3):
            file_key = f'image_{i+1}'

            if file_key not in request.files:
                print(f"[UPLOAD ERROR] Missing file key: {file_key}")
                print(f"[UPLOAD ERROR] Available keys: {list(request.files.keys())}")
                return jsonify({
                    "error": f"Missing {file_key}",
                    "detail": f"{file_key}が見つかりません。",
                    "available_keys": list(request.files.keys())
                }), 400

            file = request.files[file_key]
            print(f"[UPLOAD] Processing {file_key}: filename={file.filename}")

            if file.filename == '':
                print(f"[UPLOAD ERROR] Empty filename for {file_key}")
                return jsonify({
                    "error": f"No selected file for {file_key}",
                    "detail": f"{file_key}のファイル名が空です。"
                }), 400

            # ファイル保存
            filename = secure_filename(file.filename)
            storage_path = os.path.join(session_id, filename).replace("\\", "/")
            file_bytes = file.read()
            if not file_bytes:
                return jsonify({
                    "error": "Empty file",
                    "detail": f"{file_key} has no content."
                }), 400

            local_path = _save_bytes_to_local_storage(storage_path, file_bytes)
            upload_record: Dict[str, str] = {
                "file_key": file_key,
                "filename": filename,
                "storage_path": storage_path,
                "local_path": local_path,
                "content_type": file.content_type or "application/octet-stream",
            }

            public_url: Optional[str] = None
            if supabase_available:
                public_url, upload_error = upload_bytes_to_supabase(
                    storage_path=storage_path,
                    file_bytes=file_bytes,
                    content_type=upload_record["content_type"]
                )
                if upload_error:
                    public_url = None
                    logger.error(
                        "Supabase upload failed for %s. Falling back to local storage. Error: %s",
                        storage_path,
                        upload_error,
                    )
                    supabase_available = is_supabase_configured()
                    if not supabase_available:
                        logger.info("Supabase has been disabled after an upload failure; continuing with local storage.")
                else:
                    print(f"[UPLOAD] Saved {file_key} to Supabase URL: {public_url}")

            if public_url:
                upload_record["public_url"] = public_url
                upload_record["storage_backend"] = "supabase"
                response_file_urls.append(public_url)
            else:
                if SUPABASE_REQUIRED:
                    raise RuntimeError(
                        "Supabase uploads are required but upload failed for %s" % storage_path
                    )
                upload_record["storage_backend"] = "local"
                response_file_urls.append(f"/uploads/local/{storage_path}")
                logger.info(f"[UPLOAD] Stored {file_key} locally at {local_path}")

            uploaded_file_records.append(upload_record)

        session['uploaded_files'] = uploaded_file_records
        session['uploaded_file_paths'] = [record["local_path"] for record in uploaded_file_records]
        print(f"[UPLOAD SUCCESS] Uploaded {len(uploaded_file_records)} files (Supabase available={supabase_available})")

        storage_backends = {record.get("storage_backend") for record in uploaded_file_records}
        if storage_backends == {"local"}:
            storage_note = " (stored locally)"
        elif "local" in storage_backends and "supabase" in storage_backends:
            storage_note = " (partial Supabase upload; local copies kept)"
        else:
            storage_note = ""

        return jsonify({
            "status": "success",
            "message": f"Images uploaded successfully. Click 'AI Video Generation Start' button.{storage_note}",
            "files": response_file_urls
        })

    except Exception as e:
        print(f"[UPLOAD EXCEPTION] {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Upload failed",
            "detail": str(e),
            "type": type(e).__name__
        }), 500

@web_ui_blueprint.route('/generate', methods=['POST'])
def generate_video():
    """
    Enqueue the async video generation process (non-blocking via Celery).

    WARNING: This will create 3 separate billable Veo API calls (one per image).
    """
    if 'session_id' not in session or 'uploaded_files' not in session:
        return jsonify({
            "status": "error",
            "message": "No uploaded images found. Please upload images first."
        }), 400

    # Get authentication parameters
    api_key = os.getenv("GOOGLE_API_KEY")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    # Determine if Vertex AI should be used
    use_vertex_ai = bool(project_id)

    # Validate authentication
    if use_vertex_ai:
        logger.info(f"🚀 Using Vertex AI Mode - Project: {project_id}, Location: {location}")
    else:
        if not api_key:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_API_KEY or GOOGLE_CLOUD_PROJECT must be set. Please check your .env file."
            }), 500
        logger.info("Using Google AI Studio Mode")

    # Prevent duplicate submissions while a task is still running
    existing_task_id = session.get('generation_task_id')
    if existing_task_id:
        existing_task = AsyncResult(existing_task_id, app=celery)
        if existing_task.state not in states.READY_STATES:
            return jsonify({
                "status": "error",
                "message": "A video generation task is already running. Please wait for it to finish or cancel it."
            }), 409

    session_id = session['session_id']
    stored_files = session.get('uploaded_file_paths') or session.get('uploaded_files') or []
    image_paths: List[str] = []

    if stored_files and isinstance(stored_files[0], dict):
        for record in stored_files:
            local_path = record.get("local_path")
            if local_path:
                image_paths.append(os.path.abspath(local_path))
    else:
        image_paths = [os.path.abspath(path) for path in stored_files]

    if len(image_paths) != 3:
        return jsonify({
            "status": "error",
            "message": "Please upload 3 images before starting generation."
        }), 400

    # Parse generation options from client
    request_data = request.get_json(silent=True) or {}
    clip_duration = request_data.get('clip_duration')
    if clip_duration is None and 'clip_duration' in request.form:
        clip_duration = request.form.get('clip_duration')

    def _sanitize_clip_duration(value, default=8):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(4, min(20, parsed))

    clip_duration = _sanitize_clip_duration(clip_duration, default=8)

    # Generate unique task ID for tracking
    db_task_id = str(uuid.uuid4())
    user_id = session_id  # Using session_id as user_id for now

    # Reset previous session state
    session['generation_status'] = 'QUEUED'
    session['generation_progress'] = 5
    session.pop('generation_error', None)
    session.pop('final_video', None)

    # Launch task (will be async if Redis available, sync otherwise)
    try:
        task = property_video_generation_task.apply_async(
            args=[db_task_id, session_id, image_paths, user_id],
            kwargs={
                "api_key": api_key,
                "project_id": project_id,
                "location": location,
                "use_vertex_ai": use_vertex_ai,
                "options": {
                    "clip_duration": clip_duration,
                    "transition_type": "fade",
                    "transition_duration": 0.5,
                    "output_name": "final_property_video.mp4"
                }
            }
        )
    except Exception as e:
        logger.error(f"Failed to queue task: {e}")
        return jsonify({
            "status": "error",
            "message": f"Failed to start video generation: {str(e)}"
        }), 500

    session['generation_task_id'] = task.id
    session['db_task_id'] = db_task_id

    num_api_calls = len(image_paths)
    logger.warning(f"⚠️  Starting video generation: {num_api_calls} images = {num_api_calls} Veo API calls")

    # Check if running in eager mode (synchronous)
    is_eager_mode = celery.conf.task_always_eager
    if is_eager_mode:
        logger.info("Running in SYNCHRONOUS mode - task will execute immediately")

    # Check if task completed immediately (synchronous mode)
    if task.ready():
        logger.info("Task completed synchronously")
        try:
            result = task.get()
            session['final_video'] = result.get('final_video')
            session['generation_status'] = 'COMPLETE'
            session['generation_progress'] = 100
            return jsonify({
                "status": "completed",
                "message": f"Video generation completed! ({num_api_calls} Veo API calls used)",
                "task_id": task.id,
                "final_video_url": "/download",
                "api_calls": num_api_calls,
                "sync_mode": True
            }), 200
        except Exception as e:
            logger.error(f"Synchronous task failed: {e}")
            session['generation_status'] = 'ERROR'
            session['generation_error'] = str(e)
            return jsonify({
                "status": "error",
                "message": f"Video generation failed: {str(e)}",
                "sync_mode": True
            }), 500

    # Async mode - task is queued
    # Check if Celery workers are available (with timeout)
    try:
        inspector = celery.control.inspect(timeout=1.0)
        active_workers = inspector.active()

        if not active_workers:
            logger.error("⚠️  No Celery workers are running! Task will remain queued until a worker starts.")
            logger.error("⚠️  Start a worker with: celery -A celery_app worker --loglevel=info")
            return jsonify({
                "status": "error",
                "message": "No Celery workers are running. Please start a Celery worker or enable synchronous mode (CELERY_ALWAYS_EAGER=true in .env).",
                "help": "Start a worker with: celery -A celery_app worker --loglevel=info"
            }), 500
    except Exception as e:
        logger.error(f"⚠️  Failed to check for Celery workers: {e}")
        logger.error("⚠️  This usually means Redis is not available. Task will remain queued.")
        return jsonify({
            "status": "error",
            "message": "Failed to connect to Celery broker. Please ensure Redis is running or enable synchronous mode (CELERY_ALWAYS_EAGER=true in .env).",
            "help": "Start Redis with: brew services start redis (macOS) or sudo systemctl start redis (Linux)"
        }), 500

    return jsonify({
        "status": "started",
        "message": f"Video generation started. Processing {num_api_calls} images (= {num_api_calls} Veo API calls).",
        "task_id": task.id,
        "celery_task_id": task.id,
        "db_task_id": db_task_id,
        "api_calls": num_api_calls,
        "sync_mode": False
    }), 202

@web_ui_blueprint.route('/status')
def get_status():
    """
    Check the progress of the async video generation task.
    """
    task_id = session.get('generation_task_id')

    if not task_id:
        return jsonify({
            "status": "IDLE",
            "message": "Upload Progress",
            "progress_percent": 0
        })

    task = AsyncResult(task_id, app=celery)
    meta = task.info if isinstance(task.info, dict) else {}
    progress = meta.get('progress', session.get('generation_progress', 0))
    message = meta.get('message', "Processing video request...")
    stage = meta.get('stage', task.state)

    if task.state == states.PENDING:
        session['generation_status'] = 'QUEUED'
        session['generation_progress'] = progress
        return jsonify({
            "status": "QUEUED",
            "message": "Waiting for an available worker...",
            "progress_percent": progress
        })

    if task.state in {'STARTED', 'GENERATING_CLIPS', 'COMPOSING'}:
        session['generation_status'] = stage
        session['generation_progress'] = progress
        session.modified = True
        return jsonify({
            "status": stage or "GENERATING_CLIPS",
            "message": message,
            "progress_percent": progress
        })

    if task.state == states.SUCCESS:
        final_video = meta.get('final_video') or session.get('final_video')
        if final_video:
            session['final_video'] = final_video
        session['generation_status'] = 'COMPLETE'
        session['generation_progress'] = 100
        session.modified = True
        return jsonify({
            "status": "COMPLETE",
            "message": "Video generation completed successfully!",
            "progress_percent": 100,
            "final_video_url": "/download",
            "editor_url": "/video/editor"
        })

    if task.state in {states.FAILURE, states.REVOKED}:
        error_msg = session.get('generation_error')
        if not error_msg:
            if isinstance(task.info, Exception):
                error_msg = str(task.info)
            else:
                error_msg = meta.get('message', 'An unknown error occurred during video generation.')
        status_label = "CANCELLED" if task.state == states.REVOKED else "ERROR"
        session['generation_status'] = status_label
        session['generation_error'] = error_msg
        session['generation_progress'] = progress
        session.modified = True
        return jsonify({
            "status": status_label,
            "message": f"{status_label}: {error_msg}",
            "progress_percent": progress
        })

    # Fallback (should not normally reach here)
    return jsonify({
        "status": task.state or "IDLE",
        "message": message,
        "progress_percent": progress
    })

@web_ui_blueprint.route('/download')
def download_video():
    """
    Download the generated video.
    """
    if 'final_video' not in session:
        task_id = session.get('generation_task_id')
        if task_id:
            task = AsyncResult(task_id, app=celery)
            if task.successful() and isinstance(task.result, dict):
                final_video = task.result.get('final_video')
                if final_video:
                    session['final_video'] = final_video

    if 'final_video' not in session:
        return jsonify({"error": "No video found for this session"}), 404

    video_path = session['final_video']
    directory = os.path.dirname(video_path)
    filename = os.path.basename(video_path)
    return send_from_directory(directory, filename, as_attachment=True)


@web_ui_blueprint.route('/generate/cancel', methods=['POST'])
def cancel_generation():
    """
    Cancel an in-progress video generation task.
    """
    task_id = session.get('generation_task_id')
    if not task_id:
        return jsonify({
            "status": "error",
            "message": "No generation task found for this session."
        }), 400

    task = AsyncResult(task_id, app=celery)
    if task.state in states.READY_STATES:
        return jsonify({
            "status": "info",
            "message": "Task has already finished."
        }), 200

    celery.control.revoke(task_id, terminate=True, signal="SIGTERM")
    session['generation_status'] = 'CANCELLED'
    session['generation_progress'] = 0
    session['generation_error'] = 'Task cancelled by user.'
    session.modified = True

    return jsonify({
        "status": "cancelled",
        "message": "Video generation task was cancelled."
    }), 202


# ============================================================================
# FRAME EDITOR ENDPOINTS
# ============================================================================

@web_ui_blueprint.route('/video/upload', methods=['POST'])
def upload_video():
    """
    Upload video for frame editing
    """
    try:
        if 'video' not in request.files:
            return jsonify({
                "status": "error",
                "message": "No video file provided"
            }), 400

        video_file = request.files['video']

        if not video_file.filename:
            return jsonify({
                "status": "error",
                "message": "No file selected"
            }), 400

        if 'session_id' not in session:
            session['session_id'] = str(uuid.uuid4())

        session_id = session['session_id']
        upload_dir = os.path.join('uploads', session_id, 'editor')
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(video_file.filename)
        video_path = os.path.join(upload_dir, filename)
        video_file.save(video_path)

        normalized_video_path = video_path.replace('\\', '/')
        public_url = f"/uploads/{session_id}/editor/{filename}"

        session['editor_video'] = normalized_video_path

        logger.info(f"Video uploaded: {video_path}")

        return jsonify({
            "status": "success",
            "message": "Video uploaded successfully",
            "video_path": normalized_video_path,
            "video_url": public_url
        })

    except Exception as e:
        logger.error(f"Error uploading video: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    """
    Serve uploaded files (videos, etc.)
    """
    try:
        # uploads ディレクトリからファイルを提供（絶対パス使用）
        upload_dir = os.path.abspath('uploads')
        logger.info(f"Serving file: {filename} from {upload_dir}")
        return send_from_directory(upload_dir, filename)
    except Exception as e:
        logger.error(f"Error serving file {filename}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "File not found"
        }), 404


@web_ui_blueprint.route('/frames/<path:filename>')
def serve_frame_file(filename):
    """
    Serve frame files (extracted frames, edited frames, etc.)
    """
    try:
        # frames ディレクトリからファイルを提供（絶対パス使用）
        frames_dir = os.path.abspath('frames')
        logger.info(f"Serving frame: {filename} from {frames_dir}")
        return send_from_directory(frames_dir, filename)
    except Exception as e:
        logger.error(f"Error serving frame {filename}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "Frame not found"
        }), 404


@web_ui_blueprint.route('/frames/extract', methods=['POST'])
def extract_frames():
    """
    Extract frames from uploaded video
    """
    try:
        data = request.get_json()
        video_path = data.get('video_path')

        if not video_path or not os.path.exists(video_path):
            return jsonify({
                "status": "error",
                "message": "Video not found"
            }), 400

        session_id = session.get('session_id', 'default')
        frames_dir = os.path.join('frames', session_id, 'editor')

        editor = FrameEditor(video_path, frames_dir)
        frames = editor.extract_frames(frame_count=6)

        # セッションにはパス情報のみ保存（base64データは除外）
        frames_for_session = [
            {
                "frame_id": frame['frame_id'],
                "path": frame['path'],
                "timestamp": frame['timestamp'],
                "seconds": frame['seconds']
                # base64 は含まない
            }
            for frame in frames
        ]

        session['editor_frames'] = frames_for_session
        session['editor_frames_dir'] = frames_dir
        session['editor_video_path'] = video_path  # FrameEditorの再作成用

        logger.info(f"Extracted {len(frames)} frames")

        # クライアントにはbase64付きの完全なデータを返す
        return jsonify({
            "status": "success",
            "frames": frames,  # base64を含む完全なデータ
            "frame_count": len(frames)
        })

    except Exception as e:
        logger.error(f"Error extracting frames: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/frames/image/<int:frame_id>')
def get_frame_image(frame_id):
    """
    Get individual frame image by ID
    """
    try:
        if 'editor_frames' not in session:
            return jsonify({
                "status": "error",
                "message": "No frames found"
            }), 400

        frames = session['editor_frames']

        if frame_id < 0 or frame_id >= len(frames):
            return jsonify({
                "status": "error",
                "message": "Invalid frame ID"
            }), 400

        frame_path = frames[frame_id]['path']

        if not os.path.exists(frame_path):
            return jsonify({
                "status": "error",
                "message": "Frame file not found"
            }), 404

        directory = os.path.dirname(frame_path)
        filename = os.path.basename(frame_path)
        return send_from_directory(directory, filename, mimetype='image/png')

    except Exception as e:
        logger.error(f"Error getting frame image: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/frames/edit', methods=['POST'])
def edit_frame():
    """
    Edit frame using AI
    """
    try:
        data = request.get_json()
        frame_id = data.get('frame_id')
        prompt = data.get('prompt')

        if 'editor_frames' not in session:
            return jsonify({
                "status": "error",
                "message": "No frames found"
            }), 400

        if frame_id < 0 or frame_id >= len(session['editor_frames']):
            return jsonify({
                "status": "error",
                "message": "Invalid frame ID"
            }), 400

        if not prompt:
            return jsonify({
                "status": "error",
                "message": "Prompt is required"
            }), 400

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return jsonify({
                "status": "error",
                "message": "API key not configured"
            }), 500

        ai_editor = AIFrameEditor(api_key)
        frame_path = session['editor_frames'][frame_id]['path']
        variations = ai_editor.generate_frame_variations(
            base_image_path=frame_path,
            prompt=prompt,
            variation_count=4
        )

        logger.info(f"Generated {len(variations)} variations")

        return jsonify({
            "status": "success",
            "variations": variations
        })

    except Exception as e:
        logger.error(f"Error editing frame: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/frames/apply', methods=['POST'])
def apply_frame_edit():
    """
    Apply edited frame and save as file
    """
    try:
        import base64

        data = request.get_json()
        frame_id = data.get('frame_id')
        edited_image_url = data.get('edited_image_url')

        if frame_id is None:
            return jsonify({
                "status": "error",
                "message": "Frame ID is required"
            }), 400

        if not edited_image_url:
            return jsonify({
                "status": "error",
                "message": "Edited image is required"
            }), 400

        # Validate base64 image format
        if not edited_image_url.startswith('data:image'):
            return jsonify({
                "status": "error",
                "message": "Invalid image format"
            }), 400

        # Decode base64 image
        try:
            base64_str = edited_image_url.split(',')[1]
            image_data = base64.b64decode(base64_str)
        except Exception as e:
            logger.error(f"Error decoding base64: {e}")
            return jsonify({
                "status": "error",
                "message": "Failed to decode image data"
            }), 400

        # Save to file
        session_id = session.get('session_id', 'default')
        edited_frames_dir = os.path.join('frames', session_id, 'edited')
        os.makedirs(edited_frames_dir, exist_ok=True)

        edited_image_path = os.path.join(edited_frames_dir, f'frame_{frame_id}_edited.png')

        try:
            with open(edited_image_path, 'wb') as f:
                f.write(image_data)
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return jsonify({
                "status": "error",
                "message": "Failed to save edited frame"
            }), 500

        # Store only the file path in session (not the base64 data)
        if 'edited_frames' not in session:
            session['edited_frames'] = {}

        session['edited_frames'][str(frame_id)] = edited_image_path

        logger.info(f"Saved edited frame {frame_id} to: {edited_image_path}")

        return jsonify({
            "status": "success",
            "message": "Frame saved",
            "file_path": edited_image_path
        })

    except Exception as e:
        logger.error(f"Error applying frame: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/frames/generate-video', methods=['POST'])
def generate_video_from_image():
    """
    Generate video from uploaded image (Demo: returns pre-saved video after 7s delay)
    """
    try:
        # Check if image file is provided
        if 'image' not in request.files:
            return jsonify({
                "status": "error",
                "message": "No image file provided"
            }), 400

        image_file = request.files['image']
        prompt = request.form.get('prompt', '')

        if not image_file.filename:
            return jsonify({
                "status": "error",
                "message": "No file selected"
            }), 400

        if not prompt:
            return jsonify({
                "status": "error",
                "message": "Prompt is required"
            }), 400

        # Save uploaded image (for reference, not used in demo)
        session_id = session.get('session_id', 'default')
        upload_dir = os.path.join('uploads', session_id, 'editor', 'temp_images')
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(image_file.filename)
        image_path = os.path.join(upload_dir, filename)
        image_file.save(image_path)

        logger.info(f"Image uploaded: {image_path}")
        logger.info(f"Prompt: {prompt}")

        # Generate video using Demo mode (7 second delay)
        api_key = os.getenv("GOOGLE_API_KEY", "demo-key")

        ai_editor = AIFrameEditor(api_key)

        # This will wait 7 seconds and return pre-saved demo video
        logger.info("[DEMO] Starting 7-second simulated generation...")
        demo_video_path = ai_editor.generate_video_from_image(
            image_path=image_path,
            prompt=prompt,
            output_path="",  # Not used in demo mode
            duration=8
        )

        # Store in session
        if 'generated_videos' not in session:
            session['generated_videos'] = []
        session['generated_videos'].append(demo_video_path)

        logger.info(f"[DEMO] Video ready: {demo_video_path}")

        # Return video URL (static file)
        video_url = f"/{demo_video_path}"

        return jsonify({
            "status": "success",
            "message": "Video generated successfully",
            "video_url": video_url,
            "video_path": demo_video_path
        })

    except FileNotFoundError as e:
        logger.error(f"Demo video not found: {e}")
        return jsonify({
            "status": "error",
            "message": "Demo video file is missing. Please add parking_lot_demo.mp4 to static/demo_videos/"
        }), 500
    except Exception as e:
        logger.error(f"Error generating video: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/video/editor')
def video_editor():
    """
    Load video editor UI
    """
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    return render_template('video_editor_ui.html')


@web_ui_blueprint.route('/video/export', methods=['POST'])
def export_video():
    """
    Export edited video
    """
    try:
        if 'editor_video' not in session:
            return jsonify({
                "status": "error",
                "message": "No video to export"
            }), 400

        # TODO: 編集済みフレームでビデオを再構成
        # For now, return the original video
        video_path = session['editor_video']

        return jsonify({
            "status": "success",
            "download_url": f"/download/editor?path={video_path}"
        })

    except Exception as e:
        logger.error(f"Error exporting video: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/download/editor')
def download_editor_video():
    """
    Download the edited video
    """
    try:
        video_path = request.args.get('path')

        if not video_path or not os.path.exists(video_path):
            return jsonify({"error": "Video not found"}), 404

        directory = os.path.dirname(video_path)
        filename = os.path.basename(video_path)
        return send_from_directory(directory, filename, as_attachment=True)

    except Exception as e:
        logger.error(f"Download error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Editor Chat Endpoints - 自然言語対話型動画制作
# -----------------------------------------------------------------------------

@web_ui_blueprint.route('/editor/chat', methods=['POST'])
def editor_chat():
    """
    統合チャットエンドポイント
    自然言語コマンドを解析して適切な機能にルーティング

    Supports both JSON and FormData (for image uploads with Generate mode)

    Request Body (JSON):
        {
            "message": str,  # ユーザーのチャット入力
            "session_id": str,  # オプション: セッションID（省略時は自動生成）
            "mode": str  # オプション: 選択されたモード（generate, extend, stitch, adjust）
        }

    Request Body (FormData):
        message: str  # ユーザーのチャット入力
        mode: str  # 選択されたモード
        image: File  # オプション: アップロードされた画像（Generateモード用）

    Returns:
        {
            "status": str,  # "success", "processing", "error", "clarification"
            "message": str,  # ユーザーへのフィードバック
            "intent": str,  # コマンドインテント
            "data": dict,   # 追加データ（task_id, scene_id, video_url, etc.）
            "chat_history": list  # チャット履歴
        }
    """
    try:
        # Handle both JSON and FormData
        if request.content_type and 'multipart/form-data' in request.content_type:
            user_input = request.form.get('message', '').strip()
            provided_session_id = request.form.get('session_id')
            selected_mode = request.form.get('mode')  # generate, extend, stitch, adjust
            uploaded_image = request.files.get('image')
        else:
            data = request.get_json()
            user_input = data.get('message', '').strip()
            provided_session_id = data.get('session_id')
            selected_mode = data.get('mode')
            uploaded_image = None

        if not user_input:
            return jsonify({
                "status": "error",
                "message": "メッセージが必要です"
            }), 400

        # セッションIDの管理
        if provided_session_id:
            session_id = provided_session_id
            session['editor_session_id'] = session_id
        elif 'editor_session_id' not in session:
            session_id = str(uuid.uuid4())
            session['editor_session_id'] = session_id
        else:
            session_id = session['editor_session_id']

        # チャット履歴の初期化
        if 'chat_history' not in session:
            session['chat_history'] = []

        # 会話コンテキストの初期化
        if 'conversation_context' not in session:
            session['conversation_context'] = {}

        # ユーザーメッセージを履歴に追加
        session['chat_history'].append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })

        logger.info(f"Editor chat: session_id={session_id}, input={user_input}, mode={selected_mode}")

        # Handle Generate mode with conversation flow
        if selected_mode == 'generate':
            result = _handle_generate_mode(user_input, uploaded_image, session_id)

        # Handle other modes (Extend, Stitch, Adjust) - to be implemented
        elif selected_mode == 'extend':
            result = {
                "status": "error",
                "message": "Extendモードは現在開発中です"
            }
        elif selected_mode == 'stitch':
            result = {
                "status": "error",
                "message": "Stitchモードは現在開発中です"
            }
        elif selected_mode == 'adjust':
            result = {
                "status": "error",
                "message": "Adjustモードは現在開発中です"
            }
        else:
            # Fallback to legacy command parsing
            handler = ChatCommandHandler()
            command = handler.parse_command(user_input)

            # コマンドバリデーション
            is_valid, error_message = handler.validate_command(command)
            if not is_valid:
                session['chat_history'].append({
                    "role": "assistant",
                    "content": error_message,
                    "timestamp": datetime.now().isoformat()
                })
                return jsonify({
                    "status": "error",
                    "message": error_message,
                    "intent": command['intent'].value,
                    "chat_history": session['chat_history']
                }), 400

            # SceneManager初期化
            scene_manager = SceneManager(session_id)

            # インテントに応じて処理分岐
            intent = command['intent']
            params = command['params']

            if intent == CommandIntent.CREATE:
                result = _handle_create_video(params, scene_manager, session_id)

            elif intent == CommandIntent.EXTEND:
                result = _handle_extend_scene(params, scene_manager, session_id)

            elif intent == CommandIntent.TRANSITION:
                result = _handle_merge_scenes(params, scene_manager, session_id)

            elif intent == CommandIntent.FRAME_EDIT:
                result = _handle_frame_edit(params, scene_manager, session_id)

            else:
                result = {
                    "status": "error",
                    "message": handler.get_intent_help_message(intent)
                }

        # アシスタントの応答を履歴に追加
        session['chat_history'].append({
            "role": "assistant",
            "content": result.get('message', ''),
            "timestamp": datetime.now().isoformat(),
            "data": result
        })

        # チャット履歴を結果に含める
        result['chat_history'] = session['chat_history']

        return jsonify(result)

    except Exception as e:
        logger.error(f"Editor chat error: {e}", exc_info=True)
        error_message = f"エラーが発生しました: {str(e)}"

        # エラーも履歴に追加
        if 'chat_history' in session:
            session['chat_history'].append({
                "role": "assistant",
                "content": error_message,
                "timestamp": datetime.now().isoformat(),
                "error": True
            })

        return jsonify({
            "status": "error",
            "message": error_message,
            "chat_history": session.get('chat_history', [])
        }), 500


@web_ui_blueprint.route('/editor/chat/history', methods=['GET'])
def get_chat_history():
    """
    チャット履歴を取得

    Returns:
        {
            "chat_history": list,
            "session_id": str
        }
    """
    try:
        return jsonify({
            "chat_history": session.get('chat_history', []),
            "session_id": session.get('editor_session_id')
        })
    except Exception as e:
        logger.error(f"Get chat history error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@web_ui_blueprint.route('/editor/chat/clear', methods=['POST'])
def clear_chat_history():
    """
    チャット履歴をクリア

    Returns:
        {
            "status": str,
            "message": str
        }
    """
    try:
        session['chat_history'] = []
        return jsonify({
            "status": "success",
            "message": "チャット履歴をクリアしました"
        })
    except Exception as e:
        logger.error(f"Clear chat history error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@web_ui_blueprint.route('/editor/timeline', methods=['GET'])
def get_timeline():
    """
    タイムライン情報を取得

    Returns:
        {
            "session_id": str,
            "scene_count": int,
            "total_duration": float,
            "scenes": list
        }
    """
    try:
        session_id = session.get('editor_session_id')
        if not session_id:
            return jsonify({
                "status": "error",
                "message": "セッションが見つかりません"
            }), 404

        scene_manager = SceneManager(session_id)
        timeline_data = scene_manager.export_timeline()

        return jsonify(timeline_data)

    except Exception as e:
        logger.error(f"Get timeline error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# -----------------------------------------------------------------------------
# Chat Command Handlers - コマンドハンドラー（内部関数）
# -----------------------------------------------------------------------------

def _handle_generate_mode(user_input: str, uploaded_image, session_id: str) -> Dict[str, Any]:
    """
    Generateモードの会話フロー管理

    フロー:
    1. 初回: 画像確認 → duration timeを聞く
    2. 返答: durationを抽出 → 動画生成 → 動画URLを返す

    Args:
        user_input: ユーザーの入力メッセージ
        uploaded_image: アップロードされた画像（FileStorage）
        session_id: セッションID

    Returns:
        {
            "status": "success" | "clarification" | "error",
            "message": str,
            "data": {
                "video_url": str,  # 生成された動画URL（生成完了時）
                "step": str  # 現在のステップ
            }
        }
    """
    import re
    import os
    from werkzeug.utils import secure_filename
    from frame_editor import AIFrameEditor

    # 会話コンテキストの取得
    context = session.get('conversation_context', {})
    current_step = context.get('step', 'initial')

    logger.info(f"Generate mode: step={current_step}, user_input={user_input}, has_image={uploaded_image is not None}")

    # Step 1: 初回メッセージ - 画像確認とduration確認
    if current_step == 'initial' or current_step == '':
        # 画像が添付されているかチェック
        if not uploaded_image:
            return {
                "status": "error",
                "message": "画像を添付してください。画像から動画を生成します。",
                "data": {"step": "waiting_for_image"}
            }

        # 画像を保存
        try:
            # セッション用のディレクトリを作成
            upload_dir = os.path.join('uploads', session_id, 'editor')
            os.makedirs(upload_dir, exist_ok=True)

            # ファイル名をセキュアに処理
            filename = secure_filename(uploaded_image.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            image_filename = f"generate_{timestamp}_{filename}"
            image_path = os.path.join(upload_dir, image_filename)

            # 画像を保存
            uploaded_image.save(image_path)
            logger.info(f"Image saved: {image_path}")

            # コンテキストに画像パスとプロンプトを保存
            session['conversation_context'] = {
                'mode': 'generate',
                'step': 'waiting_for_duration',
                'image_path': image_path,
                'prompt': user_input
            }
            session.modified = True

            # duration timeを聞く
            return {
                "status": "clarification",
                "message": f"画像を受け取りました！\n\n何秒の動画を生成しますか？（例: 5秒、10秒など）",
                "data": {"step": "waiting_for_duration"}
            }

        except Exception as e:
            logger.error(f"Image upload error: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"画像のアップロードに失敗しました: {str(e)}",
                "data": {"step": "error"}
            }

    # Step 2: Duration確認 → 動画生成
    elif current_step == 'waiting_for_duration':
        # Durationを抽出
        duration_match = re.search(r'(\d+)\s*[秒s]', user_input)
        if duration_match:
            duration = int(duration_match.group(1))
        else:
            # 数字だけの場合も対応
            number_match = re.search(r'(\d+)', user_input)
            if number_match:
                duration = int(number_match.group(1))
            else:
                # Durationが見つからない場合
                return {
                    "status": "clarification",
                    "message": "すみません、何秒の動画を生成するか数字で教えてください。（例: 5、10など）",
                    "data": {"step": "waiting_for_duration"}
                }

        # Durationの範囲チェック（1-30秒）
        if duration < 1 or duration > 30:
            return {
                "status": "clarification",
                "message": "動画の長さは1秒から30秒の間で指定してください。",
                "data": {"step": "waiting_for_duration"}
            }

        # 保存された画像パスとプロンプトを取得
        image_path = context.get('image_path')
        prompt = context.get('prompt', '')

        if not image_path or not os.path.exists(image_path):
            # 画像が見つからない場合、最初からやり直し
            session['conversation_context'] = {}
            session.modified = True
            return {
                "status": "error",
                "message": "画像が見つかりません。もう一度画像を添付してください。",
                "data": {"step": "initial"}
            }

        try:
            # 動画生成
            logger.info(f"Generating video: image={image_path}, duration={duration}s, prompt={prompt}")

            ai_editor = AIFrameEditor(api_key=os.getenv('GOOGLE_API_KEY'))
            video_path = ai_editor.generate_video_from_image(
                image_path=image_path,
                prompt=prompt,
                duration=duration
            )

            # 動画URLを生成（相対パス）
            video_url = f"/{video_path}"

            # コンテキストをクリア（会話終了）
            session['conversation_context'] = {}
            session.modified = True

            logger.info(f"Video generated successfully: {video_path}")

            return {
                "status": "success",
                "message": f"✅ {duration}秒の動画を生成しました！プレビューを確認してください。\n\n満足したら「Apply to Main Player」ボタンを押してください。",
                "data": {
                    "step": "completed",
                    "video_url": video_url,
                    "video_path": video_path,
                    "duration": duration
                }
            }

        except Exception as e:
            logger.error(f"Video generation error: {e}", exc_info=True)
            # エラー時もコンテキストをクリア
            session['conversation_context'] = {}
            session.modified = True
            return {
                "status": "error",
                "message": f"動画の生成に失敗しました: {str(e)}",
                "data": {"step": "error"}
            }

    else:
        # 不明なステップ - リセット
        session['conversation_context'] = {}
        session.modified = True
        return {
            "status": "error",
            "message": "会話の状態が不明です。もう一度最初から始めてください。",
            "data": {"step": "initial"}
        }


def _handle_create_video(params: Dict[str, Any], scene_manager: SceneManager, session_id: str) -> Dict[str, Any]:
    """
    ① 動画生成処理

    Args:
        params: コマンドパラメータ
        scene_manager: SceneManagerインスタンス
        session_id: セッションID

    Returns:
        結果辞書
    """
    logger.info(f"Handling CREATE command: {params}")

    # 画像パスの検証
    image_path = params.get('image_path')

    # TODO: 画像パスが指定されていない場合、セッションのアップロードから取得
    # または、プロンプトのみでテキストから動画生成（Veo API対応時）

    if not image_path:
        return {
            "status": "error",
            "message": "画像パスを指定してください（例: 「image1.jpgから動画を作って」）",
            "intent": "create"
        }

    # 画像ファイルの存在確認（ローカルまたはアップロード済み）
    # MVPでは簡易実装: セッションのuploadディレクトリを確認
    upload_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id)
    full_image_path = os.path.join(upload_dir, image_path)

    if not os.path.exists(full_image_path):
        # グローバルアップロードディレクトリも確認
        full_image_path = os.path.join(LOCAL_UPLOAD_ROOT, image_path)
        if not os.path.exists(full_image_path):
            return {
                "status": "error",
                "message": f"画像が見つかりません: {image_path}。先にアップロードしてください。",
                "intent": "create"
            }

    # 次のシーンIDを生成
    scene_id = scene_manager.generate_next_scene_id()

    # Celeryタスクとして非同期実行
    # TODO: tasks.pyにgenerate_video_from_chat_taskを実装
    try:
        from tasks import generate_video_from_chat_task

        task = generate_video_from_chat_task.delay(
            session_id=session_id,
            scene_id=scene_id,
            image_path=full_image_path,
            prompt=params.get('prompt'),
            duration=params.get('duration', '8s'),
            aspect_ratio=params.get('aspect_ratio', '16:9'),
            resolution=params.get('resolution', '720p')
        )

        logger.info(f"Video generation task started: task_id={task.id}, scene_id={scene_id}")

        return {
            "status": "processing",
            "task_id": task.id,
            "scene_id": scene_id,
            "message": f"動画を生成中です（約2-5分）...\nシーンID: {scene_id}",
            "intent": "create"
        }

    except ImportError:
        # タスクが未実装の場合の暫定対応
        logger.warning("generate_video_from_chat_task not implemented yet")
        return {
            "status": "error",
            "message": "動画生成機能は現在開発中です。tasks.pyにgenerate_video_from_chat_taskを実装してください。",
            "intent": "create"
        }


def _handle_extend_scene(params: Dict[str, Any], scene_manager: SceneManager, session_id: str) -> Dict[str, Any]:
    """
    ② シーン拡張処理

    Args:
        params: コマンドパラメータ
        scene_manager: SceneManagerインスタンス
        session_id: セッションID

    Returns:
        結果辞書
    """
    logger.info(f"Handling EXTEND command: {params}")

    # 最後のシーンを取得
    last_scene = scene_manager.get_last_scene()

    if not last_scene:
        return {
            "status": "error",
            "message": "まず最初のシーンを作成してください（例: 「image1.jpgから動画を作って」）",
            "intent": "extend"
        }

    # 新しい画像パス
    new_image_path = params.get('image_path')

    if not new_image_path:
        return {
            "status": "error",
            "message": "新しいシーンの画像パスを指定してください（例: 「image2.jpgで続きを作って」）",
            "intent": "extend"
        }

    # 画像ファイルの存在確認
    upload_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id)
    full_image_path = os.path.join(upload_dir, new_image_path)

    if not os.path.exists(full_image_path):
        full_image_path = os.path.join(LOCAL_UPLOAD_ROOT, new_image_path)
        if not os.path.exists(full_image_path):
            return {
                "status": "error",
                "message": f"画像が見つかりません: {new_image_path}",
                "intent": "extend"
            }

    # 次のシーンIDを生成
    scene_id = scene_manager.generate_next_scene_id()

    # Celeryタスクとして非同期実行
    try:
        from tasks import extend_scene_task

        task = extend_scene_task.delay(
            session_id=session_id,
            scene_id=scene_id,
            previous_scene_id=last_scene.scene_id,
            new_image_path=full_image_path,
            prompt=params.get('prompt'),
            duration=params.get('duration', '8s'),
            aspect_ratio=params.get('aspect_ratio', '16:9'),
            resolution=params.get('resolution', '720p')
        )

        logger.info(f"Scene extension task started: task_id={task.id}, scene_id={scene_id}")

        return {
            "status": "processing",
            "task_id": task.id,
            "scene_id": scene_id,
            "previous_scene_id": last_scene.scene_id,
            "message": f"{last_scene.scene_id}の次のシーンを生成中...\n新しいシーンID: {scene_id}",
            "intent": "extend"
        }

    except ImportError:
        logger.warning("extend_scene_task not implemented yet")
        return {
            "status": "error",
            "message": "シーン拡張機能は現在開発中です。tasks.pyにextend_scene_taskを実装してください。",
            "intent": "extend"
        }


def _handle_merge_scenes(params: Dict[str, Any], scene_manager: SceneManager, session_id: str) -> Dict[str, Any]:
    """
    ③ 動画連結処理

    Args:
        params: コマンドパラメータ
        scene_manager: SceneManagerインスタンス
        session_id: セッションID

    Returns:
        結果辞書
    """
    logger.info(f"Handling TRANSITION command: {params}")

    scenes = scene_manager.get_all_scenes()

    if len(scenes) < 2:
        return {
            "status": "error",
            "message": "最低2つのシーンが必要です。先にシーンを追加してください。",
            "intent": "transition"
        }

    # Celeryタスクとして非同期実行
    try:
        from tasks import merge_scenes_task

        task = merge_scenes_task.delay(
            session_id=session_id,
            transition_type=params.get('transition_type', 'cut')
        )

        logger.info(f"Scene merge task started: task_id={task.id}")

        return {
            "status": "processing",
            "task_id": task.id,
            "scene_count": len(scenes),
            "transition_type": params.get('transition_type', 'cut'),
            "message": f"{len(scenes)}つのシーンを{params.get('transition_type', 'cut')}で連結中...",
            "intent": "transition"
        }

    except ImportError:
        logger.warning("merge_scenes_task not implemented yet")
        return {
            "status": "error",
            "message": "シーン連結機能は現在開発中です。tasks.pyにmerge_scenes_taskを実装してください。",
            "intent": "transition"
        }


def _handle_frame_edit(params: Dict[str, Any], scene_manager: SceneManager, session_id: str) -> Dict[str, Any]:
    """
    ④ フレーム編集処理

    Args:
        params: コマンドパラメータ
        scene_manager: SceneManagerインスタンス
        session_id: セッションID

    Returns:
        結果辞書
    """
    logger.info(f"Handling FRAME_EDIT command: {params}")

    # シーンIDの取得
    scene_id = params.get('scene_id')

    if not scene_id:
        # scene_idが指定されていない場合、最後のシーンを対象
        last_scene = scene_manager.get_last_scene()
        if not last_scene:
            return {
                "status": "error",
                "message": "編集するシーンがありません。先にシーンを作成してください。",
                "intent": "frame_edit"
            }
        scene_id = last_scene.scene_id

    scene = scene_manager.get_scene(scene_id)
    if not scene:
        return {
            "status": "error",
            "message": f"シーンが見つかりません: {scene_id}",
            "intent": "frame_edit"
        }

    # タイムスタンプからフレームを抽出
    timestamp = params.get('timestamp', 0.0)

    # 既存のフレーム編集機能を活用
    # （MVPでは簡易実装: 最初のフレームを編集）
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return {
                "status": "error",
                "message": "GOOGLE_API_KEYが設定されていません",
                "intent": "frame_edit"
            }

        # フレーム抽出
        frame_editor = FrameEditor(scene.video_path)
        # タイムスタンプに最も近いフレームを抽出
        # TODO: extract_frame_at_time メソッドを実装
        # 暫定: 最初のフレームを使用
        frames = frame_editor.extract_frames(num_frames=1)
        if not frames:
            return {
                "status": "error",
                "message": "フレームの抽出に失敗しました",
                "intent": "frame_edit"
            }

        frame_path = frames[0]['path']

        # AI編集
        ai_editor = AIFrameEditor(api_key)
        variations = ai_editor.generate_frame_variations(
            base_image_path=frame_path,
            prompt=params.get('prompt'),
            variation_count=4
        )

        return {
            "status": "success",
            "scene_id": scene_id,
            "timestamp": timestamp,
            "variations": variations,
            "message": f"{scene_id}のフレームを編集しました。4つのバリエーションから選択してください。",
            "intent": "frame_edit"
        }

    except Exception as e:
        logger.error(f"Frame edit error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"フレーム編集エラー: {str(e)}",
            "intent": "frame_edit"
        }
