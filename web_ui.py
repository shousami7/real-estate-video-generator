
import os
import uuid
import logging
from flask import (
    Blueprint, render_template, request, jsonify, session, send_from_directory, send_file
)
from werkzeug.utils import secure_filename
from generate_property_video import PropertyVideoGenerator
from frame_editor import FrameEditor, AIFrameEditor
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

web_ui_blueprint = Blueprint('web_ui', __name__, template_folder='templates', static_folder='static')

@web_ui_blueprint.route('/')
def index():
    """Web UIのエントリーポイントです。"""
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

        # アップロードディレクトリ作成
        upload_path = os.path.join('uploads', session_id)
        os.makedirs(upload_path, exist_ok=True)
        print(f"[UPLOAD] Upload directory: {upload_path}")

        # ファイルチェック（詳細なエラーメッセージ付き）
        uploaded_files = []
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
            file_path = os.path.join(upload_path, filename)
            file.save(file_path)
            uploaded_files.append(file_path)
            print(f"[UPLOAD] Saved {file_key} to: {file_path}")

        # セッションに保存
        session['uploaded_files'] = uploaded_files
        print(f"[UPLOAD SUCCESS] Uploaded {len(uploaded_files)} files")

        return jsonify({
            "status": "success",
            "message": "Images uploaded successfully. Click 'AI Video Generation Start' button.",
            "files": uploaded_files
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
    Start the video generation process.
    NOTE: This is a synchronous implementation that will block the server.
    For production use, consider using Celery, RQ, or similar task queue.
    """
    if 'session_id' not in session or 'uploaded_files' not in session:
        return jsonify({
            "status": "error",
            "message": "No uploaded images found. Please upload images first."
        }), 400

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({
            "status": "error",
            "message": "GOOGLE_API_KEY is not set. Please check your .env file."
        }), 500

    session_id = session['session_id']
    image_paths = session['uploaded_files']

    # Mark generation as started
    session['generation_status'] = 'GENERATING_CLIPS'
    session['generation_progress'] = 20

    generator = PropertyVideoGenerator(
        api_key=api_key,
        output_dir='output',
        session_name=session_id
    )

    try:
        final_video_path = generator.generate_complete_property_video(
            image_paths=image_paths
        )
        session['final_video'] = final_video_path
        session['generation_status'] = 'COMPLETE'
        session['generation_progress'] = 100

        return jsonify({
            "status": "complete",
            "message": "Video generation completed successfully!",
            "final_video_url": "/download",
            "editor_url": "/video/editor"
        })
    except ValueError as e:
        # クォータ超過などのユーザー向けエラーメッセージ
        error_msg = str(e)
        session['generation_status'] = 'ERROR'
        session['generation_error'] = error_msg
        return jsonify({
            "status": "error",
            "message": error_msg
        }), 500
    except Exception as e:
        session['generation_status'] = 'ERROR'
        error_str = str(e)
        
        # 429エラーをチェック
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            error_msg = (
                "API quota limit reached.\n\n"
                "Google AI API usage limit exceeded.\n\n"
                "Solutions:\n"
                "1. Check your usage at Google AI Studio (https://ai.dev/usage)\n"
                "2. Review your plan and billing information\n"
                "3. Rate limit details: https://ai.google.dev/gemini-api/docs/rate-limits\n"
                "4. Please wait a while and try again"
            )
        else:
            error_msg = f"Error occurred during video generation: {error_str}"
        
        session['generation_error'] = error_msg
        return jsonify({
            "status": "error",
            "message": error_msg
        }), 500

@web_ui_blueprint.route('/status')
def get_status():
    """
    Check the progress of video generation.
    Returns detailed status information for the frontend.
    """
    status = session.get('generation_status', 'IDLE')
    progress = session.get('generation_progress', 0)

    if status == 'COMPLETE' and 'final_video' in session:
        return jsonify({
            "status": "COMPLETE",
            "message": "Video generation completed successfully!",
            "progress_percent": 100,
            "final_video_url": "/download",
            "editor_url": "/video/editor"
        })
    elif status == 'ERROR':
        error_msg = session.get('generation_error', 'Unknown error')
        return jsonify({
            "status": "ERROR",
            "message": f"Error: {error_msg}",
            "progress_percent": progress
        })
    elif status == 'GENERATING_CLIPS':
        return jsonify({
            "status": "GENERATING_CLIPS",
            "message": "Generating AI video clips... (Veo 3.1)",
            "progress_percent": progress
        })
    else:
        return jsonify({
            "status": "IDLE",
            "message": "Upload Progress",
            "progress_percent": 0
        })

@web_ui_blueprint.route('/download')
def download_video():
    """
    Download the generated video.
    """
    if 'final_video' not in session:
        return jsonify({"error": "No video found for this session"}), 404

    video_path = session['final_video']
    directory = os.path.dirname(video_path)
    filename = os.path.basename(video_path)
    return send_from_directory(directory, filename, as_attachment=True)


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

        session['editor_video'] = video_path

        logger.info(f"Video uploaded: {video_path}")

        return jsonify({
            "status": "success",
            "message": "Video uploaded successfully",
            "video_path": video_path
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
