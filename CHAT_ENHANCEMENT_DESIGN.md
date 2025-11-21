# 🎬 エディタチャット強化 - 実装設計書

## 🎯 プロダクトビジョン
**生成AI時代に最適化された"対話的・積み上げ式"の動画制作**

ユーザーがチャットで自然言語で指示するだけで、動画の生成・拡張・編集を行えるシステム。

---

## 📊 既存システム分析

### ✅ 活用可能な既存実装

| コンポーネント | ファイル | 活用方法 |
|--------------|---------|---------|
| **Veo API統合** | `veo_generator.py:234-313` | `generate_video(image_path, prompt, previous_video)` |
| **動画連結** | `video_composer.py:71-150` | `compose_with_transitions(video_paths, transition_type)` |
| **フレーム編集** | `frame_editor.py` | `AIFrameEditor.generate_frame_variations(base_image, prompt)` |
| **Supabaseストレージ** | `supabase_storage.py` | `upload_file_to_supabase(path, local_file)` |
| **チャットUI** | `templates/video_editor_ui.html:88-159` | 既存のチャットUIをそのまま活用 |

---

## 🏗️ 新規実装アーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                     ユーザーチャット入力                          │
│                    "この画像から8秒の動画を作って"                  │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              🧠 ChatCommandHandler (NEW)                     │
│                    自然言語 → コマンド解釈                       │
├─────────────────────────────────────────────────────────────┤
│  • インテント分類: CREATE / EXTEND / TRANSITION / FRAME_EDIT  │
│  • パラメータ抽出: 画像パス, 秒数, プロンプト, etc.               │
└──────────────┬──────────────────────────────────────────────┘
               ↓
┌──────────────────────────────────────────────────────────────┐
│                   📊 SceneManager (NEW)                      │
│                  タイムライン・シーン管理                         │
├──────────────────────────────────────────────────────────────┤
│  • timeline: [Scene1, Scene2, ...]                          │
│  • scene_id, video_path, duration, prompt                   │
│  • add_scene(), get_timeline(), merge_scenes()              │
└──────────┬───────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────┐
│                  ⚙️ 既存機能の活用                             │
├──────────────────────────────────────────────────────────────┤
│  ① CREATE      → veo_generator.generate_video()             │
│  ② EXTEND      → veo_generator.generate_video(previous_video)│
│  ③ TRANSITION  → video_composer.compose_with_transitions()  │
│  ④ FRAME_EDIT  → AIFrameEditor.generate_frame_variations()  │
└──────────┬───────────────────────────────────────────────────┘
           ↓
┌──────────────────────────────────────────────────────────────┐
│               💾 Supabase保存 + UIフィードバック                │
│          • upload_file_to_supabase()                        │
│          • チャット履歴更新                                    │
│          • タイムラインUI更新（既存UIに統合）                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 🎯 4機能の実装詳細

### 🥇 ① 動画の生成（Create）

**ユーザー入力例:**
- "この画像から8秒の動画を作って"
- "image1.jpgをゆっくりズームインする動画にして"
- "物件の外観を見せる動画を生成"

**実装フロー:**
```python
# chat_command_handler.py
def handle_create_command(image_path: str, prompt: str, duration: str = "8s"):
    # 1. Veo APIで動画生成
    veo = VeoVideoGenerator(...)
    operation = veo.generate_video(
        image_path=image_path,
        prompt=prompt,
        duration=duration
    )

    # 2. ポーリングで完了待機（5分）
    video_response = veo.wait_for_completion(operation)

    # 3. gs:// → ローカルダウンロード
    local_path = veo.download_video(video_response)

    # 4. Supabaseにアップロード
    public_url = upload_file_to_supabase(f"{session_id}/scene1.mp4", local_path)

    # 5. タイムラインに追加
    scene_manager.add_scene(
        scene_id="scene1",
        video_path=local_path,
        video_url=public_url,
        duration=8.0,
        prompt=prompt
    )

    return {
        "status": "success",
        "scene_id": "scene1",
        "video_url": public_url,
        "message": "Scene1を作成しました（8秒）"
    }
```

**既存コードの活用:**
- ✅ `veo_generator.py:234-356` - generate_video()
- ✅ `veo_generator.py:482-621` - download_video()（3段階フォールバック）
- ✅ `supabase_storage.py:103-189` - upload_file_to_supabase()

