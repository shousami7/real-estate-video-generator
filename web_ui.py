import os
import json
import uuid
import logging
from typing import Any, Dict, List, Optional
from google import genai

from flask import (
    Blueprint, render_template, request, jsonify, session, send_from_directory, redirect, url_for
)
from werkzeug.utils import secure_filename
from celery import states
from celery.result import AsyncResult

from frame_editor import FrameEditor, AIFrameEditor
from celery_app import celery, store_task_video_mapping, get_task_video_mapping
from utils.response_utils import build_task_response
from supabase_storage import (
    is_supabase_configured,
    is_supabase_required,
    get_initialization_error,
    upload_bytes_to_supabase,
    build_storage_path,
    SUPABASE_CLIENT,
    SUPABASE_BUCKET_NAME,
)
from chat_command_handler import ChatCommandHandler, CommandIntent
from scene_manager import SceneManager
from datetime import datetime
from utils.video_duration import probe_video_duration as get_video_duration

# Cache for Supabase task logs to prevent redundant downloads
_TASK_LOG_CACHE: Dict[str, dict] = {}

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
    init_error = get_initialization_error()
    if init_error:
        message = f"⚠️  Supabase not available: {init_error}"
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


def _ingest_api_image(video_id: str, image_file: Any, stage: str) -> tuple[Optional[str], Optional[tuple]]:
    """
    Helper to process image uploads for API endpoints.
    Returns (image_path, error_response).
    If error_response is set, return it immediately.
    """
    if not image_file or not image_file.filename:
        return None, None

    filename = secure_filename(image_file.filename)
    storage_path = build_storage_path(video_id, "input", filename)
    file_bytes = image_file.read()

    if not file_bytes:
        return None, (jsonify(build_task_response(
            task_id="",
            video_id=video_id,
            stage=stage,
            status="error",
            error="Empty image file"
        )), 400)

    # Save locally
    local_path = _save_bytes_to_local_storage(storage_path, file_bytes)
    
    # Upload to Supabase if configured
    if is_supabase_configured():
        _, upload_error = upload_bytes_to_supabase(
            storage_path=storage_path,
            file_bytes=file_bytes,
            content_type=image_file.content_type or "image/jpeg"
        )
        if upload_error:
            logger.warning(f"Supabase upload failed: {upload_error}")

    return local_path, None


def _load_task_log(video_id: str, task_id: str) -> Optional[dict]:
    """
    Load task log from Supabase with caching.
    """
    cached = _TASK_LOG_CACHE.get(task_id)
    if cached:
        return cached

    if not is_supabase_configured():
        return None

    try:
        log_path = build_storage_path(video_id, "logs", f"{task_id}.json")
        log_bytes = SUPABASE_CLIENT.storage.from_(SUPABASE_BUCKET_NAME).download(log_path)
        if log_bytes:
            data = json.loads(log_bytes)
            _TASK_LOG_CACHE[task_id] = data
            return data
    except Exception as e:
        logger.warning(f"Could not load task log from Supabase: {e}")
    
    return None


REQUIRED_TASK_KEYS = {
    "task_id", "video_id", "stage", "status", "output_url", "frames", "error"
}


def _has_full_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and REQUIRED_TASK_KEYS.issubset(payload.keys())

@web_ui_blueprint.route('/')
def index():
    """Redirect to video editor (legacy UI has been removed)."""
    return redirect(url_for('web_ui.video_editor'))



@web_ui_blueprint.route('/status')
def get_status():
    """
    Check the progress of the async video generation task.
    Includes defensive handling for corrupted Celery backend data.
    """
    task_id = request.args.get('task_id') or session.get('generation_task_id')

    if not task_id:
        return jsonify({
            "status": "IDLE",
            "message": "Upload Progress",
            "progress_percent": 0
        })

    task = AsyncResult(task_id, app=celery)

    # Safely access task.state and task.info - catch backend deserialization errors
    try:
        task_state = task.state
    except (ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning(f"Task {task_id} has corrupted backend state: {e}")
        return jsonify({
            "status": "ERROR",
            "message": "Task data corrupted in backend. Please retry the operation.",
            "progress_percent": 0
        })

    try:
        task_info = task.info
    except (ValueError, KeyError, AttributeError, TypeError) as e:
        logger.warning(f"Task {task_id} info deserialization failed: {e}")
        task_info = None

    meta = task_info if isinstance(task_info, dict) else {}
    video_id = get_task_video_mapping(task_id) or meta.get('video_id') or session.get('session_id')
    progress = meta.get('progress', session.get('generation_progress', 0))
    message = meta.get('message', "Processing video request...")
    stage = meta.get('stage', task_state)
    step = meta.get('step') or stage

    if task_state == states.PENDING:
        session['generation_status'] = 'QUEUED'
        session['generation_progress'] = progress
        return jsonify({
            "status": "QUEUED",
            "message": "Waiting for an available worker...",
            "progress_percent": progress,
            "video_id": video_id,
            "stage": stage,
        })

    if task_state in {'STARTED', 'GENERATING_CLIPS', 'COMPOSING'}:
        session['generation_status'] = step
        session['generation_progress'] = progress
        session.modified = True
        return jsonify({
            "status": step or "GENERATING_CLIPS",
            "message": message,
            "progress_percent": progress,
            "video_id": video_id,
            "stage": stage,
        })

    if task_state == states.SUCCESS:
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
            "editor_url": "/video/editor",
            "video_id": video_id,
            "stage": meta.get('stage') or stage,
        })

    if task_state in {states.FAILURE, states.REVOKED}:
        error_msg = session.get('generation_error')
        if not error_msg:
            if isinstance(task_info, Exception):
                error_msg = str(task_info)
            else:
                error_msg = meta.get('message', 'An unknown error occurred during video generation.')
        status_label = "CANCELLED" if task_state == states.REVOKED else "ERROR"
        session['generation_status'] = status_label
        session['generation_error'] = error_msg
        session['generation_progress'] = progress
        session.modified = True
        return jsonify({
            "status": status_label,
            "message": f"{status_label}: {error_msg}",
            "progress_percent": progress,
            "video_id": video_id,
            "stage": meta.get('stage') or stage,
        })

    # Fallback (should not normally reach here)
    return jsonify({
        "status": task_state or "IDLE",
        "message": message,
        "progress_percent": progress,
        "video_id": video_id,
        "stage": stage,
    })



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


