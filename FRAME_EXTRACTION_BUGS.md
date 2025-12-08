# フレーム抽出機能のバグレポート

**作成日**: 2025-12-08
**優先度**: 🔴 高
**影響範囲**: フレーム抽出API、動画編集機能

---

## 概要

フレーム抽出関連のコードに複数の重大なバグが発見されました。これらのバグは、API呼び出しの失敗やパラメータの無視につながる可能性があります。

---

## 🔴 バグ #1: `extract_frames_task` の重複定義

### 問題の詳細

**場所**: `tasks.py`

同じタスクが2回定義されており、2回目の定義が1回目を上書きしています。しかし、各定義のシグネチャが異なります。

#### 1回目の定義 (Line 169-234)
```python
@celery.task(bind=True, name="tasks.extract_frames_task")
def extract_frames_task(self, task_id: str, video_path: str, bucket: Optional[str] = None) -> Dict[str, Any]:
    """
    Download a video from Supabase and extract JPEG frames at a fixed FPS.
    """
```

#### 2回目の定義 (Line 1527-1602) - これが実際に使われる
```python
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
```

### 影響範囲

**routes.py:37** では1回目のシグネチャで呼び出していますが、実際には2回目の定義が使用されます:

```python
# routes.py Line 37
extract_frames_task.delay(task_id, video_path)
# ↑ これは (task_id, video_path) の順で渡している

# しかし実際の関数は (video_id, video_path) を期待
# task_id は必須パラメータだが、実際の関数では video_path がオプション
```

### 修正方法

**オプション A: 2つのタスクに分離する（推奨）**

```python
# 1つ目: Supabaseからのフレーム抽出用
@celery.task(bind=True, name="tasks.extract_frames_from_supabase")
def extract_frames_from_supabase(self, task_id: str, video_path: str, bucket: Optional[str] = None):
    # 既存の1回目の実装

# 2つ目: ローカル動画からのフレーム抽出用
@celery.task(bind=True, name="tasks.extract_frames_from_local")
def extract_frames_from_local(self, video_id: str, video_path: Optional[str] = None, fps: float = 1.0):
    # 既存の2回目の実装
```

**オプション B: 1つのタスクに統合する**

```python
@celery.task(bind=True, name="tasks.extract_frames_task")
def extract_frames_task(
    self,
    video_id: str,
    video_path: Optional[str] = None,
    bucket: Optional[str] = None,
    fps: float = 4.0,
    source: str = "local"  # "local" or "supabase"
) -> Dict[str, Any]:
    """
    Extract frames from a video (local or Supabase).
    """
    if source == "supabase":
        # 1回目の実装ロジック
        pass
    else:
        # 2回目の実装ロジック
        pass
```

**routes.py の修正も必要:**

```python
# routes.py Line 37 を修正
extract_frames_from_supabase.delay(task_id, video_path)  # オプションA
# または
extract_frames_task.delay(task_id, video_path, source="supabase")  # オプションB
```

---

## 🔴 バグ #2: `frame_count` パラメータが無視される

### 問題の詳細

**場所**: `frame_editor.py:89-113`

`extract_frames` 関数のシグネチャで `frame_count` パラメータを受け取っていますが、実装では完全に無視されています。

```python
def extract_frames(self, frame_count: int = None, fps: float = 5.0) -> List[Dict[str, Any]]:
    """
    Extract frames from video at regular intervals

    Args:
        frame_count: Number of frames to extract (legacy, ignored if fps is set)
        fps: Frames per second to extract (default: 5.0)
    """
    # ...
    # Line 113: frame_count は使われず、fps だけで計算される
    actual_frame_count = max(1, int(duration * fps))
```

### 影響範囲

以下の箇所で `frame_count` を指定しているが、実際には無視されます:

1. **tasks.py:1564**
```python
extracted_frames = frame_editor.extract_frames(frame_count=frame_count)
```

2. **tasks.py:1649**
```python
extracted = frame_editor.extract_frames(frame_count=frame_index + 5)
```

### 修正方法

**オプション A: `frame_count` を優先する（後方互換性維持）**

```python
def extract_frames(self, frame_count: int = None, fps: float = 5.0) -> List[Dict[str, Any]]:
    """
    Extract frames from video at regular intervals

    Args:
        frame_count: Number of frames to extract (if specified, takes priority over fps)
        fps: Frames per second to extract (default: 5.0, used if frame_count is None)
    """
    logger.debug(f"Extracting frames from video...")

    if not os.path.exists(self.video_path):
        raise FileNotFoundError(f"Video not found: {self.video_path}")

    duration = self.get_video_duration()

    if duration <= 0:
        raise RuntimeError(f"Invalid video duration: {duration}")

    # frame_count が指定されていればそれを使用、そうでなければ fps から計算
    if frame_count is not None:
        actual_frame_count = max(1, min(frame_count, int(duration * 60)))  # 最大60fps相当
        interval = duration / actual_frame_count
    else:
        interval = 1.0 / fps
        actual_frame_count = max(1, int(duration * fps))

    self.frames = []

    for i in range(actual_frame_count):
        timestamp = interval * i
        if timestamp >= duration:
            timestamp = max(duration - 0.001, 0)
        # ... 以下既存の実装
```

**オプション B: `frame_count` パラメータを削除（クリーンアップ）**

```python
def extract_frames(self, fps: float = 5.0) -> List[Dict[str, Any]]:
    """
    Extract frames from video at regular intervals

    Args:
        fps: Frames per second to extract (default: 5.0)
    """
    # 既存の実装のまま
```