**技術要素:**
- Polling: `time.sleep(10)` で最大5分
- gs:// → signed URL化: `veo_generator._download_video_with_fallback()`
- Supabase: `SUPABASE_BUCKET_NAME/sessions/{session_id}/scene1.mp4`

**完成すると:**
> "最初の1秒→8秒の魔法" が生まれる
> タイムラインに **Scene1** として表示される

---

### 🥈 ② 動画の拡張（Extend / Add Scene）

**ユーザー入力例:**
- "次のシーンを追加して"
- "image2.jpgから続きを作って"
- "リビングに移動する動画を追加"

**実装フロー:**
```python
def handle_extend_command(new_image_path: str, prompt: str):
    # 1. 最後のシーンを取得
    last_scene = scene_manager.get_last_scene()
    previous_video = veo.load_video_object(last_scene.video_path)

    # 2. シーン拡張（Veo APIのprevious_video機能）
    operation = veo.generate_video(
        image_path=new_image_path,
        prompt=prompt,
        duration="8s",
        previous_video=previous_video  # ← 前の動画を参照
    )

    # 3. ダウンロード & Supabaseアップロード
    video_response = veo.wait_for_completion(operation)
    local_path = veo.download_video(video_response)
    public_url = upload_file_to_supabase(f"{session_id}/scene2.mp4", local_path)

    # 4. タイムラインに追加
    scene_manager.add_scene(
        scene_id="scene2",
        video_path=local_path,
        video_url=public_url,
        duration=8.0,
        prompt=prompt,
        previous_scene_id="scene1"
    )

    return {
        "status": "success",
        "scene_id": "scene2",
        "message": "Scene2を追加しました"
    }
```

**既存コードの活用:**
- ✅ `veo_generator.py:288-289` - `previous_video` パラメータ対応済み
- ✅ `veo_generator.py:649-676` - シーン拡張ロジック

**技術要素:**
- `previous_video` = 前のシーンのVeo APIレスポンスオブジェクト
- timeline = `[Scene1, Scene2]` の append
- scene_id の自動生成: `f"scene{len(timeline)+1}"`

**完成すると:**
> "物件ツアーの2シーン目"が作れる
> エディタとして動き始める

---

### 🥉 ③ 動画と動画を繋げる（Transitions）

**ユーザー入力例:**
- "今までのシーンを繋げて"
- "フェード効果で連結して"
- "全体を一つの動画にまとめて"

**実装フロー:**
```python
def handle_transition_command(transition_type: str = "fade"):
    # 1. タイムラインから全シーンを取得
    scenes = scene_manager.get_all_scenes()
    video_paths = [scene.video_path for scene in scenes]

    # 2. VideoComposerで連結
    composer = VideoComposer()
    output_path = f"output/{session_id}/final_video.mp4"

    composed_path = composer.compose_with_transitions(
        video_paths=video_paths,
        output_path=output_path,
        transition_type=transition_type,  # "fade", "cut", "wipeleft", etc.
        transition_duration=0.5  # 0.5秒のトランジション
    )

    # 3. Supabaseにアップロード
    public_url = upload_file_to_supabase(
        f"{session_id}/final.mp4",
        composed_path
    )

    return {
        "status": "success",
        "video_url": public_url,
        "message": f"{len(scenes)}つのシーンを{transition_type}で連結しました"
    }
```

**既存コードの活用:**
- ✅ `video_composer.py:71-150` - compose_with_transitions()
- ✅ FFmpegフィルターグラフ自動生成済み

**技術要素:**
- **MVP**: `cut`（単純連結）で十分
- **Optional**: `crossfade`（フェード効果）
- フロント側のプレビュー: 連続再生で再現

**完成すると:**
> "複数動画が1本の広告動画っぽく見える"
> Scene1 → (fade 0.5s) → Scene2 → (fade 0.5s) → Scene3

---

### 🏅 ④ フレームごとのミニマム編集（Frame Edit）

**ユーザー入力例:**
- "Scene1の3秒目を明るくして"
- "Scene2の最初のフレームを編集"
- "この部分の色を鮮やかにして"

