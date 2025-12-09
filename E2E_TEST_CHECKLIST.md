# 🧪 On-Demand Frame Extraction - E2E Test Checklist

**実装ブランチ:** `claude/evaluate-ui-performance-solutions-01YDyBLFArAqnvA6yzrAaG4V`
**コミット:** `1b04c57`

---

## 📋 Pre-Test Setup

### 1. サーバー起動

```bash
# ターミナル 1: Redis (Celery broker)
redis-server

# ターミナル 2: Celery worker
cd /home/user/real-estate-video-generator
celery -A tasks.celery worker --loglevel=info

# ターミナル 3: Flask server
cd /home/user/real-estate-video-generator
python app.py
```

### 2. ブラウザでアクセス

```
http://localhost:5000/editor
```

### 3. テスト用動画を用意

以下のいずれかを用意:
- [ ] 8秒の短い動画 (192 frames @ 24fps)
- [ ] 20秒の中程度の動画 (480 frames @ 24fps)
- [ ] 60秒の長い動画 (1440 frames @ 24fps)

---

## 🧪 Test Suite 1: Backend API Tests

### Test 1.1: FrameEditor.extract_frame_at_timestamp() - 正常系

```bash
cd /home/user/real-estate-video-generator

# Pythonインタラクティブシェルで実行
python3 << 'EOF'
import os
from frame_editor import FrameEditor

# テスト用動画パスを設定（実際のパスに置き換え）
# 例: video_path = "uploads/local/session_xxx/video.mp4"
video_path = input("Enter video path: ")

if not os.path.exists(video_path):
    print(f"❌ Video not found: {video_path}")
    exit(1)

# FrameEditorインスタンス作成
editor = FrameEditor(video_path, "test_frames")

# 動画の長さを取得
duration = editor.get_video_duration()
print(f"✅ Video duration: {duration}s")

# Test 1: 開始位置 (0s)
print("\n--- Test 1: Extract at 0s ---")
frame = editor.extract_frame_at_timestamp(0.0)
print(f"✅ Timestamp: {frame['timestamp']}, Path: {frame['path']}")
assert frame['seconds'] == 0.0, "Timestamp mismatch"
assert os.path.exists(frame['path']), "Frame file not created"
assert os.path.getsize(frame['path']) > 0, "Frame file is empty"
print("✅ Test 1 PASSED")

# Test 2: 中間位置 (duration / 2)
mid_timestamp = duration / 2
print(f"\n--- Test 2: Extract at {mid_timestamp}s ---")
frame = editor.extract_frame_at_timestamp(mid_timestamp)
print(f"✅ Timestamp: {frame['timestamp']}, Path: {frame['path']}")
assert abs(frame['seconds'] - mid_timestamp) < 0.1, "Timestamp mismatch"
assert os.path.exists(frame['path']), "Frame file not created"
print("✅ Test 2 PASSED")

# Test 3: 終端近く (duration - 0.5s)
end_timestamp = duration - 0.5
print(f"\n--- Test 3: Extract at {end_timestamp}s ---")
frame = editor.extract_frame_at_timestamp(end_timestamp)
print(f"✅ Timestamp: {frame['timestamp']}, Path: {frame['path']}")
assert os.path.exists(frame['path']), "Frame file not created"
print("✅ Test 3 PASSED")

print("\n🎉 All FrameEditor tests PASSED!")
EOF
```

**Expected Output:**
```
✅ Video duration: 8.0s
--- Test 1: Extract at 0s ---
✅ Timestamp: 0:00.0, Path: test_frames/frame_at_0ms.jpg
✅ Test 1 PASSED
--- Test 2: Extract at 4.0s ---
✅ Timestamp: 0:04.0, Path: test_frames/frame_at_4000ms.jpg
✅ Test 2 PASSED
--- Test 3: Extract at 7.5s ---
✅ Timestamp: 0:07.5, Path: test_frames/frame_at_7500ms.jpg
✅ Test 3 PASSED
🎉 All FrameEditor tests PASSED!
```

---

### Test 1.2: FrameEditor - エラーハンドリング

