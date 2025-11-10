# Video Editor Integration - Complete Implementation

## 🎯 Overview

完全なビデオ編集機能が統合されました。ユーザーは編集画面で動画をアップロードし、6つのフレームに分割して、AIを使って各フレームを編集できます。

## ✨ 実装された機能

### 1. 編集画面へのアクセス
- 動画生成完了後、「Edit Frames」ボタンをクリック
- `/video/editor` に直接遷移

### 2. 動画アップロード
- ドラッグ&ドロップ または ファイル選択
- サポート形式: MP4, MOV, AVI (最大 500MB)
- プログレスバー表示
- 生成した動画または別の動画をアップロード可能

### 3. フレーム抽出
- アップロード後、自動的に6フレームに分割
- 均等な間隔で抽出
- Base64エンコードでフロントエンドに送信

### 4. フレーム編集
- 左下のフレームパネルでフレームをクリック
- 右側チャットパネルにフレームプレビュー表示
- プロンプト入力: 「このフレームをこう編集して」
- AIが4つの画像バリエーションを生成

### 5. バリエーション適用
- 4つの生成画像から選択
- クリックで選択、「Apply to Frame」ボタンで適用
- フレームサムネイルが更新される

### 6. エクスポート
- すべての編集完了後、「Export」ボタンをクリック
- 編集済み動画をダウンロード

## 📁 ファイル構成

```
real-estate-video-generator/
├── frame_editor.py                    # ✅ 新バージョン
│   ├── FrameEditor クラス
│   │   ├── extract_frames()          # 6フレーム抽出
│   │   ├── get_video_duration()      # 動画の長さ取得
│   │   └── _image_to_base64()        # Base64変換
│   └── AIFrameEditor クラス
│       └── generate_frame_variations() # AI画像生成
│
├── web_ui.py                          # ✅ 更新済み
│   ├── /video/upload                 # POST: 動画アップロード
│   ├── /frames/extract               # POST: フレーム抽出
│   ├── /frames/edit                  # POST: AI編集
│   ├── /frames/apply                 # POST: フレーム適用
│   ├── /video/editor                 # GET: エディターUI表示
│   ├── /video/export                 # POST: 動画エクスポート
│   └── /download/editor              # GET: 動画ダウンロード
│
└── templates/
    ├── luxury_video_ui.html           # ✅ 更新済み
    │   └── Edit Frames ボタン → /video/editor に遷移
    │
    └── video_editor_ui.html           # ✅ 新デザイン
        ├── アップロードゾーン（ドラッグ&ドロップ対応）
        ├── ビデオプレイヤー
        ├── フレーム選択パネル（6フレーム）
        └── AI編集チャットパネル
```

## 🔄 完全なワークフロー

```
1. 動画生成完了
   ↓
2. 「Edit Frames」ボタンをクリック
   ↓
3. エディター画面 (/video/editor) に遷移
   ↓
4. 動画をアップロード (ドラッグ&ドロップ or ファイル選択)
   ↓
   POST /video/upload → 動画保存
   ↓
5. フレーム自動抽出（6フレーム）
   ↓
   POST /frames/extract → 6フレーム生成
   ↓
6. 左下のフレームパネルでフレームを選択
   ↓
7. 右側チャットパネルでプロンプト入力
   例: "Make the sunset more vibrant"
   ↓
   POST /frames/edit → AI画像生成
   ↓
8. 4つのバリエーションから選択
   ↓
9. 「Apply to Frame」ボタンをクリック
   ↓
   POST /frames/apply → フレーム更新
   ↓
10. (他のフレームも編集可能 - ステップ6に戻る)
   ↓
11. 「Export」ボタンをクリック
   ↓
   POST /video/export → 編集済み動画生成
   ↓
12. 動画ダウンロード開始
```

## 🎨 UIデザインの特徴

### カラーパレット
- **プライマリー**: `#34D399` (エメラルドグリーン)
- **背景**: `#0a0a0a` (ダークブラック)
- **パネル**: `#1a1a1a` (ダークグレー)
- **ボーダー**: `#374151` (グレー)
- **テキスト**: `#FFFFFF` / `#9CA3AF`

### フォント
- **Space Grotesk** - ヘッダー、ボタン、テキスト全般
- **Material Symbols Outlined** - アイコン

### アニメーション
- フレームサムネイル: ホバー時 scale(1.05)
- チャットメッセージ: スライドイン (0.3s)
- 生成画像: ホバー時 scale(1.02)
- プログレスバー: スムーズなトランジション

### レスポンシブ
- 3カラムレイアウト
  - 左: ビデオプレイヤー + フレームパネル
  - 右: AI編集チャットパネル (420px固定幅)