**実装フロー:**
```python
def handle_frame_edit_command(
    scene_id: str,
    timestamp: float,
    prompt: str
):
    # 1. シーンから特定フレームを抽出
    scene = scene_manager.get_scene(scene_id)
    frame_editor = FrameEditor(scene.video_path)

    # フレーム抽出（timestampから最も近いフレーム）
    frame_path = frame_editor.extract_frame_at_time(timestamp)

    # 2. AI編集（既存のAIFrameEditor）
    ai_editor = AIFrameEditor(api_key)
    variations = ai_editor.generate_frame_variations(
        base_image_path=frame_path,
        prompt=prompt,
        variation_count=4
    )

    # 3. ユーザーに選択肢を返す（UIで選択）
    return {
        "status": "success",
        "variations": variations,
        "message": "4つのバリエーションを生成しました"
    }

    # 4. ユーザーが選択後、フレームを適用
    # （別エンドポイント /editor/chat/apply-frame）
    frame_editor.apply_edited_frame(
        frame_id=frame_id,
        edited_image_data=selected_variation
    )

    # 5. 編集後のシーンを再生成
    updated_video_path = frame_editor.rebuild_video()
    scene_manager.update_scene(scene_id, updated_video_path)
```

**既存コードの活用:**
- ✅ `frame_editor.py:62-123` - extract_frames()
- ✅ `web_ui.py:724-779` - /frames/edit エンドポイント
- ✅ `web_ui.py:782-823` - /frames/apply エンドポイント

**技術要素:**
- FFmpegでフレーム抽出: `ffmpeg -ss {timestamp} -i video.mp4 -frames:v 1 frame.png`
- AI編集: Google Imagen / Stability AI
- フレーム置換: FFmpegで元動画にマージ

**完成すると:**
> "動画の特定部分を編集する最小の仕組み"
> チャットから「Scene1の3秒目を明るくして」が可能に

---

## 🧠 自然言語コマンド解釈エンジン

### 実装: `chat_command_handler.py`

```python
import re
from typing import Dict, Any, Optional
from enum import Enum

class CommandIntent(Enum):
    CREATE = "create"           # 新しい動画を作る
    EXTEND = "extend"           # シーンを追加
    TRANSITION = "transition"   # 動画を繋げる
    FRAME_EDIT = "frame_edit"   # フレーム編集
    UNKNOWN = "unknown"

class ChatCommandHandler:
    """
    自然言語をコマンドに変換するハンドラー
    """

    # インテント分類用のキーワード
    INTENT_PATTERNS = {
        CommandIntent.CREATE: [
            r"作.*動画", r"生成", r"から.*秒", r"動画.*作",
            r"generate", r"create video"
        ],
        CommandIntent.EXTEND: [
            r"次.*シーン", r"追加", r"続き", r"シーン.*追加",
            r"add scene", r"extend", r"next scene"
        ],
        CommandIntent.TRANSITION: [
            r"繋げ", r"連結", r"まとめ", r"一つ.*動画",
            r"merge", r"combine", r"transition"
        ],
        CommandIntent.FRAME_EDIT: [
            r"フレーム.*編集", r"秒目", r"明るく", r"色.*変",
            r"edit frame", r"brighten", r"adjust"
        ]
    }

    def parse_command(self, user_input: str) -> Dict[str, Any]:
        """
        ユーザー入力を解析してコマンドに変換

        Returns:
            {
                "intent": CommandIntent,
                "params": {
                    "image_path": str,
                    "prompt": str,
                    "duration": str,
                    ...
                }
            }
        """
        intent = self._classify_intent(user_input)
        params = self._extract_parameters(user_input, intent)

        return {
            "intent": intent,
            "params": params,
            "original_input": user_input
        }

    def _classify_intent(self, text: str) -> CommandIntent:
        """インテント分類"""
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return intent
        return CommandIntent.UNKNOWN

    def _extract_parameters(
        self,
        text: str,
        intent: CommandIntent
    ) -> Dict[str, Any]:
        """パラメータ抽出"""
        params = {}

        # 秒数抽出: "8秒", "10s", etc.
        duration_match = re.search(r'(\d+)\s*[秒s]', text)
        if duration_match:
            params['duration'] = f"{duration_match.group(1)}s"
        else:
            params['duration'] = "8s"  # デフォルト

        # 画像パス抽出: "image1.jpg", "IMG_001.png", etc.
        image_match = re.search(r'([a-zA-Z0-9_\-\.]+\.(jpg|jpeg|png|webp))', text, re.IGNORECASE)
        if image_match:
            params['image_path'] = image_match.group(1)

        # トランジションタイプ: "フェード", "fade", etc.
        if 'フェード' in text or 'fade' in text.lower():
            params['transition_type'] = 'fade'
        else:
            params['transition_type'] = 'cut'

        # タイムスタンプ抽出: "3秒目", "5s at", etc.
        timestamp_match = re.search(r'(\d+)\s*秒目', text)
        if timestamp_match:
            params['timestamp'] = float(timestamp_match.group(1))

        # シーンID: "Scene1", "scene2", etc.
        scene_match = re.search(r'[Ss]cene\s*(\d+)', text)
        if scene_match:
            params['scene_id'] = f"scene{scene_match.group(1)}"

        # プロンプト（AIへの指示）
        # 全体をプロンプトとして保存（細かい処理は各ハンドラーで）
        params['prompt'] = text

        return params
```