```bash
python3 << 'EOF'
from frame_editor import FrameEditor
import os

# Test 1: 存在しない動画
print("--- Test: Non-existent video ---")
try:
    editor = FrameEditor("/nonexistent/video.mp4", "test_frames")
    editor.extract_frame_at_timestamp(1.0)
    print("❌ Should have raised FileNotFoundError")
except FileNotFoundError as e:
    print(f"✅ Correctly raised FileNotFoundError: {e}")

# Test 2: 負のタイムスタンプ
print("\n--- Test: Negative timestamp ---")
video_path = input("Enter valid video path: ")
editor = FrameEditor(video_path, "test_frames")
try:
    editor.extract_frame_at_timestamp(-1.0)
    print("❌ Should have raised ValueError")
except ValueError as e:
    print(f"✅ Correctly raised ValueError: {e}")

# Test 3: 動画の長さを超えるタイムスタンプ
print("\n--- Test: Timestamp exceeds duration ---")
duration = editor.get_video_duration()
try:
    editor.extract_frame_at_timestamp(duration + 10.0)
    print("❌ Should have raised ValueError")
except ValueError as e:
    print(f"✅ Correctly raised ValueError: {e}")

print("\n🎉 All error handling tests PASSED!")
EOF
```

---

### Test 1.3: Web API Endpoint - curl テスト

```bash
# まず Flask サーバーが起動していることを確認
# http://localhost:5000 でアクセス可能か確認

# Test 1: 正常なリクエスト
# 注意: video_path は実際にアップロードした動画のパスに置き換える
curl -X POST http://localhost:5000/frames/extract_at_time \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "uploads/local/session_xxx/video.mp4",
    "timestamp": 3.5
  }' | jq '.'

# Expected Output:
# {
#   "status": "success",
#   "frame": {
#     "frame_id": 0,
#     "name": "frame at 0:03.5",
#     "path": "frames/session_xxx/timeline/frame_at_3500ms.jpg",
#     "timestamp": "0:03.5",
#     "seconds": 3.5,
#     "base64": "data:image/jpeg;base64,..."
#   }
# }

# Test 2: video_path が存在しない
curl -X POST http://localhost:5000/frames/extract_at_time \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "/nonexistent/video.mp4",
    "timestamp": 1.0
  }' | jq '.'

# Expected Output:
# {
#   "status": "error",
#   "message": "Video not found: /nonexistent/video.mp4"
# }

# Test 3: timestamp が不正
curl -X POST http://localhost:5000/frames/extract_at_time \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "uploads/local/session_xxx/video.mp4",
    "timestamp": "invalid"
  }' | jq '.'

# Expected Output:
# {
#   "status": "error",
#   "message": "timestamp must be a number"
# }

# Test 4: 必須パラメータ欠落
curl -X POST http://localhost:5000/frames/extract_at_time \
  -H "Content-Type: application/json" \
  -d '{}' | jq '.'

# Expected Output:
# {
#   "status": "error",
#   "message": "video_path is required"
# }
```

---

## 🧪 Test Suite 2: Frontend Manual Tests

### Test 2.1: UI 要素の表示確認

**手順:**
1. ブラウザで `http://localhost:5000/editor` を開く
2. 動画をアップロード
3. "Extract Frames" ボタンをクリック
4. タイムラインが表示されることを確認

**チェック項目:**
- [ ] タイムラインが表示される (`#liquid-glass-timeline-section`)
- [ ] フレームカードが横スクロールで表示される
- [ ] Frame counter が表示される (例: "#1 / 24")
- [ ] タイムスタンプが表示される (例: "0:00.0")

---

### Test 2.2: タイムラインダブルクリック - 基本動作

**手順:**
1. タイムライン上の任意の位置をダブルクリック
2. ローディング表示が出ることを確認
3. フレームプレビューモーダルが表示されることを確認

**チェック項目:**
- [ ] ダブルクリックでローディングスピナーが表示される
- [ ] "Extracting frame at X:XX..." メッセージが表示される
- [ ] 2〜3秒後にプレビューモーダルが表示される
- [ ] モーダルに抽出されたフレーム画像が表示される
- [ ] タイムスタンプが正しく表示される
- [ ] "Edit This Frame" ボタンが表示される
- [ ] "Close" ボタンが表示される

---

### Test 2.3: タイムスタンプ計算の精度確認