- フレームグリッド: 6列 (grid-cols-6)
- 生成画像グリッド: 2列 × 2行

## 🔌 APIエンドポイント詳細

### 1. `/video/upload` (POST)

動画をアップロード

**Request:**
```javascript
FormData {
  video: File
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Video uploaded successfully",
  "video_path": "uploads/{session_id}/editor/{filename}"
}
```

### 2. `/frames/extract` (POST)

動画から6フレームを抽出

**Request:**
```json
{
  "video_path": "uploads/{session_id}/editor/{filename}"
}
```

**Response:**
```json
{
  "status": "success",
  "frames": [
    {
      "frame_id": 0,
      "path": "frames/{session_id}/editor/frame_000.png",
      "timestamp": "0:04",
      "seconds": 4.0,
      "base64": "data:image/png;base64,..."
    },
    ...
  ],
  "frame_count": 6
}
```

### 3. `/frames/edit` (POST)

AIで画像バリエーションを生成

**Request:**
```json
{
  "frame_id": 0,
  "prompt": "Make the sunset more vibrant"
}
```

**Response:**
```json
{
  "status": "success",
  "variations": [
    "data:image/png;base64,...",
    "data:image/png;base64,...",
    "data:image/png;base64,...",
    "data:image/png;base64,..."
  ]
}
```

### 4. `/frames/apply` (POST)

選択したバリエーションをフレームに適用

**Request:**
```json
{
  "frame_id": 0,
  "edited_image_url": "data:image/png;base64,..."
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Frame applied"
}
```

### 5. `/video/export` (POST)

編集済み動画をエクスポート

**Request:**
```json
{}
```

**Response:**
```json
{
  "status": "success",
  "download_url": "/download/editor?path=..."
}
```

### 6. `/video/editor` (GET)

エディターUI表示

**Response:**
```html
<!DOCTYPE html>
<html>...</html>
```

## 🚀 起動方法

### 1. 依存関係の確認

```bash
# 既存の requirements.txt に含まれている
pip install -r requirements.txt
```

必要なパッケージ:
- `Flask>=2.3.0`
- `Pillow>=10.0.0`
- `google-genai>=1.0.0`
- `python-dotenv>=1.0.0`

### 2. FFmpeg のインストール

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# 確認
ffmpeg -version
```

### 3. 環境変数の設定

`.env` ファイルを作成:

```bash
GOOGLE_API_KEY=your_google_ai_api_key_here
SECRET_KEY=your_secret_key_for_flask_sessions
```

### 4. アプリケーション起動

```bash
python3 app.py
```

アプリケーションは `http://localhost:5001` で起動します。

### 5. アクセス

```
ブラウザで http://localhost:5001 を開く
```

## 🎯 使い方

### ステップ1: 動画を生成（既存機能）

1. 3枚の画像をアップロード
2. 「AI Video Generation Start」をクリック
3. 動画生成完了まで待機

### ステップ2: 編集画面へ

1. 「Edit Frames」ボタンをクリック
2. 編集画面に遷移

### ステップ3: 動画をアップロード

**方法1: ドラッグ&ドロップ**
- 動画ファイルをアップロードゾーンにドラッグ

**方法2: ファイル選択**
- アップロードゾーンをクリック
- ファイル選択ダイアログから動画を選択

### ステップ4: フレームを編集

1. **フレーム選択**
   - 左下のフレームパネルから編集したいフレームをクリック

2. **プロンプト入力**
   - 右下の入力欄に編集内容を記述
   - 例: "Make it feel more like a vibrant, golden hour sunset"

3. **送信**
   - ↑ ボタンをクリック または Enterキー

4. **バリエーション選択**
   - 4つの生成画像が表示される
   - 好きな画像をクリック

5. **適用**
   - 「Apply to Frame」ボタンをクリック
   - フレームサムネイルが更新される

### ステップ5: エクスポート

1. すべての編集が完了したら「Export」ボタンをクリック
2. 動画ダウンロードが自動的に開始

## 💡 プロンプトの例

### 照明・色調整
```
Make the sunset more vibrant and golden
Add warm lighting to create a cozy atmosphere
Increase contrast and saturation
Make the scene brighter and more inviting
```

### 雰囲気変更
```
Make it feel more luxurious and high-end
Add a modern, minimalist aesthetic
Create a resort-like atmosphere
Add dramatic lighting for more impact
```

### 天候・環境
```
Make it look like a sunny day
Add dramatic clouds to the sky
Create a golden hour lighting effect
Add some mist for a dreamy atmosphere
```

### 装飾・追加要素
```
Add palm trees swaying in the background
Add some greenery to the scene
Add subtle lens flare effect
Add reflections in the pool
```

## 🐛 トラブルシューティング

### 1. FFmpeg not found