---

## 📊 シーン管理システム

### 実装: `scene_manager.py`

```python
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import json
import os

@dataclass
class Scene:
    """シーン情報"""
    scene_id: str
    video_path: str
    video_url: str
    duration: float
    prompt: str
    created_at: str
    previous_scene_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class SceneManager:
    """
    タイムライン・シーン管理システム
    """

    def __init__(self, session_id: str, storage_dir: str = "output"):
        self.session_id = session_id
        self.storage_dir = storage_dir
        self.timeline: List[Scene] = []
        self._load_timeline()

    def add_scene(
        self,
        scene_id: str,
        video_path: str,
        video_url: str,
        duration: float,
        prompt: str,
        previous_scene_id: Optional[str] = None
    ) -> Scene:
        """シーンを追加"""
        from datetime import datetime

        scene = Scene(
            scene_id=scene_id,
            video_path=video_path,
            video_url=video_url,
            duration=duration,
            prompt=prompt,
            created_at=datetime.now().isoformat(),
            previous_scene_id=previous_scene_id
        )

        self.timeline.append(scene)
        self._save_timeline()
        return scene

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """シーンを取得"""
        for scene in self.timeline:
            if scene.scene_id == scene_id:
                return scene
        return None

    def get_last_scene(self) -> Optional[Scene]:
        """最後のシーンを取得"""
        return self.timeline[-1] if self.timeline else None

    def get_all_scenes(self) -> List[Scene]:
        """全シーンを取得"""
        return self.timeline

    def update_scene(self, scene_id: str, updated_video_path: str):
        """シーンを更新（編集後）"""
        for scene in self.timeline:
            if scene.scene_id == scene_id:
                scene.video_path = updated_video_path
                self._save_timeline()
                break

    def get_timeline_duration(self) -> float:
        """タイムライン全体の長さ"""
        return sum(scene.duration for scene in self.timeline)

    def _save_timeline(self):
        """タイムラインを保存"""
        timeline_path = os.path.join(
            self.storage_dir,
            self.session_id,
            "timeline.json"
        )
        os.makedirs(os.path.dirname(timeline_path), exist_ok=True)

        with open(timeline_path, 'w', encoding='utf-8') as f:
            json.dump(
                [asdict(scene) for scene in self.timeline],
                f,
                ensure_ascii=False,
                indent=2
            )

    def _load_timeline(self):
        """タイムラインを読み込み"""
        timeline_path = os.path.join(
            self.storage_dir,
            self.session_id,
            "timeline.json"
        )

        if os.path.exists(timeline_path):
            with open(timeline_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.timeline = [Scene(**item) for item in data]
```

---

## 🌐 統合チャットAPIエンドポイント

### 実装: `web_ui.py` に追加

