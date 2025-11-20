# システムアーキテクチャ仕様書
# Real Estate Video Generator - Architecture Specification

**Version:** 2.0
**Last Updated:** 2025-11-20
**Author:** Development Team

## 📝 変更履歴 (Changelog)

### v2.0 (2025-11-20)
- ✅ **追加:** 重要な用語・概念セクション (video_id vs session_id の明確化)
- ✅ **追加:** パラメータ抽出ロジックの完全仕様 (8種類のパラメータ詳細)
- ✅ **追加:** バリデーションロジックの完全仕様 (4種類のインテント別)
- ✅ **追加:** レスポンス仕様セクション (API vs Chat の2形式を明確化)
- ✅ **修正:** タスク仕様を完全化 (3つのCeleryタスク + 2つの同期処理)
- ✅ **追加:** API バリデーション仕様 (全エンドポイントの必須/オプション項目)
- ✅ **明確化:** "Adjust" モードは FRAME_EDIT インテントにマッピング
- ✅ **明確化:** extract/edit は同期処理 (Celeryタスクではない)
- ✅ **追加:** エラーレスポンス仕様 (400/404 の統一形式)

### v1.0 (2025-11-20)
- 初版リリース

---

## 📋 目次 (Table of Contents)

1. [システム概要](#システム概要)
2. [重要な用語・概念](#重要な用語概念)
3. [アーキテクチャ設計思想](#アーキテクチャ設計思想)
4. [システム構成](#システム構成)
5. [システム1: チャットシステム](#システム1-チャットシステムweb-ui)
6. [システム2: API + MCPサーバー](#システム2-api--mcpサーバー)
7. [共通レイヤー](#共通レイヤーceleryタスク)
8. [レスポンス仕様](#レスポンス仕様)
9. [データフロー](#データフロー)
10. [エンドポイント仕様](#エンドポイント仕様)
11. [タスク仕様](#タスク仕様)
12. [セキュリティ・認証](#セキュリティ認証)

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

## 重要な用語・概念

### video_id vs session_id

**これらは同じ概念です。**

- **API層** (`/api/*`): `video_id` と呼称
- **Celeryタスク層**: `session_id` と呼称
- **Chat層**: `session_id` と呼称

**使い分けの理由:**
- API: 外部から見た「動画の識別子」として `video_id`
- 内部実装: ユーザーセッションの識別子として `session_id`

**実装での扱い:**
```python
# API呼び出し時
POST /api/generate
{
  "video_id": "abc-123"  # ← 外部向け名称
}

# Celeryタスク呼び出し時
generate_video_from_chat_task.apply_async(
    args=[
        "abc-123",  # session_id (第1引数) ← 同じ値
        scene_id,
        ...
    ]
)
```

**重要:**
- コード全体で同じUUID文字列が流れます
- データベース/ストレージでは `session_id` または `video_id` のどちらかでディレクトリ構造化
- 実装者は「同じID」として扱ってください

### scene_id

個別の動画シーンの識別子。
- フォーマット: `"scene-001"`, `"scene-002"`, ...
- 1つの `video_id` (セッション) に複数の `scene_id` が紐づく
- 最終的に全シーンを stitch して1本の動画にする

### インテント (Intent)

チャットシステムで使用される、ユーザーの意図分類:
- `CREATE` - 新規動画生成
- `EXTEND` - シーン追加
- `TRANSITION` - 動画結合
- `FRAME_EDIT` - フレーム編集 (UIの **"Adjust"** モードに対応)

### ステージ (Stage)

APIレスポンスで使用される処理段階:
- `generate` - 動画生成
- `extend` - 動画拡張
- `extract` - フレーム抽出
- `edit` - フレーム編集
- `stitch` - 動画結合

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
        r'作.*動画', r'生成', r'から.*秒', r'動画.*作',
        r'generate', r'create video', r'新.*動画',
        r'make.*video', r'ビデオ.*作'
    ],
    CommandIntent.EXTEND: [
        r'次.*シーン', r'追加', r'続き', r'シーン.*追加',
        r'add scene', r'extend', r'next scene',
        r'さらに', r'もう.*シーン', r'scene.*add'
    ],
    CommandIntent.TRANSITION: [
        r'繋げ', r'連結', r'まとめ', r'一つ.*動画',
        r'merge', r'combine', r'transition',
        r'つなげ', r'結合', r'合わせ'
    ],
    CommandIntent.FRAME_EDIT: [
        r'フレーム.*編集', r'秒目', r'明るく', r'色.*変',
        r'edit frame', r'brighten', r'adjust',
        r'暗く', r'鮮やか', r'編集'
    ]
}
```

#### パラメータ抽出ロジック
**ファイル:** `chat_command_handler.py:122-275`

ChatCommandHandler は以下のパラメータを自然言語から抽出します:

**1. duration (動画の長さ)**
```python
# 抽出パターン: "8秒", "10s", "5 seconds"
duration_match = re.search(r'(\d+)\s*[秒s]', text)
if duration_match:
    params['duration'] = f"{duration_match.group(1)}s"
else:
    params['duration'] = "8s"  # デフォルト
```
- **Required:** No (デフォルト: `"8s"`)
- **例:** "8秒の動画" → `"8s"`, "10s video" → `"10s"`

**2. image_path (画像ファイルパス)**
```python
# 抽出パターン: "image1.jpg", "IMG_001.png", "外観.jpg"
image_patterns = [
    r'([a-zA-Z0-9_\-\.ぁ-んァ-ヶー一-龠]+\.(jpg|jpeg|png|webp|gif))',
    r'file://([^\s]+)',
    r'uploaded:([^\s]+)'
]
```
- **Required:** Yes (CREATE/EXTEND時)
- **例:** "image1.jpgから動画を作って" → `"image1.jpg"`

**3. transition_type (トランジションタイプ)**
```python
# 抽出パターン: "フェード", "fade", "ワイプ"
transition_keywords = {
    'fade': ['フェード', 'fade', 'dissolve'],
    'wipeleft': ['左ワイプ', 'wipe left', 'wipeleft'],
    'wiperight': ['右ワイプ', 'wipe right', 'wiperight'],
    'cut': ['カット', 'cut', 'そのまま']
}
```
- **Required:** No (デフォルト: `"cut"`)
- **例:** "フェードで繋げて" → `"fade"`

**4. timestamp (タイムスタンプ)**
```python
# 抽出パターン: "3秒目", "5秒の部分", "at 2.5s"
timestamp_patterns = [
    r'(\d+(?:\.\d+)?)\s*秒目',
    r'at\s+(\d+(?:\.\d+)?)\s*s',
    r'(\d+(?:\.\d+)?)\s*秒.*部分'
]
```
- **Required:** FRAME_EDIT時に推奨
- **例:** "3秒目を明るくして" → `3.0`

**5. scene_id (シーンID)**
```python
# 抽出パターン: "Scene1", "scene2", "シーン3"
scene_patterns = [
    r'[Ss]cene\s*(\d+)',
    r'シーン\s*(\d+)'
]
```
- **Required:** FRAME_EDIT時にオプション
- **例:** "Scene1の3秒目を編集" → `"scene1"`

**6. prompt (AIへの指示)**
```python
# クリーニング: コマンド固有キーワードを除去
cleanup_patterns = [
    r'動画.*作って', r'シーン.*追加', r'繋げて',
    r'編集して', r'\d+秒', r'から', r'について'
]
prompt = re.sub(pattern, '', text)  # 各パターンを削除
prompt = ' '.join(prompt.split()).strip()  # 余分な空白削除
```
- **Required:** Yes
- **例:** "この画像から8秒の動画を作って" → `"この画像"`

**7. aspect_ratio (アスペクト比)**
```python
# 抽出パターン: "16:9", "9:16", "縦", "横"
aspect_ratio_keywords = {
    '16:9': ['16:9', '横', 'landscape', 'horizontal'],
    '9:16': ['9:16', '縦', 'portrait', 'vertical']
}
```
- **Required:** No (デフォルト: `"16:9"`)
- **例:** "縦向きの動画" → `"9:16"`

**8. resolution (解像度)**
```python
# 抽出パターン: "720p", "1080p", "HD", "Full HD"
resolution_keywords = {
    '720p': ['720p', 'hd'],
    '1080p': ['1080p', 'full hd', 'fullhd', 'fhd']
}
```
- **Required:** No (デフォルト: `"720p"`)
- **例:** "Full HDで生成" → `"1080p"`

#### バリデーションロジック
**ファイル:** `chat_command_handler.py:320-354`

```python
def validate_command(command: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    intent = command['intent']
    params = command['params']

    # UNKNOWNインテントは失敗
    if intent == CommandIntent.UNKNOWN:
        return False, self.get_intent_help_message(intent)

    # CREATE: 画像パスまたはプロンプトが必要
    if intent == CommandIntent.CREATE:
        if not params.get('image_path') and not params.get('prompt'):
            return False, "画像パスまたはプロンプトを指定してください"

    # EXTEND: 画像パスまたはプロンプトが必要
    if intent == CommandIntent.EXTEND:
        if not params.get('image_path') and not params.get('prompt'):
            return False, "新しいシーンの画像パスまたはプロンプトを指定してください"

    # FRAME_EDIT: scene_idまたはtimestampが必要
    if intent == CommandIntent.FRAME_EDIT:
        if not params.get('scene_id') and params.get('timestamp') is None:
            return False, "編集するフレームを指定してください（例: 「Scene1の3秒目」）"

    return True, None
```

**バリデーションルール:**
- `CREATE`: `image_path` OR `prompt` required
- `EXTEND`: `image_path` OR `prompt` required
- `TRANSITION`: バリデーションなし (全シーンを結合)
- `FRAME_EDIT`: `scene_id` OR `timestamp` required

**エラー時の動作:**
- バリデーション失敗時、エラーメッセージをチャット履歴に追加
- ユーザーに修正方法を提示 (例: "画像パスを指定してください")
- 処理は実行されず、ユーザーに再入力を促す

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

## レスポンス仕様

### 2つの異なるレスポンス形式

システムには **2種類のレスポンス形式** があります:

#### 1. API レスポンス (MCP/外部AI向け)
**使用箇所:** `/api/*` エンドポイント
**ファイル:** `utils/response_utils.py:8-43`

```python
def build_task_response(
    task_id: str,
    video_id: str,
    stage: str,
    status: str,
    progress: Optional[int] = None,
    output_url: Optional[str] = None,
    frames: Optional[list] = None,
    error: Optional[str] = None,
) -> dict:
    return {
        "task_id": task_id,        # Celeryタス克ID
        "video_id": video_id,      # セッション/動画ID
        "stage": stage,            # generate, extend, extract, edit, stitch
        "status": status,          # running, completed, error
        "progress": progress,      # 0-100 (nullable)
        "output_url": output_url,  # 完成動画URL (nullable)
        "frames": frames,          # フレームリスト (nullable)
        "error": error,            # エラーメッセージ (nullable)
    }
```

**必須フィールド:**
- `task_id`, `video_id`, `stage`, `status`

**オプションフィールド:**
- `progress` (処理中のみ)
- `output_url` (完了時のみ)
- `frames` (extract/edit完了時のみ)
- `error` (エラー時のみ)

**例 (生成中):**
```json
{
  "task_id": "abc-123",
  "video_id": "session-456",
  "stage": "generate",
  "status": "running",
  "progress": 50,
  "output_url": null,
  "frames": null,
  "error": null
}
```

**例 (完了):**
```json
{
  "task_id": "abc-123",
  "video_id": "session-456",
  "stage": "generate",
  "status": "completed",
  "progress": 100,
  "output_url": "https://supabase.../video.mp4",
  "frames": null,
  "error": null
}
```

**例 (エラー):**
```json
{
  "task_id": "",
  "video_id": "session-456",
  "stage": "generate",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "Image file is required"
}
```

---

#### 2. Chat レスポンス (人間向けUI)
**使用箇所:** `/editor/chat` エンドポイント
**ファイル:** `web_ui.py:1944-2012` (ハンドラー関数)

```python
# _handle_create_video() の返り値
{
    "status": "processing",        # processing, completed, error
    "task_id": "abc-123",          # Celeryタスクid
    "scene_id": "scene-001",       # 生成されたシーンID
    "message": "動画を生成中です（約2-5分）...\nシーンID: scene-001",
    "intent": "create",            # create, extend, transition, frame_edit
    "chat_history": [...]          # チャット履歴全体
}
```

**必須フィールド:**
- `status`, `message`, `intent`

**追加フィールド (成功時):**
- `task_id` - Celeryタスク追跡用
- `scene_id` - 生成されたシーン
- `chat_history` - 会話履歴

**例 (成功):**
```json
{
  "status": "processing",
  "task_id": "celery-task-uuid",
  "scene_id": "scene-001",
  "message": "動画を生成中です（約2-5分）...\nシーンID: scene-001",
  "intent": "create",
  "chat_history": [
    {"role": "user", "content": "この画像から8秒の動画を作って", "timestamp": "..."},
    {"role": "assistant", "content": "動画を生成中です...", "timestamp": "..."}
  ]
}
```

**例 (エラー):**
```json
{
  "status": "error",
  "message": "画像が見つかりません: image1.jpg。先にアップロードしてください。",
  "intent": "create",
  "chat_history": [...]
}
```

---

### レスポンス形式の使い分け

| 項目 | API Response | Chat Response |
|------|-------------|---------------|
| **対象** | AIエージェント | 人間ユーザー |
| **形式** | 構造化 (固定スキーマ) | 柔軟 (会話的) |
| **主キー** | `task_id`, `video_id`, `stage` | `message`, `intent` |
| **人間向けメッセージ** | `error` フィールドのみ | `message` フィールド常時 |
| **チャット履歴** | なし | `chat_history` 含む |
| **scene_id** | 含まない (内部実装) | 含む (UI表示用) |
| **ビルダー** | `build_task_response()` | 手動構築 |

**重要:**
- API エンドポイントは **必ず** `build_task_response()` を使用
- Chat ハンドラーは独自形式 (後方互換性のため)
- 将来的な統合は検討中

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

#### 2. `extend_scene_task`
**ファイル:** `tasks.py:394`
**機能:** シーン拡張（チャット・API共通）

**シグネチャ:**
```python
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
) -> Dict[str, Any]
```

**引数:**
- `session_id`: セッションID (= video_id)
- `scene_id`: 新しいシーンID (例: `"scene-002"`)
- `previous_scene_id`: 前のシーンID (例: `"scene-001"`)
- `new_image_path`: 新しい画像のパス
- `prompt`: 動画生成プロンプト
- `duration`: 動画の長さ (デフォルト: `"8s"`)
- `aspect_ratio`: アスペクト比 (デフォルト: `"16:9"`)
- `resolution`: 解像度 (デフォルト: `"720p"`)

**処理フロー:**
```python
1. タスクステート更新 (EXTENDING, progress=10)
2. SceneManager から前のシーンを取得
3. VeoVideoGenerator 初期化
4. 新しい画像から動画生成 (progress=20)
   # TODO: Veo API の previous_video 機能を実装予定
5. veo.wait_for_completion() ポーリング (progress=50)
6. 動画ダウンロード (progress=70)
7. Supabase/Local ストレージ保存 (progress=90)
8. SceneManager に新シーン登録 (progress=100)
9. 結果返却
```

**返り値:**
```python
{
    "status": "completed",
    "scene_id": "scene-002",
    "video_path": "/local/path/scene-002.mp4",
    "video_url": "https://supabase.../scene-002.mp4",
    "duration": 8.0
}
```

**注意:**
- 現在の実装では、前のシーンとは独立した新規動画を生成
- 将来的には Veo API の `previous_video` パラメータで真のシーン継続を実装予定

---

#### 3. `merge_scenes_task` (= stitch)
**ファイル:** `tasks.py:650`
**機能:** 複数シーンを1本の動画に結合

**シグネチャ:**
```python
@celery.task(bind=True, name="tasks.merge_scenes_task")
def merge_scenes_task(
    self,
    session_id: str,
    transition_type: str = "cut"
) -> Dict[str, Any]
```

**引数:**
- `session_id`: セッションID (= video_id)
- `transition_type`: トランジションタイプ
  - `"cut"` - カット (0秒)
  - `"fade"` - フェード (0.5秒)
  - `"wipeleft"`, `"wiperight"` - ワイプ (0.5秒)

**処理フロー:**
```python
1. タスクステート更新 (MERGING, progress=10)
2. SceneManager から全シーンを取得
3. 最低2シーン必要 (バリデーション)
4. VideoComposer で結合 (progress=30)
   - transition_duration = 0.5 if transition_type != "cut" else 0.0
   - composer.compose_with_transitions()
5. 結合動画をストレージ保存 (progress=80)
6. SceneManager に最終動画登録
7. 結果返却 (progress=100)
```

**返り値:**
```python
{
    "status": "completed",
    "final_video_path": "/local/path/stitched_20250120_120000.mp4",
    "final_video_url": "https://supabase.../stitched_20250120_120000.mp4",
    "scene_count": 3,
    "total_duration": 24.0
}
```

**バリデーション:**
- 最低2シーン必要
- シーンが不足している場合、400エラー返却

---

### 同期処理 (Celeryタスクなし)

以下の2つの機能は **同期処理** で実装されています (Celeryタスクではありません):

#### 4. フレーム抽出 (Synchronous)
**エンドポイント:** `/api/extract` (web_ui.py:1501)
**処理方法:** FrameEditor を使用して即座に実行

**処理フロー:**
```python
1. video_id から最後のシーンを取得
2. video_path の存在確認
3. FrameEditor(video_path, frames_dir) 初期化
4. frame_editor.extract_frames(frame_count) 実行
5. フレーム情報を即座に返却 (200 OK)
```

**返り値 (即座):**
```json
{
  "task_id": "generated-uuid",
  "video_id": "session-456",
  "stage": "extract",
  "status": "completed",
  "progress": 100,
  "output_url": null,
  "frames": [
    {"index": 0, "timestamp": 0.0, "url": "/frames/.../frame_0.jpg"},
    {"index": 1, "timestamp": 1.0, "url": "/frames/.../frame_1.jpg"}
  ],
  "error": null
}
```

**理由:**
- フレーム抽出は通常1-3秒で完了 (非同期化不要)
- ffmpeg のローカル処理のみ (外部API呼び出しなし)

---

#### 5. フレーム編集 (Synchronous)
**エンドポイント:** `/api/edit` (web_ui.py:1623)
**処理方法:** FrameEditor + Imagen API を使用して即座に実行

**処理フロー:**
```python
1. video_id から最後のシーンを取得
2. frames_dir から指定 frame_index の画像を取得
3. FrameEditor(video_path, frames_dir) 初期化
4. frame_editor.edit_frame_with_ai(frame_index, instruction) 実行
   - Imagen API 呼び出し (1-3秒)
5. 編集済みフレームを保存
6. 結果を即座に返却 (200 OK)
```

**返り値 (即座):**
```json
{
  "task_id": "generated-uuid",
  "video_id": "session-456",
  "stage": "edit",
  "status": "completed",
  "progress": 100,
  "output_url": null,
  "frames": [
    {
      "index": 5,
      "original_url": "/frames/.../frame_5.jpg",
      "edited_url": "/frames/.../frame_5_edited.jpg",
      "instruction": "Make the sky more blue"
    }
  ],
  "error": null
}
```

**理由:**
- Imagen API は通常1-3秒で応答 (非同期化不要)
- 単一フレームのみ処理 (バッチ処理ではない)

---

### タスク一覧まとめ

| タスク名 | ファイル | 実行方式 | 平均実行時間 | 使用API |
|---------|---------|---------|------------|--------|
| `generate_video_from_chat_task` | tasks.py:154 | **非同期** (Celery) | 2-5分 | Veo API |
| `extend_scene_task` | tasks.py:394 | **非同期** (Celery) | 2-5分 | Veo API |
| `merge_scenes_task` | tasks.py:650 | **非同期** (Celery) | 10-30秒 | ffmpeg (ローカル) |
| フレーム抽出 | web_ui.py:1501 | **同期** | 1-3秒 | ffmpeg (ローカル) |
| フレーム編集 | web_ui.py:1623 | **同期** | 1-3秒 | Imagen API |

**実装者への注意:**
- `/api/generate`, `/api/extend`, `/api/stitch` は 202 Accepted を返却 (非同期)
- `/api/extract`, `/api/edit` は 200 OK を返却 (同期)
- 同期エンドポイントでは `task_id` は追跡用UUID (実際のCeleryタスクではない)

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

## API バリデーション仕様

### 全エンドポイント共通エラーレスポンス

**400 Bad Request:**
```json
{
  "task_id": "",
  "video_id": "provided-or-unknown",
  "stage": "generate",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "具体的なエラーメッセージ"
}
```

**404 Not Found:**
```json
{
  "task_id": "",
  "video_id": "video-123",
  "stage": "extract",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "No video found for video_id: video-123. Generate a video first."
}
```

---

### エンドポイント別バリデーション

#### `/api/generate` (POST)

**必須フィールド:**
- `prompt` (string): 動画生成プロンプト
- `image` (file, multipart時): 画像ファイル

**オプションフィールド:**
- `video_id` (string): セッションID (省略時はUUID自動生成)
- `duration` (integer): 動画の長さ (4-20秒、デフォルト: 8)

**バリデーションルール:**
```python
# prompt必須
if not prompt:
    return 400, {"error": "Prompt is required"}

# duration範囲チェック
if duration < 4 or duration > 20:
    duration = 8  # デフォルトにフォールバック

# 画像必須 (現在の実装)
if not image_path:
    return 400, {"error": "Image file is required. Please upload an image."}
```

**エラー例:**
```json
{
  "task_id": "",
  "video_id": "unknown",
  "stage": "generate",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "Prompt is required"
}
```

---

#### `/api/extend` (POST)

**必須フィールド:**
- `video_id` (string): 拡張する動画のID
- `extra_duration` (integer): 追加する秒数 (4-20秒)

**オプションフィールド:**
- `prompt` (string): 追加シーンのプロンプト
- `image` (file): 新しい画像ファイル (multipart時)

**バリデーションルール:**
```python
# video_id必須
if not video_id:
    return 400, {"error": "video_id is required"}

# extra_duration必須
if not extra_duration:
    return 400, {"error": "extra_duration is required"}

# extra_duration範囲チェック
if extra_duration < 4 or extra_duration > 20:
    return 400, {"error": "extra_duration must be between 4 and 20"}

# 前のシーンが存在するか確認
last_scene = scene_manager.get_last_scene()
if not last_scene:
    return 404, {"error": "No video found for video_id: {video_id}. Generate a video first."}
```

**エラー例:**
```json
{
  "task_id": "",
  "video_id": "unknown",
  "stage": "extend",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "video_id is required"
}
```

---

#### `/api/extract` (POST)

**必須フィールド:**
- `video_id` (string): フレーム抽出する動画のID

**オプションフィールド:**
- `fps` (integer): フレーム抽出レート (1-30、デフォルト: 2)

**バリデーションルール:**
```python
# video_id必須
if not video_id:
    return 400, {"error": "video_id is required"}

# fps範囲チェック
if fps < 1 or fps > 30:
    fps = 2  # デフォルトにフォールバック

# 動画が存在するか確認
last_scene = scene_manager.get_last_scene()
if not last_scene:
    return 404, {"error": "No video found for video_id: {video_id}. Generate a video first."}

# ファイルが存在するか確認
if not os.path.exists(video_path):
    return 404, {"error": "Video file not found: {video_path}"}
```

**エラー例:**
```json
{
  "task_id": "",
  "video_id": "video-123",
  "stage": "extract",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "No video found for video_id: video-123. Generate a video first."
}
```

---

#### `/api/edit` (POST)

**必須フィールド:**
- `video_id` (string): 編集する動画のID
- `frame_index` (integer): 編集するフレームのインデックス (0以上)
- `instruction` (string): 編集指示

**オプションフィールド:**
なし

**バリデーションルール:**
```python
# frame_index型チェック
try:
    frame_index = int(raw_frame_index)
    if frame_index < 0:
        raise ValueError
except (TypeError, ValueError):
    return 400, {"error": "frame_index must be a non-negative integer"}

# video_id必須
if not video_id:
    return 400, {"error": "video_id is required"}

# frame_index必須 (明示的チェック)
if frame_index is None:
    return 400, {"error": "frame_index is required"}

# instruction必須
if not instruction:
    return 400, {"error": "instruction is required"}

# 動画が存在するか確認
last_scene = scene_manager.get_last_scene()
if not last_scene:
    return 404, {"error": "No video found for video_id: {video_id}. Generate a video first."}

# ファイルが存在するか確認
if not os.path.exists(video_path):
    return 404, {"error": "Video file not found: {video_path}"}
```

**エラー例:**
```json
{
  "task_id": "",
  "video_id": "video-123",
  "stage": "edit",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "frame_index must be a non-negative integer"
}
```

---

#### `/api/stitch` (POST)

**必須フィールド:**
- `video_ids` (array of strings): 結合する動画のIDリスト

OR

- `video_id` (string): 単一動画のID (内部シーン結合)

**オプションフィールド:**
- `transition_type` (string): トランジションタイプ
  - 許可値: `"cut"`, `"fade"`
  - デフォルト: `"fade"`

**バリデーションルール:**
```python
# video_ids または video_id が必要
if not video_ids:
    return 400, {"error": "video_ids is required"}

# 現在の実装では単一video_idのみサポート
if len(video_ids) > 1:
    return 400, {"error": "Stitching across multiple video_ids is not supported yet. Use a single video_id."}

# transition_type列挙型チェック
if transition_type not in {"cut", "fade"}:
    transition_type = "fade"  # デフォルトにフォールバック

# 最低2シーン必要
scenes = scene_manager.get_all_scenes()
if len(scenes) < 2:
    return 400, {"error": "At least two scenes are required to stitch a final video. Generate or extend first."}
```

**エラー例:**
```json
{
  "task_id": "",
  "video_id": "video-123",
  "stage": "stitch",
  "status": "error",
  "progress": null,
  "output_url": null,
  "frames": null,
  "error": "At least two scenes are required to stitch a final video. Generate or extend first."
}
```

---

### バリデーション実装リファレンス

**コード例 (`web_ui.py` での実装パターン):**
```python
@web_ui_blueprint.route('/api/edit', methods=['POST'])
def api_edit_frame():
    try:
        data = request.get_json() or {}
        video_id = data.get('video_id')
        raw_frame_index = data.get('frame_index')
        instruction = data.get('instruction')

        # 1. 型バリデーション
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

        # 2. 必須フィールドバリデーション
        if not video_id:
            return jsonify(build_task_response(
                task_id="",
                video_id="unknown",
                stage="edit",
                status="error",
                error="video_id is required"
            )), 400

        # 3. リソース存在確認
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

        # 4. 処理実行
        # ...

    except Exception as e:
        logger.error(f"API error: {e}", exc_info=True)
        return jsonify(build_task_response(
            task_id="",
            video_id=video_id or "unknown",
            stage="edit",
            status="error",
            error=str(e)
        )), 500
```

---

### バリデーション一覧表

| エンドポイント | 必須 | オプション | デフォルト値 |
|--------------|-----|-----------|------------|
| `/api/generate` | `prompt`, `image` (現在) | `video_id`, `duration` | duration=8 |
| `/api/extend` | `video_id`, `extra_duration` | `prompt`, `image` | - |
| `/api/extract` | `video_id` | `fps` | fps=2 |
| `/api/edit` | `video_id`, `frame_index`, `instruction` | - | - |
| `/api/stitch` | `video_ids` OR `video_id` | `transition_type` | transition_type="fade" |

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