@web_ui_blueprint.route('/output/<path:filename>')
def serve_output_file(filename):
    """
    Serve output files (generated videos, etc.)
    """
    try:
        # output ディレクトリからファイルを提供（絶対パス使用）
        output_dir = os.path.abspath('output')
        logger.info(f"Serving output file: {filename} from {output_dir}")
        return send_from_directory(output_dir, filename)
    except Exception as e:
        logger.error(f"Error serving output file {filename}: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": "File not found"
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

        ai_editor = AIFrameEditor(api_key=api_key)
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
        # Note: AIFrameEditor is currently a demo/placeholder.
        # If it becomes real, pass project_id/location here.
        ai_editor = AIFrameEditor()

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

@web_ui_blueprint.route('/editor/chat/generate', methods=['POST'])
def editor_chat_generate():
    """
    Generate mode endpoint - handles image-to-video generation with duration

    Request Form Data:
        - image: Image file
        - duration: Video duration in seconds
        - mode: "generate"

    Returns:
        {
            "status": "success" | "error",
            "message": str,
            "video_path": str,
            "video_url": str
        }
    """
    try:
        # Check if image file is provided
        if 'image' not in request.files:
            return jsonify({
                "status": "error",
                "message": "No image file provided"
            }), 400

        image_file = request.files['image']
        duration = request.form.get('duration', '8')

        if not image_file.filename:
            return jsonify({
                "status": "error",
                "message": "No file selected"
            }), 400

        # Parse duration
        try:
            duration_seconds = int(duration)
            if duration_seconds < 4 or duration_seconds > 20:
                duration_seconds = 8  # Default to 8 seconds if out of range
        except (ValueError, TypeError):
            duration_seconds = 8

        # Save uploaded image
        session_id = session.get('session_id', str(uuid.uuid4()))
        session['session_id'] = session_id

        upload_dir = os.path.join('uploads', session_id, 'editor', 'generate')
        os.makedirs(upload_dir, exist_ok=True)

        filename = secure_filename(image_file.filename)
        image_path = os.path.join(upload_dir, filename)
        image_file.save(image_path)

        logger.info(f"Image uploaded for generate mode: {image_path}")
        logger.info(f"Requested duration: {duration_seconds} seconds")

        # Get API configuration
        api_key = os.getenv("GOOGLE_API_KEY")

        if not api_key:
            return jsonify({
                "status": "error",
                "message": "GOOGLE_API_KEY must be configured for Google AI Studio"
            }), 500

        # Import veo_generator
        from veo_generator import VeoVideoGenerator

        # Generate video using VeoVideoGenerator
        logger.info(f"[GENERATE MODE] Starting video generation with {duration_seconds}s duration")

        veo = VeoVideoGenerator(api_key=api_key)

        output_dir = os.path.join('output', session_id, 'generated')
        os.makedirs(output_dir, exist_ok=True)

        output_filename = f"generated_{int(datetime.now().timestamp())}.mp4"
        output_path = os.path.join(output_dir, output_filename)

        # Generate video (this may take 2-5 minutes)
        prompt = f"Smooth camera movement showcasing the property"
        video_path = veo.generate_from_image_file(
            image_path=image_path,
            prompt=prompt,
            output_path=output_path,
            duration=f"{duration_seconds}s"  # Format as "6s", "8s", etc.
        )

        if not video_path or not os.path.exists(video_path):
            return jsonify({
                "status": "error",
                "message": "Video generation failed - no output file created"
            }), 500

        # Store in session
        if 'generated_videos' not in session:
            session['generated_videos'] = []
        session['generated_videos'].append(video_path)

        logger.info(f"[GENERATE MODE] Video ready: {video_path}")

        # Return video URL
        normalized_path = video_path.replace('\\', '/')
        video_url = f"/{normalized_path}"

        return jsonify({
            "status": "success",
            "message": f"{duration_seconds}-second video generated successfully",
            "video_path": video_path,
            "video_url": video_url,
            "duration": duration_seconds
        })

    except Exception as e:
        logger.error(f"Error in generate mode: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/editor/chat', methods=['POST'])
def editor_chat():
    """
    統合チャットエンドポイント
    自然言語コマンドを解析して適切な機能にルーティング

    Accepts either:
    - JSON: {"message": str, "session_id": str, "agent_mode": bool, "video_mode": str}
    - Multipart form data: message (text), image (file), session_id, agent_mode, video_mode

    Returns:
        {
            "status": str,  # "success", "processing", "error"
            "message": str,  # ユーザーへのフィードバック
            "intent": str,  # コマンドインテント
            "data": dict,   # 追加データ（task_id, scene_id, etc.）
            "chat_history": list  # チャット履歴
        }
    """
    try:
        # Handle both JSON and multipart form data
        if request.content_type and 'multipart/form-data' in request.content_type:
            # Multipart form data (with optional image upload)
            user_input = request.form.get('message', '').strip()
            provided_session_id = request.form.get('session_id')
            is_agent_mode = request.form.get('agent_mode', '').lower() in ['true', '1', 'yes']
            video_mode = request.form.get('video_mode')
            
            # Handle image upload
            image_file = request.files.get('image')
        else:
            # JSON data (text-only)
            data = request.get_json()
            user_input = data.get('message', '').strip()
            provided_session_id = data.get('session_id')
            is_agent_mode = bool(data.get('agent_mode'))
            video_mode = data.get('video_mode')
            image_file = None

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

        # Handle image upload if present
        if image_file and image_file.filename:
            upload_dir = os.path.join('uploads', session_id, 'editor', 'generate')
            os.makedirs(upload_dir, exist_ok=True)
            
            filename = secure_filename(image_file.filename)
            # Add timestamp to avoid overwriting
            timestamp = int(datetime.now().timestamp())
            filename = f"{timestamp}_{filename}"
            image_path = os.path.join(upload_dir, filename)
            image_file.save(image_path)
            
            logger.info(f"Image uploaded for agent mode: {image_path}")
            
            # Store the uploaded image path in session for reference
            if 'latest_uploaded_image' not in session:
                session['latest_uploaded_image'] = {}
            session['latest_uploaded_image'][session_id] = image_path

        # チャット履歴の初期化
        if 'chat_history' not in session:
            session['chat_history'] = []

        # ユーザーメッセージを履歴に追加
        session['chat_history'].append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat(),
            "has_image": bool(image_file and image_file.filename)
        })

        logger.info(f"Editor chat: session_id={session_id}, input={user_input}, has_image={bool(image_file and image_file.filename)}")

        # Agentモード: MCP/Gemini連携に切り替える場合はここで分岐
        if is_agent_mode:
            result = _handle_agent_mode(user_input, session_id, video_mode)
        else:
            # コマンド解釈
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
        # 循環参照を避けるため、chat_historyを除外したコピーを作成
        result_for_history = {k: v for k, v in result.items() if k != 'chat_history'}
        session['chat_history'].append({
            "role": "assistant",
            "content": result.get('message', ''),
            "timestamp": datetime.now().isoformat(),
            "data": result_for_history
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


def _handle_agent_mode(user_input: str, session_id: str, video_mode: str | None = None) -> dict:
    """
    Handle Agent (MCP/Gemini) mode.
    Uses Gemini to interpret the user's command and maps it to the appropriate Celery task.
    """
    logger.info(f"[AgentMode] session_id={session_id}, video_mode={video_mode}, input={user_input}")

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {
            "status": "error",
            "message": "GOOGLE_API_KEY is not configured. Please set it in your .env file.",
            "intent": "agent_error"
        }

    try:
        # 1. Initialize Gemini Client
        client = genai.Client(api_key=api_key)
        
        # 2. Define Tools (Schema)
        tools = [
            {
                "name": "generate_video",
                "description": "Generate a new video from a text prompt. Use this when the user wants to create a new video from scratch or from an uploaded image.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Text description of the video to generate"},
                        "duration": {"type": "string", "description": "Duration of the video (e.g. '8s')"},
                        "aspect_ratio": {"type": "string", "description": "Aspect ratio (e.g. '16:9')"}
                    },
                    "required": ["prompt"]
                }
            },
            {
                "name": "extend_video",
                "description": "Extend the current or specified video. Use this when the user wants to make the video longer or add a scene.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string", "description": "Description of the extension/next scene"},
                        "duration": {"type": "string", "description": "Duration to add (e.g. '8s')"}
                    },
                    "required": ["prompt"]
                }
            },
            {
                "name": "extract_frames",
                "description": "Extract frames from a video. Use this when the user wants to see specific frames or images from the video.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fps": {"type": "integer", "description": "Frames per second to extract"}
                    }
                }
            },
            {
                "name": "edit_frame",
                "description": "Edit a specific frame using AI. Use this when the user wants to modify an image or frame.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "frame_index": {"type": "integer", "description": "Index of the frame to edit"},
                        "instruction": {"type": "string", "description": "Instruction for editing"}
                    },
                    "required": ["frame_index", "instruction"]
                }
            },
            {
                "name": "stitch_videos",
                "description": "Stitch/Merge multiple scenes together. Use this when the user wants to combine clips into a final video.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "transition_type": {"type": "string", "description": "Transition type (cut, fade)"}
                    }
                }
            }
        ]

        def _find_latest_uploaded_image(session_id: str) -> Optional[str]:
            """Return the most recent image uploaded for the given session, if any."""
            latest_image = None

            if 'latest_uploaded_image' in session and session_id in session['latest_uploaded_image']:
                latest_image = session['latest_uploaded_image'][session_id]
                logger.info(f"Using image from chat upload: {latest_image}")

            if not latest_image:
                upload_dir = os.path.join('uploads', 'videos', session_id, 'input')
                if os.path.exists(upload_dir):
                    files = sorted(
                        [os.path.join(upload_dir, f) for f in os.listdir(upload_dir) if not f.startswith('.')],
                        key=os.path.getmtime,
                        reverse=True
                    )
                    if files:
                        latest_image = files[0]
                        logger.info(f"Using latest image from directory: {latest_image}")

            return latest_image

        # 3. Call Gemini to decide intent
        # We use a simplified prompt approach since we are inside the backend
        prompt = f"""
        You are an AI video production assistant. Your job is to interpret the user's request and select the best tool to execute it.
        
        User Request: "{user_input}"
        
        Available Tools:
        {json.dumps(tools, indent=2)}
        
        Respond ONLY with a valid JSON object in this format:
        {{
            "tool": "tool_name",
            "arguments": {{ ... }},
            "reply": "A brief, friendly message to the user confirming what you are doing."
        }}
        
        If the request is unclear or not related to video production, respond with:
        {{
            "tool": null,
            "reply": "I can help you generate, extend, edit, and stitch videos. Could you please clarify your request?"
        }}
        """

        response = client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        try:
            result = json.loads(response.text)
        except json.JSONDecodeError:
            # Fallback cleanup if model returns markdown code blocks
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:-3]
            result = json.loads(text)

        tool_name = result.get("tool")
        args = result.get("arguments", {})
        reply_message = result.get("reply", "Processing your request...")

        if not tool_name:
            return {
                "status": "success",
                "message": reply_message,
                "intent": "chat"
            }

        # 4. Execute the selected tool (Map to Celery Tasks)
        task = None
        task_type = "unknown"
        
        # Common args
        scene_manager = SceneManager(session_id)
        
        if tool_name == "generate_video":
            latest_image = _find_latest_uploaded_image(session_id)
            if not latest_image:
                return {
                    "status": "error",
                    "message": "I need an image to generate a video. Please upload an image first.",
                    "intent": "error"
                }

            task = celery.send_task('tasks.generate_video_from_chat_task', args=[
                session_id,
                str(uuid.uuid4()), # scene_id
                latest_image,
                args.get("prompt", user_input),
                args.get("duration", "8s"),
                args.get("aspect_ratio", "16:9"),
                "720p"
            ])
            task_type = "generate"

        elif tool_name == "extend_video":
            # Need previous scene ID
            scenes = scene_manager.get_all_scenes()
            if not scenes:
                return {
                    "status": "error",
                    "message": "No video found to extend. Please generate a video first.",
                    "intent": "error"
                }
            last_scene = scenes[-1]
            
            image_path = _find_latest_uploaded_image(session_id)
            if not image_path:
                return {
                    "status": "error",
                    "message": "I need an image to extend the video. Please upload an image for the extension.",
                    "intent": "error"
                }
            
            task = celery.send_task('tasks.extend_scene_task', args=[
                session_id,
                str(uuid.uuid4()), # new scene_id
                last_scene.scene_id, # previous_scene_id
                image_path, # new_image_path
                args.get("prompt", "Continue the video"),
                args.get("duration", "8s"),
                args.get("aspect_ratio", "16:9"),
                "720p"
            ])
            task_type = "extend"

        elif tool_name == "extract_frames":
            scenes = scene_manager.get_all_scenes()
            if not scenes:
                return {"status": "error", "message": "No video to extract frames from.", "intent": "error"}
            
            # We use the session_id as video_id for the task if we want to extract from the 'composed' video,
            # or the scene id. Let's default to the session context.
            task = celery.send_task('tasks.extract_frames_task', args=[
                session_id,
                None, # video_path (optional, task finds it)
                args.get("fps", 1)
            ])
            task_type = "extract"

        elif tool_name == "edit_frame":
            task = celery.send_task('tasks.edit_frame_task', args=[
                session_id,
                args.get("frame_index", 0),
                args.get("instruction", "")
            ])
            task_type = "edit"

        elif tool_name == "stitch_videos":
            task = celery.send_task('tasks.merge_scenes_task', args=[
                session_id,
                args.get("transition_type", "fade")
            ])
            task_type = "stitch"

        if task:
            store_task_video_mapping(task.id, session_id)
            
            # Build plan sheet data for frontend visualization
            plan_sheet = None
            if tool_name in ["generate_video", "extend_video"]:
                # Extract duration value (remove 's' suffix if present)
                duration_str = args.get("duration", "8s")
                duration_value = int(duration_str.rstrip('s')) if isinstance(duration_str, str) else int(duration_str)
                
                plan_sheet = {
                    "mode": "Generate" if tool_name == "generate_video" else "Extend",
                    "duration": duration_value,
                    "prompt": args.get("prompt", user_input),
                    "pic": "yes",  # We require an image for both generate and extend
                    "task_id": task.id
                }
            
            return {
                "status": "processing",
                "message": reply_message,
                "intent": task_type,
                "data": {
                    "task_id": task.id,
                    "video_id": session_id,
                    "plan_sheet": plan_sheet  # Include plan sheet for frontend
                }
            }
        else:
             return {
                "status": "error",
                "message": "Failed to create task for the selected tool.",
                "intent": "error"
            }

    except Exception as e:
        logger.error(f"Agent mode error: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"I encountered an error processing your request: {str(e)}",
            "intent": "error"
        }