```python
@web_ui_blueprint.route('/editor/chat', methods=['POST'])
def editor_chat():
    """
    統合チャットエンドポイント
    自然言語 → 4機能のルーティング
    """
    try:
        data = request.get_json()
        user_input = data.get('message', '')
        session_id = session.get('editor_session_id')

        if not user_input:
            return jsonify({
                "status": "error",
                "message": "メッセージが必要です"
            }), 400

        # 1. チャット履歴に追加
        if 'chat_history' not in session:
            session['chat_history'] = []
        session['chat_history'].append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })

        # 2. コマンド解釈
        handler = ChatCommandHandler()
        command = handler.parse_command(user_input)

        # 3. SceneManager初期化
        scene_manager = SceneManager(session_id)

        # 4. インテントに応じて処理分岐
        intent = command['intent']
        params = command['params']

        if intent == CommandIntent.CREATE:
            result = _handle_create_video(params, scene_manager, session_id)

        elif intent == CommandIntent.EXTEND:
            result = _handle_extend_scene(params, scene_manager, session_id)

        elif intent == CommandIntent.TRANSITION:
            result = _handle_merge_scenes(params, scene_manager, session_id)

        elif intent == CommandIntent.FRAME_EDIT:
            result = _handle_frame_edit(params, scene_manager)

        else:
            result = {
                "status": "error",
                "message": "コマンドを理解できませんでした。もう一度お試しください。"
            }

        # 5. チャット履歴に応答を追加
        session['chat_history'].append({
            "role": "assistant",
            "content": result.get('message', ''),
            "timestamp": datetime.now().isoformat(),
            "data": result
        })

        return jsonify(result)

    except Exception as e:
        logger.error(f"Editor chat error: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


def _handle_create_video(params, scene_manager, session_id):
    """① 動画生成処理"""
    # Celeryタスクとして非同期実行
    from tasks import generate_video_from_chat_task

    task = generate_video_from_chat_task.delay(
        session_id=session_id,
        image_path=params.get('image_path'),
        prompt=params.get('prompt'),
        duration=params.get('duration', '8s')
    )

    return {
        "status": "processing",
        "task_id": task.id,
        "message": "動画を生成中です（約2-5分）...",
        "intent": "create"
    }


def _handle_extend_scene(params, scene_manager, session_id):
    """② シーン拡張処理"""
    last_scene = scene_manager.get_last_scene()

    if not last_scene:
        return {
            "status": "error",
            "message": "最初にシーンを作成してください"
        }

    from tasks import extend_scene_task

    task = extend_scene_task.delay(
        session_id=session_id,
        previous_scene_id=last_scene.scene_id,
        new_image_path=params.get('image_path'),
        prompt=params.get('prompt'),
        duration=params.get('duration', '8s')
    )

    return {
        "status": "processing",
        "task_id": task.id,
        "message": f"{last_scene.scene_id}の次のシーンを生成中...",
        "intent": "extend"
    }


def _handle_merge_scenes(params, scene_manager, session_id):
    """③ 動画連結処理"""
    scenes = scene_manager.get_all_scenes()

    if len(scenes) < 2:
        return {
            "status": "error",
            "message": "最低2つのシーンが必要です"
        }

    from tasks import merge_scenes_task

    task = merge_scenes_task.delay(
        session_id=session_id,
        transition_type=params.get('transition_type', 'fade')
    )

    return {
        "status": "processing",
        "task_id": task.id,
        "message": f"{len(scenes)}つのシーンを連結中...",
        "intent": "transition"
    }


def _handle_frame_edit(params, scene_manager):
    """④ フレーム編集処理"""
    scene_id = params.get('scene_id')

    if not scene_id:
        # scene_idが指定されていない場合、最後のシーンを対象
        last_scene = scene_manager.get_last_scene()
        if not last_scene:
            return {
                "status": "error",
                "message": "編集するシーンがありません"
            }
        scene_id = last_scene.scene_id

    scene = scene_manager.get_scene(scene_id)

    # 既存のフレーム編集機能を活用
    # （詳細は既存の /frames/edit と同じ）

    return {
        "status": "success",
        "message": f"{scene_id}のフレームを編集中...",
        "intent": "frame_edit",
        "scene_id": scene_id
    }
```

---

## 🚀 実装ロードマップ

### Phase 1: コア機能実装（Week 1-2）
1. ✅ `chat_command_handler.py` - NLP解釈エンジン
2. ✅ `scene_manager.py` - シーン管理システム
3. ✅ `web_ui.py` - `/editor/chat` エンドポイント
4. ✅ `tasks.py` - Celery非同期タスク（create, extend, merge）

### Phase 2: 統合テスト（Week 3）
5. ✅ CREATE → EXTEND → TRANSITION の完全フロー
6. ✅ チャット履歴の保存・表示
7. ✅ タイムラインUIの更新（既存UIに統合）