**手順:**
1. 8秒の動画をアップロード
2. タイムラインの**左端**をダブルクリック → 約 0:00.0 が抽出されるはず
3. タイムラインの**中央**をダブルクリック → 約 0:04.0 が抽出されるはず
4. タイムラインの**右端**をダブルクリック → 約 0:08.0 が抽出されるはず

**チェック項目:**
- [ ] 左端クリック: タイムスタンプ 0:00.0 〜 0:01.0
- [ ] 中央クリック: タイムスタンプ 0:03.5 〜 0:04.5
- [ ] 右端クリック: タイムスタンプ 0:07.0 〜 0:08.0

**デバッグ用:**
ブラウザの開発者ツール (F12) → Console タブを開いて、以下のログを確認:
```
Timeline clicked: position=150, scroll=0, percentage=25.0%, timestamp=2.00s
```

---

### Test 2.4: モーダル操作

**手順:**
1. タイムラインをダブルクリックしてモーダルを表示
2. 各ボタンの動作を確認

**チェック項目:**
- [ ] "Close" ボタンをクリック → モーダルが閉じる
- [ ] モーダル外側（背景）をクリック → モーダルが閉じる
- [ ] "Edit This Frame" ボタンをクリック → アラート表示 (現在はプレースホルダー)
- [ ] モーダルを閉じた後、再度ダブルクリック → 新しいフレームが抽出される

---

### Test 2.5: 複数回の抽出

**手順:**
1. タイムライン上の3箇所をそれぞれダブルクリック (異なる位置)
2. 各抽出が独立して動作することを確認

**チェック項目:**
- [ ] 1回目: 0:02.0 付近をクリック → 正しく抽出
- [ ] 2回目: 0:05.0 付近をクリック → 正しく抽出
- [ ] 3回目: 0:07.0 付近をクリック → 正しく抽出
- [ ] 各抽出のタイムスタンプが異なる
- [ ] 各抽出のプレビュー画像が異なる

---

## 🧪 Test Suite 3: Performance Tests

### Test 3.1: メモリ使用量の比較

**Before (一括抽出):**
```bash
# 開発者ツール (F12) → Performance タブ → Memory
# 1. "Extract Frames" で 24fps × 8秒 = 192 フレーム抽出
# 2. メモリ使用量を記録

# Expected: 100MB〜200MB のメモリ増加
```

**After (On-Demand):**
```bash
# 1. ページリロード
# 2. 動画アップロード (フレーム抽出はスキップ)
# 3. タイムライン上で3回ダブルクリック (3フレームのみ抽出)
# 4. メモリ使用量を記録

# Expected: 5MB〜10MB のメモリ増加 (20倍以上の改善)
```

**チェック項目:**
- [ ] On-Demand のメモリ使用量が一括抽出の 1/10 以下

---

### Test 3.2: 初期ロード時間

```bash
# 開発者ツール (F12) → Network タブ

# Before (一括抽出):
# - "Extract Frames" ボタンクリック
# - すべてのフレームが読み込まれるまでの時間を記録
# Expected: 8秒動画で 10〜20秒

# After (On-Demand):
# - タイムラインダブルクリック
# - 1フレームが表示されるまでの時間を記録
# Expected: 1〜2秒
```

**チェック項目:**
- [ ] On-Demand の初期ロード時間が 1/10 以下

---

### Test 3.3: DOM 要素数

```bash
# 開発者ツール (F12) → Console で実行

# Before (一括抽出):
document.querySelectorAll('.liquid-frame').length
// Expected: 192 (8秒 × 24fps)

# After (On-Demand):
// タイムラインダブルクリック × 3回
// フレーム抽出は発生するが、DOM には追加されない
// Expected: タイムライン上のフレーム数は変わらない
```

**チェック項目:**
- [ ] On-Demand では DOM 要素数が増えない

---

## 🧪 Test Suite 4: Error Handling Tests

### Test 4.1: ネットワークエラー

**手順:**
1. 開発者ツール (F12) → Network タブ
2. "Offline" モードに設定
3. タイムラインをダブルクリック

**チェック項目:**
- [ ] エラーメッセージが表示される
- [ ] "Error extracting frame: Failed to fetch" などのメッセージ
- [ ] UI がフリーズしない

