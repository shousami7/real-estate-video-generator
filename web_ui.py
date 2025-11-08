
import os
import uuid
from flask import (
    Blueprint, render_template, request, jsonify, session, send_from_directory
)
from werkzeug.utils import secure_filename
from generate_property_video import PropertyVideoGenerator

web_ui_blueprint = Blueprint('web_ui', __name__, template_folder='templates', static_folder='static')

@web_ui_blueprint.route('/')
def index():
    """Web UIのエントリーポイントです。"""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    session_id = session['session_id']
    print(f"ユーザーID: {session_id} で接続")
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
            "message": "画像のアップロードが完了しました。「AI動画生成開始」ボタンを押してください。",
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
            "message": "アップロードされた画像が見つかりません。先に画像をアップロードしてください。"
        }), 400

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return jsonify({
            "status": "error",
            "message": "GOOGLE_API_KEYが設定されていません。.envファイルを確認してください。"
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
            "message": "動画生成が完了しました！",
            "final_video_url": "/download"
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
                "APIクォータ制限に達しました。\n\n"
                "Google AI APIの使用量制限を超えています。\n\n"
                "対処方法:\n"
                "1. Google AI Studio (https://ai.dev/usage) で使用量を確認してください\n"
                "2. プランと請求情報を確認してください\n"
                "3. レート制限の詳細: https://ai.google.dev/gemini-api/docs/rate-limits\n"
                "4. しばらく待ってから再度お試しください"
            )
        else:
            error_msg = f"動画生成中にエラーが発生しました: {error_str}"
        
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
            "message": "動画生成が完了しました！",
            "progress_percent": 100,
            "final_video_url": "/download"
        })
    elif status == 'ERROR':
        error_msg = session.get('generation_error', '不明なエラー')
        return jsonify({
            "status": "ERROR",
            "message": f"エラー: {error_msg}",
            "progress_percent": progress
        })
    elif status == 'GENERATING_CLIPS':
        return jsonify({
            "status": "GENERATING_CLIPS",
            "message": "AI動画クリップを生成中... (Veo 3.1)",
            "progress_percent": progress
        })
    else:
        return jsonify({
            "status": "IDLE",
            "message": "待機中",
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