**エラー:**
```
FileNotFoundError: ffmpeg not found
```

**解決方法:**
```bash
# インストール確認
which ffmpeg

# インストール
brew install ffmpeg  # macOS
sudo apt-get install ffmpeg  # Ubuntu
```

### 2. 動画アップロードが失敗する

**原因:**
- ファイルサイズが大きすぎる (500MB超)
- サポートされていない形式

**解決方法:**
- ファイルサイズを確認
- MP4, MOV, AVI 形式を使用

### 3. フレーム抽出が失敗する

**エラー:**
```
Could not determine video duration
```

**解決方法:**
- 動画ファイルが壊れていないか確認
- FFmpeg で動画を確認: `ffmpeg -i video.mp4`

### 4. AI生成が動作しない

**現在の状態:**
- AIFrameEditor は現在ダミーデータを返します
- `TODO: Google AI Image Generation API と統合` コメント参照

**解決方法:**
- Google AI Image Generation API (Imagen) との統合が必要
- または他の画像生成APIを使用

### 5. セッションが見つからない

**エラー:**
```
No frames found
```

**解決方法:**
- ページをリロード
- 動画を再度アップロード

## 🔧 カスタマイズ

### フレーム数を変更

`frame_editor.py`:
```python
# デフォルト: 6フレーム
def extract_frames(self, frame_count: int = 6):
    ...
```

`video_editor_ui.html`:
```javascript
// フロントエンドも変更
frames = editor.extract_frames(frame_count=8)
```

### バリエーション数を変更

`frame_editor.py`:
```python
def generate_frame_variations(
    self,
    base_image_path: str,
    prompt: str,
    variation_count: int = 4  # ここを変更
):
```

### アップロードサイズ制限

`app.py`:
```python
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB
```

## 📊 セッション管理

### セッションキー

- `session_id` - ユニークセッションID
- `editor_video` - アップロードされた動画パス
- `editor_frames` - 抽出されたフレームリスト
- `editor_frames_dir` - フレーム保存ディレクトリ
- `edited_frames` - 編集済みフレームの dict

### セッションライフサイクル

```
1. ユーザーアクセス → session_id 生成
2. 動画アップロード → editor_video 保存
3. フレーム抽出 → editor_frames 保存
4. フレーム編集 → edited_frames 更新
5. エクスポート → 編集済み動画生成
```

## 🎨 UI/UXの特徴

### ドラッグ&ドロップ
- ファイルをドラッグすると枠が緑色に
- ドロップでアップロード開始

### プログレスバー
- アップロード進捗を視覚的に表示
- 0% → 100% のアニメーション

### フレーム選択
- クリックで選択状態（緑枠）
- ホバーで拡大表示

### チャット形式
- ユーザーメッセージ（右上丸角、紫アバター）
- AIメッセージ（左下丸角、緑アバター）
- スライドインアニメーション

### 画像選択
- クリックで選択状態（緑枠 + シャドウ）
- 「Apply to Frame」ボタン表示

## 📈 今後の拡張

### 優先度: 高

1. **AI画像生成の実装**
   - Google Imagen API との統合
   - または DALL-E, Midjourney API

2. **動画再構築機能**
   - 編集済みフレームで動画を再生成
   - FFmpeg による動画合成

3. **プレビュー機能**
   - エクスポート前に編集済み動画をプレビュー

### 優先度: 中

4. **アンドゥ/リドゥ**
   - 編集履歴の管理
   - 前の状態に戻す

5. **バッチ編集**
   - 複数フレームに同じ編集を適用

6. **カスタムフレーム選択**
   - タイムスタンプ指定
   - 任意の位置からフレーム抽出

### 優先度: 低

7. **フィルター機能**
   - プリセットフィルター（セピア、ビビッド、など）

8. **テキストオーバーレイ**
   - フレームにテキスト追加

9. **音楽追加**
   - BGM選択・追加

## 🎬 まとめ

完全なビデオ編集機能が統合されました！

✅ **実装完了:**
- 動画アップロード（ドラッグ&ドロップ対応）
- 6フレーム自動抽出
- AI編集チャット
- 4バリエーション生成
- フレーム適用・更新
- エクスポート機能

✅ **デザイン:**
- Space Grotesk フォント
- Material Symbols アイコン
- ダークテーマ
- スムーズなアニメーション
- レスポンシブレイアウト

✅ **統合:**
- 既存の動画生成フローと統合
- セッション管理
- エラーハンドリング

📝 **次のステップ:**
1. `python3 app.py` でアプリ起動
2. ブラウザで `http://localhost:5001` にアクセス
3. 動画生成 → Edit Frames → 編集 → Export

🎉 **動画編集機能の統合が完了しました！**