---

### Test 4.2: サーバーエラー (500)

**手順:**
1. Flask サーバーを一時停止
2. タイムラインをダブルクリック

**チェック項目:**
- [ ] エラーアラートが表示される
- [ ] ローディングスピナーが消える

---

### Test 4.3: 不正なタイムスタンプ

**手順:**
1. 開発者ツール (F12) → Console で実行:

```javascript
// 手動で不正なタイムスタンプで API を呼び出す
extractFrameAtTimestamp('uploads/local/session_xxx/video.mp4', -1.0);
```

**チェック項目:**
- [ ] "Invalid timestamp" エラーメッセージが表示される

---

## 🧪 Test Suite 5: Edge Cases

### Test 5.1: 非常に短い動画 (1秒)

**手順:**
1. 1秒の動画をアップロード
2. タイムラインをダブルクリック

**チェック項目:**
- [ ] 正常に動作する
- [ ] タイムスタンプが 0:00.0 〜 0:01.0 の範囲

---

### Test 5.2: 非常に長い動画 (60秒以上)

**手順:**
1. 60秒の動画をアップロード
2. タイムライン上の複数箇所をダブルクリック

**チェック項目:**
- [ ] 各クリックで正しいタイムスタンプが抽出される
- [ ] ブラウザがフリーズしない
- [ ] メモリ使用量が一定

---

### Test 5.3: 連続クリック (スパム防止)

**手順:**
1. タイムライン上で5回連続でダブルクリック (すぐに)

**チェック項目:**
- [ ] 各クリックが独立して処理される
- [ ] ローディング表示が重複しない
- [ ] 最終的に5つのフレームがすべて表示される

---

## 🧪 Test Suite 6: Browser Compatibility

### Test 6.1: Chrome

**チェック項目:**
- [ ] ダブルクリックイベントが正常に動作
- [ ] モーダル表示が正常
- [ ] Base64 画像が正常に表示

### Test 6.2: Firefox

**チェック項目:**
- [ ] ダブルクリックイベントが正常に動作
- [ ] モーダル表示が正常
- [ ] Base64 画像が正常に表示

### Test 6.3: Safari (Mac のみ)

**チェック項目:**
- [ ] ダブルクリックイベントが正常に動作
- [ ] モーダル表示が正常
- [ ] Base64 画像が正常に表示

---

## 📊 Test Results Summary

**テスト実行日:** `YYYY-MM-DD`
**テスト実行者:** `Your Name`

| Test Suite | Total | Passed | Failed | Notes |
|------------|-------|--------|--------|-------|
| Backend API | 9 | | | |
| Frontend Manual | 13 | | | |
| Performance | 3 | | | |
| Error Handling | 3 | | | |
| Edge Cases | 3 | | | |
| Browser Compatibility | 3 | | | |
| **TOTAL** | **34** | | | |

---

## 🐛 Known Issues

記録用:

| Issue ID | Description | Severity | Status |
|----------|-------------|----------|--------|
| | | | |

---

## 📝 Notes

テスト中に気づいた改善点やバグをここに記録:

```
例:
- タイムラインの端をクリックすると、タイムスタンプが若干ずれる
- モーダルのアニメーションが遅い
```

---

## ✅ Final Checklist

実装が production-ready かどうかの最終確認:

- [ ] すべてのテストが PASSED
- [ ] パフォーマンスが要件を満たしている (10倍以上の改善)
- [ ] エラーハンドリングが適切
- [ ] ブラウザ互換性が確認済み
- [ ] ドキュメントが更新済み
- [ ] コードレビューが完了
- [ ] ユーザーフィードバックを収集

---

## 🚀 Deployment Steps

テストが完了したら:

1. **メインブランチへマージ:**
   ```bash
   git checkout main
   git merge claude/evaluate-ui-performance-solutions-01YDyBLFArAqnvA6yzrAaG4V
   git push origin main
   ```

2. **本番環境へデプロイ:**
   ```bash
   # デプロイ手順をここに記載
   ```

3. **本番環境で Smoke Test:**
   - [ ] 動画アップロード
   - [ ] タイムラインダブルクリック
   - [ ] フレームプレビュー表示

---

**END OF TEST CHECKLIST**
