# ⚡ Quick Test Guide - On-Demand Frame Extraction

**5分でテストを完了！**

---

## 🚀 Step 1: サーバー起動 (3ターミナル)

```bash
# ターミナル 1: Redis
redis-server

# ターミナル 2: Celery
cd /home/user/real-estate-video-generator
celery -A tasks.celery worker --loglevel=info

# ターミナル 3: Flask
cd /home/user/real-estate-video-generator
python app.py
```

**確認:** ブラウザで http://localhost:5000/editor が開けるか確認

---

## 🧪 Step 2: Backend テスト (30秒)

```bash
# テスト用動画のパスを取得
# 例: uploads/local/session_xxx/video.mp4

# テスト実行
python test_frame_extraction.py uploads/local/session_xxx/video.mp4
```

**Expected output:**
```
🧪 On-Demand Frame Extraction - Quick Test
✅ Video duration: 8.00s
✅ Passed: 5/5 tests
🎉 All tests PASSED!
```

**❌ エラーが出た場合:**
- 動画パスが正しいか確認
- FFmpeg がインストールされているか確認: `ffmpeg -version`

---

## 🌐 Step 3: Frontend テスト (2分)

### 3.1 動画アップロード

1. ブラウザで http://localhost:5000/editor を開く
2. 動画をアップロード (8秒程度の短い動画推奨)
3. "Extract Frames" ボタンをクリック
4. タイムラインが表示されるまで待つ

### 3.2 タイムラインダブルクリックテスト

**テスト1: 開始位置**
1. タイムラインの**左端**をダブルクリック
2. ローディング表示が出る
3. フレームプレビューモーダルが表示される
4. タイムスタンプが **0:00.0 〜 0:01.0** であることを確認
5. "Close" ボタンでモーダルを閉じる

**テスト2: 中央位置**
1. タイムラインの**中央**をダブルクリック
2. タイムスタンプが動画の中間付近 (例: 8秒動画なら 0:04.0 付近) であることを確認
3. モーダルを閉じる

**テスト3: 終端位置**
1. タイムラインの**右端**をダブルクリック
2. タイムスタンプが動画の終端付近であることを確認
3. モーダルを閉じる

### 3.3 ブラウザコンソールテスト

1. 開発者ツールを開く (F12)
2. Console タブを開く
3. `BROWSER_TEST_SCRIPT.js` の内容をコピー
4. コンソールにペーストして Enter
5. 実行: `await runAllTests()`

**Expected output:**
```
🧪 On-Demand Frame Extraction - Browser Tests
✅ Test 1: API Endpoint
✅ Test 2: Timeline Click Calculation
✅ Test 3: Modal Display
✅ Test 4: extractFrameAtTimestamp Function
✅ Test 5: Memory Usage
📊 Test Summary
Passed: 5/5
🎉 All browser tests PASSED!
```

---

## 📊 Step 4: パフォーマンス確認 (1分)

### Before (一括抽出) vs After (On-Demand) の比較

1. 開発者ツール (F12) → **Network タブ**
2. ページをリロード
3. 動画をアップロード
4. "Extract Frames" をクリック

**Before の測定:**
- Network タブで転送量を確認
- 例: 192 フレーム × 50KB = **9.6 MB**

**After の測定:**
1. ページをリロード
2. 動画をアップロード (フレーム抽出はスキップ)
3. タイムラインを3回ダブルクリック

- Network タブで転送量を確認
- 例: 3 フレーム × 50KB = **150 KB** (64倍の改善！)

---

## ✅ 成功の基準

以下がすべて満たされていれば OK:

- [x] Backend テストが全て PASSED
- [x] タイムラインダブルクリックで正しいタイムスタンプが抽出される
- [x] ブラウザコンソールテストが全て PASSED
- [x] On-Demand の転送量が一括抽出の 1/10 以下

---

## 🐛 トラブルシューティング

### エラー: "Video not found"

**原因:** 動画パスが間違っている

**解決策:**
```bash
# uploads ディレクトリを確認
ls -la uploads/local/
ls -la uploads/local/session_*/
```

### エラー: "FFmpeg not found"

**原因:** FFmpeg がインストールされていない

**解決策:**
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# 確認
ffmpeg -version
```

### エラー: "Failed to fetch"

**原因:** Flask サーバーが起動していない

**解決策:**
```bash
# Flask サーバーを起動
python app.py

# 確認
curl http://localhost:5000/
```

### モーダルが表示されない

**原因:** JavaScript エラー

**解決策:**
1. 開発者ツール (F12) → Console タブを確認
2. エラーメッセージを確認
3. ページをリロード (Ctrl+Shift+R / Cmd+Shift+R)

---

## 📝 詳細テストが必要な場合

完全なテストチェックリストは以下を参照:
- **E2E_TEST_CHECKLIST.md** - 34個の詳細テスト項目

---

## 🚀 テストが成功したら

1. **メインブランチへマージ:**
   ```bash
   git checkout main
   git merge claude/evaluate-ui-performance-solutions-01YDyBLFArAqnvA6yzrAaG4V
   git push origin main
   ```

2. **本番環境へデプロイ**

3. **ユーザーフィードバックを収集**

---

**END OF QUICK TEST GUIDE**

---

## 📚 関連ドキュメント

- `E2E_TEST_CHECKLIST.md` - 完全なテストチェックリスト (34項目)
- `test_frame_extraction.py` - Backend テストスクリプト
- `BROWSER_TEST_SCRIPT.js` - ブラウザコンソールテストスクリプト
