
from dotenv import load_dotenv
import os
import secrets
import logging

from utils.logging_config import configure_logging

# 絶対パスで .env を読み込む（Flask reloader による cwd 変更に対応）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# 短縮フォーマットのロギングを初期化（最初に設定しておく）
configure_logging()

from flask import Flask
from web_ui import web_ui_blueprint
from routes import api_blueprint

def create_app():
    """
    Create and configure the Flask application.
    """
    app = Flask(__name__)
    # Use a secure random key as a fallback if not explicitly set (best practice).
    # This key is only generated once per runtime and is cryptographically secure.
    secure_fallback = secrets.token_hex(32) if os.getenv('SECRET_KEY') is None else None
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secure_fallback)
    app.config['UPLOAD_FOLDER'] = 'uploads'
    # ファイルアップロードサイズ制限 (16MB)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # Register blueprints
    app.register_blueprint(web_ui_blueprint)
    app.register_blueprint(api_blueprint)

    return app

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Run the Real Estate Video Generator web app.')
    parser.add_argument('--port', type=int, default=5001, help='Port to run the application on (default: 5001)')
    args = parser.parse_args()

    app = create_app()
    app.run(debug=True, port=args.port)