# -----------------------------------------------------------------------------
# MCP Task Status Endpoint
# -----------------------------------------------------------------------------

@web_ui_blueprint.route('/api/task/<task_id>/cancel', methods=['POST'])
def api_cancel_task(task_id):
    """
    Cancel a running Celery task.
    """
    try:
        # Revoke the task
        celery.control.revoke(task_id, terminate=True)
        
        # Update our local mapping if needed (optional, but good for consistency)
        # In a real app, we might want to mark it as cancelled in a DB
        
        logger.info(f"Task {task_id} cancelled by user request")
        
        return jsonify({
            "status": "success",
            "message": "Task cancellation requested"
        })
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@web_ui_blueprint.route('/api/task/<task_id>/status', methods=['GET'])
def get_task_status(task_id: str):
    """
    Get unified task status for MCP orchestration.

    Includes defensive handling for corrupted Celery backend data.
    Returns error status instead of crashing when task metadata
    cannot be deserialized.

    Returns:
        {
            "task_id": str,
            "video_id": str,
            "status": "pending" | "running" | "completed" | "error",
            "stage": str,
            "progress": int | null,
            "output_url": str | null,
            "frames": list | null,
            "error": str | null
        }
    """
    try:
        # Query Celery AsyncResult
        task = AsyncResult(task_id, app=celery)

        # Get video_id from backend mapping first (fallback to task metadata/session)
        video_id = get_task_video_mapping(task_id) or session.get('editor_session_id') or session.get('session_id')

        # Safely access task.state - catch backend deserialization errors
        try:
            task_state = task.state
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            # Backend has corrupted/invalid exception data - treat as error state
            logger.warning(f"Task {task_id} has corrupted backend state: {e}")
            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id or "unknown",
                stage="unknown",
                status="error",
                error="Task data corrupted in backend. Please retry the operation.",
            ))

        # Safely access task.info and task.result once, cache for reuse
        try:
            task_info = task.info
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Task {task_id} info deserialization failed: {e}")
            task_info = None

        try:
            task_result = task.result
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.warning(f"Task {task_id} result deserialization failed: {e}")
            task_result = None

        if task_state == states.PENDING:
            # Task not yet started
            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id or "unknown",
                stage="unknown",
                status="pending",
            ))

        elif task_state in {states.STARTED, 'GENERATING_CLIPS', 'COMPOSING', 'GENERATING', 'EXTENDING', 'DOWNLOADING', 'SAVING', 'MERGING', 'UPLOADING'}:
            # Task is running
            meta = task_info if isinstance(task_info, dict) else {}
            meta_video_id = meta.get('video_id')
            video_id = meta_video_id or get_task_video_mapping(task_id) or video_id or "unknown"
            progress = meta.get("progress", 0)

            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id or "unknown",
                stage=meta.get('stage') or 'unknown',
                status="running",
                progress=progress,
            ))

        elif task_state == states.SUCCESS:
            # Task completed - MUST load log file from Supabase
            result = task_result if isinstance(task_result, dict) else {}
            video_id = result.get('video_id') or get_task_video_mapping(task_id) or video_id or "unknown"

            # 1) If Celery result already contains the full unified payload, return it
            if _has_full_payload(result):
                return jsonify(result)

            # 2) If not full, try loading from Supabase log (with cache)
            log_data = _load_task_log(video_id, task_id)
            if log_data and _has_full_payload(log_data):
                return jsonify(log_data)

            # 3) Fallback: construct response from task result or defaults
            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id,
                stage=result.get('stage', 'unknown'),
                status="completed",
                output_url=result.get('output_url') or result.get('final_video'),
                frames=result.get('frames'),
                error=result.get('error'),
            ))

        elif task_state in {states.FAILURE, states.REVOKED}:
            # Task failed
            error_msg = str(task_info) if task_info else "Task failed or was revoked"
            # If Celery result already contains a unified error payload, return it directly
            if isinstance(task_result, dict):
                result = task_result
                if all(k in result for k in ["task_id", "video_id", "stage", "status", "output_url", "frames", "error"]):
                    return jsonify(result)

            # Try to load error log from Supabase only if needed
            if video_id and video_id != "unknown":
                log_data = _load_task_log(video_id, task_id)
                if log_data and log_data.get('status') == 'error':
                    return jsonify(log_data)

            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id or "unknown",
                stage="unknown",
                status="error",
                error=error_msg,
            ))

        else:
            # Unknown state
            return jsonify(build_task_response(
                task_id=task_id,
                video_id=video_id or "unknown",
                stage="unknown",
                status="pending",
            ))

    except Exception as e:
        logger.error(f"Error getting task status: {e}", exc_info=True)
        mapped_video_id = get_task_video_mapping(task_id)
        return jsonify(build_task_response(
            task_id=task_id,
            video_id=mapped_video_id or video_id or "unknown",
            stage="unknown",
            status="error",
            error=str(e),
        )), 500


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
# MCP Pipeline API Endpoints
# -----------------------------------------------------------------------------

