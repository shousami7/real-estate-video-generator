
from dotenv import load_dotenv
import os

# 絶対パスで .env を読み込む（Flask reloader による cwd 変更に対応）
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
from flask import Flask
from web_ui import web_ui_blueprint

def create_app():
    """
    Create and configure the Flask application.
    """
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    app.config['UPLOAD_FOLDER'] = 'uploads'
    # ファイルアップロードサイズ制限 (16MB)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

    # Register blueprints
    app.register_blueprint(web_ui_blueprint)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5001)
