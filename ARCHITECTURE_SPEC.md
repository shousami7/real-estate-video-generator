# システムアーキテクチャ仕様書
# Real Estate Video Generator - Architecture Specification

**Version:** 1.0
**Last Updated:** 2025-11-20
**Author:** Development Team

---

## 📋 目次 (Table of Contents)

1. [システム概要](#システム概要)
2. [アーキテクチャ設計思想](#アーキテクチャ設計思想)
3. [システム構成](#システム構成)
4. [システム1: チャットシステム](#システム1-チャットシステムweb-ui)
5. [システム2: API + MCPサーバー](#システム2-api--mcpサーバー)
6. [共通レイヤー](#共通レイヤーceleryタスク)
7. [データフロー](#データフロー)
8. [エンドポイント仕様](#エンドポイント仕様)
9. [タスク仕様](#タスク仕様)
10. [セキュリティ・認証](#セキュリティ認証)

---

## システム概要

### プロジェクト目的
AI（Google Veo API）を活用した不動産向け動画生成システム。
人間ユーザーとAIエージェント（Gemini、ChatGPT等）の両方に対応した二層アーキテクチャを採用。

### 主要機能
1. **動画生成** - 画像とプロンプトから動画を生成
2. **動画拡張** - 既存動画に追加シーンを生成
3. **フレーム抽出** - 動画からフレームを抽出
4. **フレーム編集** - AI指示による個別フレーム編集
5. **動画結合** - 複数動画の結合・トランジション適用

### 技術スタック
- **Backend:** Flask (Python)
- **Task Queue:** Celery + Redis
- **AI API:** Google Veo (Vertex AI)
- **Storage:** Supabase Storage (or Local)
- **MCP Protocol:** Model Context Protocol for AI agents
- **Frontend:** HTML/CSS/JavaScript (Tailwind CSS)

---

## アーキテクチャ設計思想

### 設計原則

#### 1. **二層プレゼンテーション・単一ビジネスロジック**
```
┌─────────────────────────────────────────────────┐
│          プレゼンテーション層                     │
│  ┌──────────────────┬──────────────────────┐    │
│  │  チャットシステム  │   APIシステム         │    │
│  │  (人間向けUI)     │   (AIエージェント向け)│    │
│  └────────┬─────────┴──────────┬───────────┘    │
│           │                    │                │
└───────────┼────────────────────┼────────────────┘
            │                    │
            └──────────┬─────────┘
                       ▼
         ┌──────────────────────────┐
         │   ビジネスロジック層       │
         │   (共通Celeryタスク)      │
         │                          │
         │ • generate_video_task    │
         │ • extend_video_task      │
         │ • extract_frames_task    │
         │ • edit_frame_task        │
         │ • stitch_videos_task     │
         └──────────────────────────┘
                       ▼
         ┌──────────────────────────┐
         │   外部サービス層           │
         │ • Veo API (Vertex AI)    │
         │ • Supabase Storage       │
         │ • Imagen API             │
         └──────────────────────────┘
```

#### 2. **関心事の分離 (Separation of Concerns)**
- **チャットシステム**: 会話的UX、自然言語処理、セッション管理
- **APIシステム**: 構造化リクエスト、ステートレス、プログラマティック制御
- **ビジネスロジック**: 両システムで共有、重複なし

#### 3. **非同期処理**
- 動画生成は2-5分かかるため、すべてCeleryで非同期実行
- タスクIDによる進捗追跡
- ポーリングベースのステータス確認

---

## システム構成

### ディレクトリ構造
```
real-estate-video-generator/
├── web_ui.py                    # Flask Webアプリケーション（両システムのエンドポイント）
├── tasks.py                     # Celeryタスク定義（共通ビジネスロジック）
├── chat_command_handler.py      # チャットコマンド解析エンジン
├── scene_manager.py             # シーン管理
├── veo_generator.py             # Veo API クライアント
├── video_composer.py            # 動画編集・結合
├── supabase_storage.py          # ストレージ管理
├── celery_app.py                # Celery設定
│
├── mcp_server/                  # MCPサーバー（AIエージェント用）
│   ├── server.py                # MCP tool定義
│   ├── requirements.txt
│   └── README.md
│
├── templates/
│   └── video_editor_ui.html     # Web UIフロントエンド
│
├── uploads/                     # ローカルファイルストレージ
└── utils/                       # ユーティリティ
```

---

## システム1: チャットシステム(Web UI)

### 概要
**対象ユーザー:** 人間（ブラウザ経由）
**インターフェース:** 会話型チャット + プラスボタンUI
**特徴:** 自然言語処理、セッション管理、リアルタイムフィードバック

### UIコンポーネント

#### プラスボタン (Plus Button)
```html
<!-- templates/video_editor_ui.html:622-628 -->
<div id="video-mode-popup" class="video-mode-popup">
    <div class="video-mode-option" data-mode="generate">Generate</div>
    <div class="video-mode-option" data-mode="extend">Extend</div>
    <div class="video-mode-option" data-mode="stitch">Stitch</div>
    <div class="video-mode-option" data-mode="adjust">Adjust</div>
</div>
```

**4つのモード:**
1. **Generate** - 新規動画生成
2. **Extend** - シーン追加
3. **Stitch** - 動画結合
4. **Adjust** - フレーム編集

### エンドポイント

#### 1. `/editor/chat` (POST)
**ファイル:** `web_ui.py:877`
**機能:** 統合チャットコマンド処理

**リクエスト:**
```json
{
  "message": "この画像から8秒の動画を作って",
  "session_id": "optional-uuid"
}
```

**レスポンス:**
```json
{
  "status": "processing",
  "message": "動画を生成中です（約2-5分）...",
  "intent": "create",
  "task_id": "celery-task-id",
  "scene_id": "scene-001",
  "chat_history": [...]
}
```

**処理フロー:**
```python
# web_ui.py:877-989
editor_chat()
  → ChatCommandHandler.parse_command()  # 自然言語解析
  → validate_command()                  # バリデーション
  → _handle_create_video()              # インテント別ハンドラー
  → generate_video_from_chat_task.delay()  # Celeryタスク起動
```

#### 2. `/editor/chat/history` (GET)
**ファイル:** `web_ui.py:1011`
**機能:** チャット履歴取得

#### 3. `/editor/chat/clear` (POST)
**ファイル:** `web_ui.py:1032`
**機能:** チャット履歴クリア

### コマンド解析エンジン

#### ChatCommandHandler
**ファイル:** `chat_command_handler.py:24`

**インテント分類:**
```python
class CommandIntent(Enum):
    CREATE = "create"           # 新規動画生成
    EXTEND = "extend"           # シーン追加
    TRANSITION = "transition"   # 動画結合
    FRAME_EDIT = "frame_edit"   # フレーム編集
    UNKNOWN = "unknown"
```

**パターンマッチング:**
```python
# chat_command_handler.py:41-62
INTENT_PATTERNS = {
    CommandIntent.CREATE: [
        r'作.*動画', r'生成', r'から.*秒',
        r'generate', r'create video', ...
    ],
    CommandIntent.EXTEND: [
        r'次.*シーン', r'追加', r'続き',
        r'add scene', r'extend', ...
    ],
    # ...
}
```

### インテント別ハンドラー

#### `_handle_create_video()`
**ファイル:** `web_ui.py:1944`
**機能:** 動画生成処理

```python
def _handle_create_video(params, scene_manager, session_id):
    # 画像パス検証
    # シーンID生成
    # Celeryタスク起動
    task = generate_video_from_chat_task.delay(
        session_id=session_id,
        scene_id=scene_id,
        image_path=full_image_path,
        prompt=params.get('prompt'),
        duration=params.get('duration', '8s')
    )
```

#### `_handle_extend_scene()`
**ファイル:** `web_ui.py:2024`
**機能:** シーン拡張処理

#### `_handle_merge_scenes()`
**ファイル:** （実装要確認）
**機能:** シーン結合処理

#### `_handle_frame_edit()`
**ファイル:** （実装要確認）
**機能:** フレーム編集処理

---

## システム2: API + MCPサーバー

### 概要
**対象ユーザー:** AIエージェント（Gemini、ChatGPT、Claude Desktop等）
**インターフェース:** RESTful API + MCP Protocol
**特徴:** ステートレス、構造化レスポンス、パイプライン制御

### MCPサーバー

#### 起動方法
```bash
cd mcp_server
python server.py
```

**設定:**
```bash
export BACKEND_URL=http://localhost:5000
```

#### MCPツール定義
**ファイル:** `mcp_server/server.py:72-198`

**6つのツール:**
1. `generate_video` - 動画生成
2. `extend_video` - 動画拡張
3. `extract_frames` - フレーム抽出
4. `edit_frame` - フレーム編集
5. `stitch_videos` - 動画結合
6. `get_status` - タスク状態確認

#### ツール実行フロー
```python
# mcp_server/server.py:201-274
@app.call_tool()
async def call_tool(name: str, arguments: Any):
    if name == "generate_video":
        result = make_request(
            "POST",
            "/api/generate",
            json={
                "prompt": arguments["prompt"],
                "video_id": arguments.get("video_id")
            }
        )
    # ...
```

**HTTPプロキシ方式:**
```
MCP Client (Gemini)
  → MCP Server (stdio)
  → HTTP Request to Flask API
  → Celery Task
  → Veo API
```

### APIエンドポイント

#### 統一レスポンス形式
**ファイル:** `utils/response_utils.py`

```python
def build_task_response(
    task_id: str,
    video_id: str,
    stage: str,
    status: str,
    progress: int = None,
    output_url: str = None,
    frames: list = None,
    error: str = None
) -> dict:
    return {
        "task_id": task_id,
        "video_id": video_id,
        "stage": stage,          # generate, extend, extract, edit, stitch
        "status": status,        # running, completed, error
        "progress": progress,    # 0-100
        "output_url": output_url,
        "frames": frames,
        "error": error
    }
```

---

## エンドポイント仕様

### 1. `/api/generate` (POST)
**ファイル:** `web_ui.py:1268`
**機能:** 動画生成

**リクエスト (multipart/form-data):**
```
POST /api/generate
Content-Type: multipart/form-data

prompt: "A luxury real estate tour"
image: [binary file]
video_id: "optional-uuid"
duration: 8  (4-20秒)
```

**リクエスト (JSON):**
```json
{
  "prompt": "A luxury real estate tour",
  "video_id": "optional-uuid",
  "duration": 8
}
```

**レスポンス (202 Accepted):**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "session-uuid",
  "stage": "generate",
  "status": "running",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": null
}
```

**実装:**
```python
# web_ui.py:1268-1378
@web_ui_blueprint.route('/api/generate', methods=['POST'])
def api_generate_video():
    # リクエスト解析（JSON or Form Data）
    # 画像アップロード処理
    # シーンID生成
    # Celeryタスク起動
    task = generate_video_from_chat_task.apply_async(
        args=[video_id, scene_id, image_path, prompt],
        kwargs={"duration": f"{duration_seconds}s", ...}
    )
```

---

### 2. `/api/extend` (POST)
**ファイル:** `web_ui.py:1381`
**機能:** 動画拡張

**リクエスト:**
```json
{
  "video_id": "existing-video-id",
  "extra_duration": 8,
  "prompt": "Continue the tour to the backyard"
}
```

**レスポンス (202 Accepted):**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "existing-video-id",
  "stage": "extend",
  "status": "running",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": null
}
```

---

### 3. `/api/extract` (POST)
**ファイル:** `web_ui.py:1501`
**機能:** フレーム抽出

**リクエスト:**
```json
{
  "video_id": "existing-video-id",
  "fps": 1
}
```

**レスポンス (202 Accepted):**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "existing-video-id",
  "stage": "extract",
  "status": "running",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": null
}
```

**完了後のステータス:**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "existing-video-id",
  "stage": "extract",
  "status": "completed",
  "progress": 100,
  "output_url": null,
  "frames": [
    {"index": 0, "timestamp": 0.0, "url": "https://..."},
    {"index": 1, "timestamp": 1.0, "url": "https://..."}
  ],
  "error": null
}
```

---

### 4. `/api/edit` (POST)
**ファイル:** `web_ui.py:1623`
**機能:** フレーム編集（AI指示）

**リクエスト:**
```json
{
  "video_id": "existing-video-id",
  "frame_index": 5,
  "instruction": "Make the sky more blue and vibrant"
}
```

**レスポンス (202 Accepted):**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "existing-video-id",
  "stage": "edit",
  "status": "running",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": null
}
```

---

### 5. `/api/stitch` (POST)
**ファイル:** `web_ui.py:1828`
**機能:** 動画結合

**リクエスト:**
```json
{
  "video_ids": ["video-1", "video-2", "video-3"],
  "transition_type": "fade"
}
```

**レスポンス (202 Accepted):**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "stitched-video-id",
  "stage": "stitch",
  "status": "running",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": null
}
```

---

### 6. `/api/task/<task_id>/status` (GET)
**機能:** タスク状態確認

**レスポンス:**
```json
{
  "task_id": "celery-task-uuid",
  "video_id": "video-uuid",
  "stage": "generate",
  "status": "completed",
  "progress": 100,
  "output_url": "https://supabase.../video.mp4",
  "frames": null,
  "error": null
}
```

**ステータス値:**
- `running` - 処理中
- `completed` - 完了
- `error` - エラー

---

## 共通レイヤー(Celeryタスク)

### タスク定義
**ファイル:** `tasks.py`

### 主要タスク一覧

#### 1. `generate_video_from_chat_task`
**ファイル:** `tasks.py:154`
**機能:** 動画生成（チャット・API共通）

**シグネチャ:**
```python
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
) -> Dict[str, Any]
```

**処理フロー:**
```python
1. タスクステート更新 (GENERATING, progress=10)
2. VeoVideoGenerator 初期化
3. veo.generate_video() 実行 (progress=20)
4. veo.wait_for_completion() ポーリング (progress=50)
5. 動画ダウンロード (progress=70)
6. Supabase/Local ストレージ保存 (progress=90)
7. SceneManager に登録 (progress=100)
8. 結果返却
```

**返り値:**
```python
{
    "status": "completed",
    "scene_id": "scene-001",
    "video_path": "/local/path/video.mp4",
    "video_url": "https://supabase.../video.mp4",
    "duration": 8.0
}
```

---

#### 2. `extend_video_task`
**ファイル:** （実装要確認）
**機能:** 動画拡張

**処理:**
1. 既存動画の最終フレーム取得
2. Veo extend API呼び出し
3. 新規シーン生成
4. 結合（オプション）

---

#### 3. `extract_frames_task`
**機能:** フレーム抽出

**処理:**
1. ffmpeg で動画からフレーム抽出
2. 指定FPSに従ってサンプリング
3. フレーム画像をストレージ保存
4. メタデータ返却

---

#### 4. `edit_frame_task`
**機能:** AIフレーム編集

**処理:**
1. フレーム画像取得
2. Imagen API で編集指示実行
3. 編集済み画像を保存
4. メタデータ更新

---

#### 5. `stitch_videos_task`
**機能:** 動画結合

**処理:**
1. 複数動画をダウンロード
2. ffmpeg でトランジション適用
3. 結合動画生成
4. ストレージ保存

---

## データフロー

### シナリオ1: チャットUIからの動画生成

```
[User] "この画像から8秒の動画を作って"
  ↓
[Browser] POST /editor/chat
  {
    "message": "この画像から8秒の動画を作って",
    "session_id": "user-session-123"
  }
  ↓
[web_ui.py:877] editor_chat()
  ↓
[chat_command_handler.py:68] parse_command()
  → Intent: CREATE
  → Params: {duration: "8s", prompt: "..."}
  ↓
[web_ui.py:1944] _handle_create_video()
  → 画像パス検証
  → scene_id = "scene-001"
  ↓
[tasks.py:154] generate_video_from_chat_task.delay()
  ↓
[Celery Worker]
  → VeoVideoGenerator.generate_video()
  → wait_for_completion() (2-5分)
  → download_video()
  → upload_to_supabase()
  ↓
[Response] 202 Accepted
  {
    "status": "processing",
    "task_id": "abc-123",
    "scene_id": "scene-001",
    "message": "動画を生成中です..."
  }
  ↓
[Browser] ポーリング /api/task/abc-123/status
  ↓
[Completed]
  {
    "status": "completed",
    "output_url": "https://supabase.../video.mp4"
  }
```

---

### シナリオ2: Gemini (MCP) からのパイプライン実行

```
[Gemini] "Create a real estate video, extend it, extract frames, edit frame 5"
  ↓
[MCP Client] → [MCP Server] generate_video tool
  ↓
[mcp_server/server.py:201] call_tool("generate_video")
  ↓
HTTP POST /api/generate
  {
    "prompt": "Luxury home tour",
    "video_id": "gemini-session-456"
  }
  ↓
[web_ui.py:1268] api_generate_video()
  → generate_video_from_chat_task.apply_async()
  ↓
[Response] {"task_id": "task-1", "video_id": "gemini-session-456"}
  ↓
[Gemini] MCP get_status("task-1") → ポーリング
  ↓
[Completed] {"status": "completed", "output_url": "..."}
  ↓
[Gemini] MCP extend_video tool
  ↓
HTTP POST /api/extend
  {"video_id": "gemini-session-456", "extra_duration": 8}
  ↓
[Response] {"task_id": "task-2"}
  ↓
[Gemini] get_status("task-2") → 完了待ち
  ↓
[Gemini] MCP extract_frames tool
  ↓
HTTP POST /api/extract
  {"video_id": "gemini-session-456", "fps": 1}
  ↓
[Response] {"task_id": "task-3"}
  ↓
[Completed] {"frames": [{index: 0, url: "..."}, ...]}
  ↓
[Gemini] MCP edit_frame tool
  ↓
HTTP POST /api/edit
  {
    "video_id": "gemini-session-456",
    "frame_index": 5,
    "instruction": "Brighten the image"
  }
  ↓
[Response] {"task_id": "task-4"}
  ↓
[Completed] 全パイプライン完了
```

---

## セキュリティ・認証

### 現在の実装
- **認証:** なし（開発環境）
- **セッション管理:** Flask session (cookie-based)
- **API Key:** 環境変数で管理

### 本番環境での推奨事項

#### 1. API認証
```python
# 推奨: Bearer Token認証
@web_ui_blueprint.before_request
def verify_api_key():
    if request.path.startswith('/api/'):
        token = request.headers.get('Authorization')
        if not verify_token(token):
            return jsonify({"error": "Unauthorized"}), 401
```

#### 2. レート制限
```python
from flask_limiter import Limiter

limiter = Limiter(app, key_func=get_remote_address)

@limiter.limit("10 per minute")
@web_ui_blueprint.route('/api/generate', methods=['POST'])
def api_generate_video():
    # ...
```

#### 3. ファイルアップロード検証
```python
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

def validate_image(file):
    # 拡張子チェック
    # ファイルサイズチェック
    # MIME typeチェック
    # 画像フォーマット検証
```

---

## 環境変数

### 必須設定
```bash
# Google Cloud / Veo API
GOOGLE_API_KEY=your-api-key
GCP_PROJECT_ID=your-project-id
GCP_LOCATION=us-central1

# Supabase Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_REQUIRED=0  # 1 = required, 0 = optional (fallback to local)

# Celery / Redis
REDIS_URL=redis://localhost:6379/0

# ローカルストレージ
LOCAL_UPLOAD_ROOT=./uploads
```

### オプション設定
```bash
# MCP Server
BACKEND_URL=http://localhost:5000

# Flask
FLASK_ENV=development
SECRET_KEY=your-secret-key
```

---

## デプロイメント

### 起動手順

#### 1. Redis起動
```bash
docker run -d -p 6379:6379 redis:latest
```

#### 2. Celeryワーカー起動
```bash
celery -A celery_app worker --loglevel=info
```

#### 3. Flask起動
```bash
python web_ui.py
```

#### 4. MCPサーバー起動（オプション）
```bash
cd mcp_server
python server.py
```

---

## パフォーマンス考慮事項

### 動画生成時間
- **平均:** 2-5分（Veo API依存）
- **ボトルネック:** Veo APIのジョブキュー

### スケーラビリティ
- **Celeryワーカー:** 水平スケール可能
- **Redis:** 単一インスタンスで数千タスク対応可能
- **Flask:** Gunicorn/uWSGIでマルチプロセス対応

### 推奨構成（本番）
```
[Load Balancer]
     ↓
[Flask x 4 workers]
     ↓
[Redis Cluster]
     ↓
[Celery Workers x 10]
     ↓
[Veo API]
```

---

## トラブルシューティング

### よくある問題

#### 1. タスクが完了しない
```bash
# Celeryログ確認
celery -A celery_app worker --loglevel=debug

# Redisキュー確認
redis-cli
> LLEN celery
```

#### 2. 動画URLにアクセスできない
- Supabase Storage権限確認
- 公開URLの有効期限確認
- LOCAL_UPLOAD_ROOTのパーミッション確認

#### 3. MCPサーバーが応答しない
```bash
# ログ確認
tail -f mcp_server/mcp_server.log

# バックエンド接続確認
curl http://localhost:5000/api/generate
```

---

## 今後の拡張予定

### Phase 2機能
- [ ] テキストのみから動画生成（Veo text-to-video）
- [ ] リアルタイムプレビュー
- [ ] 動画編集タイムライン
- [ ] ユーザー認証・マルチテナント
- [ ] Webhook通知
- [ ] 動画テンプレート機能

### Phase 3機能
- [ ] AI音声ナレーション追加
- [ ] 字幕自動生成
- [ ] マルチ言語対応
- [ ] ブランドカスタマイズ
- [ ] 一括処理API

---

## アーキテクチャ設計の理由

### なぜ二層に分けるのか？

#### 別々にする理由（現在の設計） ✅

**1. ユーザー体験の最適化**
- チャット: 会話的、寛容なUX
- API: 厳格、予測可能な契約

**2. 進化の独立性**
- チャットUIの機能追加がAPIに影響しない
- APIバージョニングがUIに影響しない

**3. クライアントの違い**
- 人間: エラー訂正、曖昧性許容
- AI: 構造化データ、型安全性

**4. 保守性**
- 各レイヤーの責任が明確
- テストが容易

#### 統合する場合の問題点 ❌

**1. 責任の混在**
```python
# アンチパターン例
def unified_endpoint():
    if is_ai_client():
        # 構造化処理
    else:
        # 自然言語処理
    # どちらの責任？
```

**2. 複雑性の増加**
- 条件分岐が増える
- エラーハンドリングが複雑化

**3. パフォーマンス**
- 不要な処理が実行される

---

## まとめ

### アーキテクチャの強み
✅ **明確な関心事の分離**
✅ **コード重複なし**（共通Celeryタスク）
✅ **スケーラブル**（非同期処理）
✅ **拡張可能**（新しいプレゼンテーション層追加可能）
✅ **テスタブル**（各レイヤー独立）

### 設計決定の記録
- **2025-11-20:** 二層プレゼンテーション・単一ビジネスロジック採用決定
- **理由:** 人間とAIエージェントの異なるニーズに対応しつつ、ロジック重複を排除

---

## 参考資料

- [Celery Documentation](https://docs.celeryproject.org/)
- [Model Context Protocol Spec](https://modelcontextprotocol.io/)
- [Google Veo API Documentation](https://cloud.google.com/vertex-ai/docs/generative-ai/video)
- [Flask Best Practices](https://flask.palletsprojects.com/)

---

**Document Version:** 1.0
**Last Review:** 2025-11-20
**Next Review:** 2025-12-20