@web_ui_blueprint.route('/api/chat/upload', methods=['POST'])
def chat_upload_image():
    """
    Upload a single image for chat context.
    Returns the relative path to the uploaded file.
    """
    try:
        if 'image' not in request.files:
            return jsonify({
                "status": "error",
                "message": "No image file provided"
            }), 400

        file = request.files['image']
        if file.filename == '':
            return jsonify({
                "status": "error",
                "message": "No file selected"
            }), 400

        # Reuse the same chat/editor session so agent mode can find the upload later
        session_id = session.get('editor_session_id') or session.get('session_id')
        if not session_id:
            session_id = str(uuid.uuid4())
        session['editor_session_id'] = session_id
        session['session_id'] = session_id  # keep in sync with other endpoints
        
        # Use standard Supabase structure: videos/{session_id}/input/
        filename = secure_filename(file.filename)
        storage_path = build_storage_path(session_id, "input", filename)
        
        file_bytes = file.read()
        local_path = _save_bytes_to_local_storage(storage_path, file_bytes)
        
        # Upload to Supabase if available
        public_url = None
        if is_supabase_configured():
            public_url, upload_error = upload_bytes_to_supabase(
                storage_path=storage_path,
                file_bytes=file_bytes,
                content_type=file.content_type or "image/jpeg"
            )
            if upload_error:
                logger.warning(f"Supabase upload failed: {upload_error}")
        
        # Store the uploaded image path in session for Agent Mode reference
        if 'latest_uploaded_image' not in session:
            session['latest_uploaded_image'] = {}
        
        # Use the session_id that was used for the upload (video_id)
        session['latest_uploaded_image'][session_id] = local_path
        logger.info(f"Stored uploaded image in session for {session_id}: {local_path}")

        return jsonify({
            "status": "success",
            "filename": filename,
            "local_path": local_path,
            "public_url": public_url or f"/uploads/local/{storage_path}"
        })

    except Exception as e:
        logger.error(f"Chat upload error: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@web_ui_blueprint.route('/api/generate', methods=['POST'])
def api_generate_video():
    """
    MCP Pipeline API: Generate video from prompt and optional image.

    Request (multipart/form-data or JSON):
        - prompt: str (required) - Video generation prompt
        - video_id: str (optional) - Session/video ID for context
        - image: file (required for now) - Image file for image-to-video
        - duration: int (optional) - Video duration in seconds (4-20, default: 8)

    Returns (202 Accepted):
        {
            "task_id": str,
            "video_id": str,
            "stage": "generate",
            "status": "running",
            "progress": int | null,
            "output_url": null,
            "frames": null,
            "error": null
        }
    """
    try:
        # Parse request data (support both JSON and form data)
        if request.is_json:
            data = request.get_json()
            prompt = data.get('prompt')
            video_id = data.get('video_id')
            duration = data.get('duration', 8)
            image_file = None
        else:
            prompt = request.form.get('prompt')
            video_id = request.form.get('video_id')
            duration = request.form.get('duration', 8)
            image_file = request.files.get('image')

        # Validate prompt
        if not prompt:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id or "unknown",
                stage="generate",
                status="error",
                error="Prompt is required"
            )), 400

        # Parse duration
        try:
            duration_seconds = int(duration)
            if duration_seconds < 4 or duration_seconds > 20:
                duration_seconds = 8
        except (ValueError, TypeError):
            duration_seconds = 8

        # Get or create video_id (session_id)
        if not video_id:
            video_id = str(uuid.uuid4())
        session['api_session_id'] = video_id

        # Handle image upload if provided
        image_path, error_resp = _ingest_api_image(video_id, image_file, "generate")
        if error_resp:
            return error_resp

        # Check if we have an image (required for now)
        if not image_path:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="generate",
                status="error",
                error="Image file is required. Please upload an image."
            )), 400

        # Generate scene_id
        scene_manager = SceneManager(video_id)
        scene_id = scene_manager.generate_next_scene_id()

        # Launch Celery task
        from tasks import generate_video_from_chat_task

        task = generate_video_from_chat_task.apply_async(
            args=[video_id, scene_id, image_path, prompt],
            kwargs={
                "duration": f"{duration_seconds}s",
                "aspect_ratio": "16:9",
                "resolution": "720p"
            }
        )

        logger.info(f"[MCP API] Video generation started: task_id={task.id}, video_id={video_id}, scene_id={scene_id}")
        store_task_video_mapping(task.id, video_id)

        # Return unified response
        return jsonify(build_task_response(
            task_id=task.id,
            video_id=video_id,
            stage="generate",
            status="running",
        )), 202

    except Exception as e:
        logger.error(f"[MCP API] Generate error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id if 'video_id' in locals() else "unknown",
            stage="generate",
            status="error",
            error=str(e)
        )), 500