そして呼び出し側を修正:

```python
# tasks.py:1564 を修正
target_fps = frame_count / video_duration if frame_count else 1.0
extracted_frames = frame_editor.extract_frames(fps=target_fps)

# tasks.py:1649 を修正
target_fps = (frame_index + 5) / video_duration
extracted = frame_editor.extract_frames(fps=target_fps)
```

---

## 🟡 バグ #3: コメントの誤り

### 問題の詳細

**場所**: `frame_editor.py:111-112`

```python
# Calculate frame count based on fps (3 frames per second)
interval = 1.0 / fps  # e.g., 0.333 seconds for 3 fps
actual_frame_count = max(1, int(duration * fps))
```

コメントに「3 frames per second」と記載されていますが、実際のデフォルト値は `fps: float = 5.0` です。

### 修正方法

```python
# Calculate frame count based on fps
interval = 1.0 / fps  # e.g., 0.2 seconds for 5 fps (default)
actual_frame_count = max(1, int(duration * fps))
```

---

## 🟡 バグ #4: タイムスタンプ計算の不一致

### 問題の詳細

フレームのタイムスタンプを計算するロジックが、異なるファイルで異なっています。

**frame_editor.py:117**
```python
timestamp = interval * i  # i は 0 から始まる
```

**tasks.py:197** (1回目の extract_frames_task)
```python
timestamp_seconds = idx / FRAME_EXTRACTION_FPS  # idx は 0 から始まる
```

**utils/video.py:14-53** (extract_frames_ffmpeg)
```python
# ffmpeg の fps フィルターを使用
# ffmpeg が自動的にタイムスタンプを計算
```

### 影響

- `frame_editor.py`: `timestamp = interval * i` → 最初のフレームは 0秒
- `tasks.py`: `timestamp_seconds = idx / FRAME_EXTRACTION_FPS` → 最初のフレームは 0秒
- `utils/video.py`: ffmpegのfpsフィルター → ffmpegが自動計算

計算方法は概ね一致していますが、コードの一貫性がありません。

### 修正方法

**共通のヘルパー関数を作成する:**

```python
# utils/frame_utils.py (新規作成)
def calculate_frame_timestamp(frame_index: int, fps: float) -> float:
    """
    Calculate timestamp for a frame at given index.

    Args:
        frame_index: Frame index (0-based)
        fps: Frames per second

    Returns:
        Timestamp in seconds
    """
    return frame_index / fps
```

そして各ファイルで使用:

```python
# frame_editor.py
from utils.frame_utils import calculate_frame_timestamp

timestamp = calculate_frame_timestamp(i, fps)

# tasks.py
from utils.frame_utils import calculate_frame_timestamp

timestamp_seconds = calculate_frame_timestamp(idx, FRAME_EXTRACTION_FPS)
```

---

## テスト手順

### バグ #1 のテスト

```bash
# routes.py 経由でフレーム抽出APIを呼び出す
curl -X POST http://localhost:5000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"task_id": "test123", "video_path": "videos/test/input.mp4"}'

# エラーが発生するか確認
# 修正後: 正常に処理されることを確認
```

### バグ #2 のテスト

```python
# frame_editor.py のテスト
from frame_editor import FrameEditor

editor = FrameEditor("test_video.mp4")

# frame_count=10 を指定
frames = editor.extract_frames(frame_count=10)

# 修正前: fpsで計算されるため、10フレームにならない可能性
# 修正後: 正確に10フレーム抽出されることを確認
assert len(frames) == 10
```

### バグ #3, #4 のテスト

```python
# コードレビューで確認
# コメントとコードの一貫性をチェック
```

---

## 優先順位と推奨修正順序

1. **🔴 最優先: バグ #1** - API呼び出しが失敗する可能性がある
2. **🔴 高優先: バグ #2** - パラメータが無視されている
3. **🟡 中優先: バグ #3** - コメントの修正
4. **🟡 中優先: バグ #4** - コードの一貫性向上

---

## 追加の推奨事項

### 1. ユニットテストの追加

現在、フレーム抽出機能のユニットテストが不足しています。以下のテストを追加することを推奨します:

```python
# tests/test_frame_extraction.py
import pytest
from frame_editor import FrameEditor

def test_extract_frames_with_frame_count():
    """frame_count パラメータが正しく動作することを確認"""
    editor = FrameEditor("test_video.mp4")
    frames = editor.extract_frames(frame_count=10)
    assert len(frames) == 10

def test_extract_frames_with_fps():
    """fps パラメータが正しく動作することを確認"""
    editor = FrameEditor("test_video.mp4")  # 10秒の動画
    frames = editor.extract_frames(fps=2.0)
    assert len(frames) == 20  # 10秒 × 2fps = 20フレーム
```

### 2. 型ヒントの一貫性

一部の関数で型ヒントが不足しています。すべての関数に適切な型ヒントを追加することを推奨します。

### 3. ドキュメントの更新

修正後、以下のドキュメントを更新してください:
- README.md
- API documentation
- Function docstrings

---

## 質問・相談先

このバグレポートに関する質問や、修正方針について相談がある場合は、以下に連絡してください:

- **担当者**: [名前を記入]
- **Slack**: #video-generation-team
- **GitHub Issue**: [Issue番号を記入]

---

**注意**: このドキュメントは修正が完了するまで更新してください。修正完了後、各バグの横に ✅ マークを追加してください。