### Phase 3: UX改善（Week 4）
8. ✅ リアルタイムプログレス表示
9. ✅ エラーハンドリング強化
10. ✅ ドキュメント・サンプル整備

---

## 📝 チャット会話例

### 例1: 物件ツアー動画の作成

```
User: "外観.jpgから8秒の動画を作って。物件をゆっくりズームイン"
AI:   ✓ Scene1を生成中...（2分）
      ✓ Scene1完成！タイムラインに追加しました。

User: "次に玄関.jpgで玄関のドアが開くシーンを追加"
AI:   ✓ Scene2を生成中...（2分）
      ✓ Scene2完成！Scene1の後に追加しました。

User: "リビング.jpgで明るいリビングを見せるシーンも追加"
AI:   ✓ Scene3を生成中...（2分）
      ✓ Scene3完成！

User: "全部フェード効果で繋げて"
AI:   ✓ 3つのシーンをフェード効果で連結中...（30秒）
      ✓ 完成！24秒の動画ができました。
      📥 ダウンロード: https://supabase.../final.mp4
```

### 例2: フレーム編集

```
User: "Scene1の最初のフレームを明るくして"
AI:   ✓ Scene1のフレームを抽出中...
      ✓ AI編集で4つのバリエーションを生成しました。
      選択してください: [variation1, variation2, variation3, variation4]

User: "2番目を選択"
AI:   ✓ Scene1を更新しました。
      タイムラインが更新されました。
```

---

## 🎯 成功指標

| 指標 | 目標 |
|------|------|
| **動画生成時間** | 2-5分/シーン |
| **コマンド理解率** | 90%以上 |
| **ユーザー操作数** | 平均3回のチャットで完成 |
| **エラー率** | 5%以下 |
| **タイムライン表示** | リアルタイム更新 |

---

## 📚 技術スタック

| レイヤー | 技術 |
|---------|------|
| **フロントエンド** | 既存HTML/CSS/JS（変更不要） |
| **バックエンド** | Flask + Python 3.10+ |
| **非同期処理** | Celery + Redis |
| **動画生成** | Google Veo API (Vertex AI) |
| **動画編集** | FFmpeg |
| **ストレージ** | Supabase Storage |
| **NLP** | 正規表現ベース（MVP）→ 将来: LLM統合 |

---

## ✅ チェックリスト

### 実装前の確認
- [ ] Vertex認証用のプロジェクトIDが設定されているか（`GOOGLE_CLOUD_PROJECT` または `GCP_PROJECT_ID`）
- [ ] Supabaseが設定されているか（`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`）
- [ ] FFmpegがインストールされているか（`which ffmpeg`）
- [ ] Celeryが起動しているか（`celery -A celery_app worker`）
- [ ] Redisが起動しているか（`redis-cli ping`）

### 実装後のテスト
- [ ] CREATE: 画像 → 動画生成
- [ ] EXTEND: 次のシーンを追加
- [ ] TRANSITION: 動画を連結
- [ ] FRAME_EDIT: フレーム編集
- [ ] チャット履歴が保存されるか
- [ ] タイムラインが正しく表示されるか
- [ ] エラーハンドリングが機能するか

---

## 🎉 期待される成果

1. **ユーザー体験の革新**
   - コード不要、チャットだけで動画制作
   - 対話的・積み上げ式のワークフロー

2. **生産性の向上**
   - 従来: 複数ツール × 手動編集 → **1時間**
   - 新方式: チャット × AI生成 → **10分**

3. **プロダクトの差別化**
   - "生成AI時代に最適化された動画制作ツール"
   - ノーコードで高品質な不動産動画を自動生成

---

## 📞 次のステップ

このドキュメントを確認後、以下を実行します：

1. **実装開始**: `chat_command_handler.py`, `scene_manager.py` を作成
2. **API統合**: `web_ui.py` に `/editor/chat` エンドポイント追加
3. **Celeryタスク**: `tasks.py` に非同期タスクを追加
4. **テスト**: エンドツーエンドテストの実行
5. **コミット**: 変更をGitにプッシュ

---

**設計書作成者**: Claude Code
**作成日**: 2025-11-17
**バージョン**: 1.0.0