@web_ui_blueprint.route('/api/extend', methods=['POST'])
def api_extend_video():
    """
    MCP Pipeline API: Extend existing video with additional content.

    Request (multipart/form-data or JSON):
        - video_id: str (required) - Existing video/session ID
        - extra_duration: int (optional) - Duration for extended segment (4-20, default: 8)
        - image: file (required for now) - New image for extension
        - prompt: str (optional) - Extension prompt

    Returns (202 Accepted):
        {
            "task_id": str,
            "video_id": str,
            "stage": "extend",
            "status": "running",
            "progress": int | null,
            "output_url": null,
            "frames": null,
            "error": null
        }
    """
    try:
        # Parse request data
        if request.is_json:
            data = request.get_json()
            video_id = data.get('video_id')
            extra_duration = data.get('extra_duration', 8)
            prompt = data.get('prompt', 'Continue the smooth camera movement')
            image_file = None
        else:
            video_id = request.form.get('video_id')
            extra_duration = request.form.get('extra_duration', 8)
            prompt = request.form.get('prompt', 'Continue the smooth camera movement')
            image_file = request.files.get('image')

        # Validate video_id
        if not video_id:
            return jsonify(build_task_response(
                task_id="",
                video_id="unknown",
                stage="extend",
                status="error",
                error="video_id is required"
            )), 400

        # Parse duration
        try:
            duration_seconds = int(extra_duration)
            if duration_seconds < 4 or duration_seconds > 20:
                duration_seconds = 8
        except (ValueError, TypeError):
            duration_seconds = 8

        # Get scene manager and last scene
        scene_manager = SceneManager(video_id)
        last_scene = scene_manager.get_last_scene()

        if not last_scene:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="extend",
                status="error",
                error=f"No existing scenes found for video_id: {video_id}. Generate a video first."
            )), 404

        # Handle image upload if provided
        image_path, error_resp = _ingest_api_image(video_id, image_file, "extend")
        if error_resp:
            return error_resp

        # Check if we have an image (required for now)
        if not image_path:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="extend",
                status="error",
                error="Image file is required for video extension. Please upload an image."
            )), 400

        # Generate new scene_id
        scene_id = scene_manager.generate_next_scene_id()

        # Launch Celery task
        from tasks import extend_scene_task

        task = extend_scene_task.apply_async(
            args=[video_id, scene_id, last_scene.scene_id, image_path, prompt],
            kwargs={
                "duration": f"{duration_seconds}s",
                "aspect_ratio": "16:9",
                "resolution": "720p"
            }
        )

        logger.info(f"[MCP API] Video extension started: task_id={task.id}, video_id={video_id}, scene_id={scene_id}")
        store_task_video_mapping(task.id, video_id)

        # Build plan sheet data for frontend visualization
        plan_sheet = {
            "mode": "Extend",
            "duration": duration_seconds,
            "prompt": prompt,
            "pic": "yes",
            "task_id": task.id
        }

        # Return unified response with plan sheet
        response = build_task_response(
            task_id=task.id,
            video_id=video_id,
            stage="extend",
            status="running",
        )
        response["plan_sheet"] = plan_sheet
        return jsonify(response), 202

    except Exception as e:
        logger.error(f"[MCP API] Extend error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id if 'video_id' in locals() else "unknown",
            stage="extend",
            status="error",
            error=str(e)
        )), 500


@web_ui_blueprint.route('/api/extract', methods=['POST'])
def api_extract_frames():
    """
    MCP Pipeline API: Extract frames from a video.

    Request (JSON):
        - video_id: str (required) - Video/session ID
        - fps: int (optional) - Frames per second to extract (1-30, default: 2)

    Returns (200 OK):
        {
            "task_id": str,
            "video_id": str,
            "stage": "extract",
            "status": "completed",
            "progress": int | null,
            "output_url": null,
            "frames": [
                {
                    "index": int,
                    "timestamp": float,
                    "url": str
                },
                ...
            ],
            "error": null
        }
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        video_id = data.get('video_id')
        fps = data.get('fps', 2)

        # Validate video_id
        if not video_id:
            return jsonify(build_task_response(
                task_id="",
                video_id="unknown",
                stage="extract",
                status="error",
                error="video_id is required"
            )), 400

        # Parse fps
        try:
            fps_value = int(fps)
            if fps_value < 1 or fps_value > 30:
                fps_value = 2
        except (ValueError, TypeError):
            fps_value = 2

        # Get scene manager and last scene
        scene_manager = SceneManager(video_id)
        last_scene = scene_manager.get_last_scene()

        if not last_scene:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="extract",
                status="error",
                error=f"No video found for video_id: {video_id}. Generate a video first."
            )), 404

        video_path = last_scene.video_path
        if not os.path.exists(video_path):
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="extract",
                status="error",
                error=f"Video file not found: {video_path}"
            )), 404

        # Extract frames using FrameEditor
        frames_dir = os.path.join('frames', video_id, 'extracted')
        os.makedirs(frames_dir, exist_ok=True)

        frame_editor = FrameEditor(video_path, frames_dir)

        # Calculate number of frames based on fps
        video_duration = get_video_duration(video_path)
        frame_count = min(int(video_duration * fps_value), 100)  # Cap at 100 frames

        extracted_frames = frame_editor.extract_frames(frame_count=frame_count)

        # Build frames response (without base64 data, just URLs)
        frames_response = []
        for frame in extracted_frames:
            frame_url = f"/frames/{video_id}/extracted/{os.path.basename(frame['path'])}"
            frames_response.append({
                "index": frame['frame_id'],
                "timestamp": frame['seconds'],
                "url": frame_url
            })

        # Generate task_id for tracking
        task_id = str(uuid.uuid4())

        logger.info(f"[MCP API] Extracted {len(frames_response)} frames from video_id={video_id}")

        # Return unified response
        return jsonify(build_task_response(
            task_id=task_id,
            video_id=video_id,
            stage="extract",
            status="completed",
            frames=frames_response,
        )), 200

    except Exception as e:
        logger.error(f"[MCP API] Extract error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id if 'video_id' in locals() else "unknown",
            stage="extract",
            status="error",
            error=str(e)
        )), 500


@web_ui_blueprint.route('/api/edit', methods=['POST'])
def api_edit_frame():
    """
    MCP Pipeline API: Edit a specific frame using AI.

    Request (JSON):
        - video_id: str (required) - Video/session ID
        - frame_index: int (required) - Frame index to edit
        - instruction: str (required) - Editing instruction

    Returns (200 OK):
        {
            "task_id": str,
            "video_id": str,
            "stage": "edit",
            "status": "completed",
            "progress": int | null,
            "output_url": null,
            "frames": [
                {
                    "index": int,
                    "original_url": str,
                    "edited_url": str,
                    "instruction": str
                }
            ],
            "error": null
        }
    """
    try:
        # Parse request data
        data = request.get_json() or {}
        video_id = data.get('video_id')
        raw_frame_index = data.get('frame_index')
        instruction = data.get('instruction')

        # Validate frame_index immediately
        try:
            frame_index = int(raw_frame_index)
            if frame_index < 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id or "unknown",
                stage="edit",
                status="error",
                error="frame_index must be a non-negative integer",
            )), 400

        # Validate inputs
        if not video_id:
            return jsonify(build_task_response(
                task_id="",
                video_id="unknown",
                stage="edit",
                status="error",
                error="video_id is required"
            )), 400

        if frame_index is None:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error="frame_index is required"
            )), 400

        if not instruction:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error="instruction is required"
            )), 400

        # Get scene manager and last scene
        scene_manager = SceneManager(video_id)
        last_scene = scene_manager.get_last_scene()

        if not last_scene:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error=f"No video found for video_id: {video_id}. Generate a video first."
            )), 404

        video_path = last_scene.video_path
        if not os.path.exists(video_path):
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error=f"Video file not found: {video_path}"
            )), 404

        # Extract frames using FrameEditor
        frames_dir = os.path.join('frames', video_id, 'for_edit')
        os.makedirs(frames_dir, exist_ok=True)

        frame_editor = FrameEditor(video_path, frames_dir)

        # Extract enough frames to get the desired index
        frame_count = frame_index + 10  # Extract a few extra frames
        extracted_frames = frame_editor.extract_frames(frame_count=frame_count)

        # Find the frame at the specified index
        if frame_index >= len(extracted_frames):
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error=f"frame_index {frame_index} out of range. Video has {len(extracted_frames)} frames."
            )), 400

        target_frame = extracted_frames[frame_index]
        frame_path = target_frame['path']

        # Use AIFrameEditor to generate edited version
        ai_editor = AIFrameEditor()

        edited_frames_dir = os.path.join('frames', video_id, 'edited')
        os.makedirs(edited_frames_dir, exist_ok=True)

        # Generate variations (we'll use the first one as the edited result)
        variations = ai_editor.generate_frame_variations(
            base_image_path=frame_path,
            prompt=instruction,
            variation_count=1
        )

        if not variations:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="edit",
                status="error",
                error="Failed to generate edited frame"
            )), 500

        # Save the edited frame
        edited_frame_path = os.path.join(edited_frames_dir, f'frame_{frame_index}_edited.png')

        # Extract base64 data and save
        import base64
        variation = variations[0]
        if 'image_url' in variation and variation['image_url'].startswith('data:image'):
            base64_str = variation['image_url'].split(',')[1]
            image_data = base64.b64decode(base64_str)
            with open(edited_frame_path, 'wb') as f:
                f.write(image_data)

        # Build frames response
        original_url = f"/frames/{video_id}/for_edit/{os.path.basename(frame_path)}"
        edited_url = f"/frames/{video_id}/edited/{os.path.basename(edited_frame_path)}"

        frames_response = [{
            "index": frame_index,
            "original_url": original_url,
            "edited_url": edited_url,
            "instruction": instruction
        }]

        # Generate task_id for tracking
        task_id = str(uuid.uuid4())

        logger.info(f"[MCP API] Edited frame {frame_index} for video_id={video_id}")

        # Return unified response
        return jsonify(build_task_response(
            task_id=task_id,
            video_id=video_id,
            stage="edit",
            status="completed",
            frames=frames_response,
        )), 200

    except Exception as e:
        logger.error(f"[MCP API] Edit error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id if 'video_id' in locals() else "unknown",
            stage="edit",
            status="error",
            error=str(e)
        )), 500


@web_ui_blueprint.route('/api/stitch', methods=['POST'])
def api_stitch_videos():
    """
    MCP Pipeline API: Stitch all scenes for a video into a single output.

    Request (JSON or form-data):
        - video_ids: list[str] (required) - Video/session IDs. Currently a single
          video_id is supported; multiple IDs are not yet merged together.
        - transition_type: str (optional) - "cut" or "fade" (default: "fade")

    Returns (202 Accepted):
        {
            "task_id": str,
            "video_id": str,
            "stage": "stitch",
            "status": "running",
            "progress": int | null,
            "output_url": null,
            "frames": null,
            "error": null
        }
    """
    try:
        # Parse request data
        if request.is_json:
            data = request.get_json() or {}
            video_ids = data.get('video_ids') or []
            single_video_id = data.get('video_id')
            transition_type = data.get('transition_type', 'fade')
        else:
            data = request.form
            video_ids = data.getlist('video_ids')
            single_video_id = data.get('video_id')
            transition_type = data.get('transition_type', 'fade')

        if single_video_id:
            video_ids.append(single_video_id)

        # Normalize and deduplicate video_ids while preserving order
        normalized_ids = []
        for vid in video_ids:
            if vid and vid not in normalized_ids:
                normalized_ids.append(vid)
        video_ids = normalized_ids

        if not video_ids:
            return jsonify(build_task_response(
                task_id="",
                video_id="unknown",
                stage="stitch",
                status="error",
                error="video_ids is required"
            )), 400

        # Current implementation stitches scenes within a single video_id.
        if len(video_ids) > 1:
            return jsonify(build_task_response(
                task_id="",
                video_id=",".join(video_ids),
                stage="stitch",
                status="error",
                error="Stitching across multiple video_ids is not supported yet. Use a single video_id."
            )), 400

        video_id = video_ids[0]
        session['api_session_id'] = video_id

        if transition_type not in {"cut", "fade"}:
            transition_type = "fade"

        # Ensure there are enough scenes to stitch
        scene_manager = SceneManager(video_id)
        scenes = scene_manager.get_all_scenes()

        if len(scenes) < 2:
            return jsonify(build_task_response(
                task_id="",
                video_id=video_id,
                stage="stitch",
                status="error",
                error="At least two scenes are required to stitch a final video. Generate or extend first."
            )), 400

        # Launch Celery task
        from tasks import merge_scenes_task

        task = merge_scenes_task.apply_async(
            args=[video_id],
            kwargs={"transition_type": transition_type}
        )

        logger.info(f"[MCP API] Stitching scenes: task_id={task.id}, video_id={video_id}, transition={transition_type}")
        store_task_video_mapping(task.id, video_id)

        return jsonify(build_task_response(
            task_id=task.id,
            video_id=video_id,
            stage="stitch",
            status="running",
        )), 202

    except Exception as e:
        logger.error(f"[MCP API] Stitch error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id if 'video_id' in locals() else "unknown",
            stage="stitch",
            status="error",
            error=str(e)
        )), 500


# -----------------------------------------------------------------------------
# Chat Command Handlers - コマンドハンドラー（内部関数）
# -----------------------------------------------------------------------------

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
    requested_image = params.get('image_path')
    latest_uploaded = (session.get('latest_uploaded_image') or {}).get(session_id)

    if not requested_image and not latest_uploaded:
        return {
            "status": "error",
            "message": "画像パスを指定してください（例: 「image1.jpgから動画を作って」）",
            "intent": "create"
        }

    # 画像ファイルの存在確認（ローカルまたはアップロード済み）
    candidate_paths = []

    if latest_uploaded:
        candidate_paths.append(latest_uploaded)

    if requested_image:
        if os.path.isabs(requested_image):
            candidate_paths.append(requested_image)
        else:
            candidate_paths.extend([
                os.path.join(LOCAL_UPLOAD_ROOT, requested_image),
                os.path.join(LOCAL_UPLOAD_ROOT, session_id, requested_image),
                _local_storage_full_path(build_storage_path(session_id, "input", requested_image)),
            ])

    resolved_image_path = next((p for p in candidate_paths if p and os.path.exists(p)), None)

    if not resolved_image_path:
        return {
            "status": "error",
            "message": f"画像が見つかりません: {requested_image or '未指定'}。先に画像をアップロードしてください。",
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
            image_path=resolved_image_path,
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
    requested_image = params.get('image_path')
    latest_uploaded = (session.get('latest_uploaded_image') or {}).get(session_id)

    if not requested_image and not latest_uploaded:
        return {
            "status": "error",
            "message": "新しいシーンの画像パスを指定してください（例: 「image2.jpgで続きを作って」）",
            "intent": "extend"
        }

    # 画像ファイルの存在確認
    candidate_paths = []

    if latest_uploaded:
        candidate_paths.append(latest_uploaded)

    if requested_image:
        if os.path.isabs(requested_image):
            candidate_paths.append(requested_image)
        else:
            candidate_paths.extend([
                os.path.join(LOCAL_UPLOAD_ROOT, requested_image),
                os.path.join(LOCAL_UPLOAD_ROOT, session_id, requested_image),
                _local_storage_full_path(build_storage_path(session_id, "input", requested_image)),
            ])

    resolved_image_path = next((p for p in candidate_paths if p and os.path.exists(p)), None)

    if not resolved_image_path:
        return {
            "status": "error",
            "message": f"画像が見つかりません: {requested_image or '未指定'}",
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
            new_image_path=resolved_image_path,
            prompt=params.get('prompt'),
            duration=params.get('duration', '8s'),
            aspect_ratio=params.get('aspect_ratio', '16:9'),
            resolution=params.get('resolution', '720p')
        )

        logger.info(f"Scene extension task started: task_id={task.id}, scene_id={scene_id}")

        # Build plan sheet data for frontend visualization
        duration_str = params.get('duration', '8s')
        duration_value = int(duration_str.rstrip('s')) if isinstance(duration_str, str) else int(duration_str)

        plan_sheet = {
            "mode": "Extend",
            "duration": duration_value,
            "prompt": params.get('prompt', 'Continue the smooth camera movement'),
            "pic": "yes",
            "task_id": task.id
        }

        return {
            "status": "processing",
            "task_id": task.id,
            "scene_id": scene_id,
            "previous_scene_id": last_scene.scene_id,
            "message": f"{last_scene.scene_id}の次のシーンを生成中...\n新しいシーンID: {scene_id}",
            "intent": "extend",
            "data": {
                "task_id": task.id,
                "video_id": session_id,
                "plan_sheet": plan_sheet
            }
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
        # フレーム抽出
        frame_editor = FrameEditor(scene.video_path)
        # タイムスタンプに最も近いフレームを抽出
        # TODO: extract_frame_at_time メソッドを実装
        # 暫定: 最初のフレームを使用
        frames = frame_editor.extract_frames(frame_count=1)
        if not frames:
            return {
                "status": "error",
                "message": "フレームの抽出に失敗しました",
                "intent": "frame_edit"
            }

        frame_path = frames[0]['path']

        # AI編集
        ai_editor = AIFrameEditor()
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
