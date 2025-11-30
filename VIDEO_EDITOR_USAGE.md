# Video Editor - Usage Guide

## 🎬 概要

アップロードした動画をAIでフレーム編集できる機能のガイドです。トップページから直接エディターに遷移し、その場で動画をアップロードして編集できます。

## ✨ 機能

1. **フレーム抽出** - 動画から6つのフレームを自動抽出
2. **AIによる編集** - チャットでフレームの編集内容を記述
3. **バリエーション生成** - AIが4つの画像バリエーションを生成
4. **フレーム適用** - 好きなバリエーションを選択して適用
5. **動画エクスポート** - 編集済みフレームで動画を再構築

## 📋 使い方

### ステップ1: 動画をアップロード

1. ブラウザで `/video/editor` にアクセス（トップページから自動リダイレクト）
2. 画面中央のアップロードゾーンに動画をドラッグ&ドロップ、または「Upload」ボタンをクリックしてファイルを選択
3. アップロードが完了すると自動的に6フレームが抽出されます

### ステップ2: フレームを編集

1. **フレームを選択**
   - 中央のグリッドから編集したいフレームをクリック
   - 右側パネルにプレビューが表示されます

2. **編集内容を入力**
   - 右下の入力欄に編集内容を日本語または英語で記述
   - 例: 「夕焼けをもっと鮮やかにして」
   - 例: "Make the sunset more vibrant with golden hour lighting"

3. **バリエーション生成**
   - 送信ボタン（↑）をクリック
   - AIが4つのバリエーションを生成します（数秒かかります）

4. **バリエーションを選択**
   - 生成された4つの画像から好きなものをクリック
   - 選択したバリエーションがフレームに適用されます
   - フレームに「✓ Edited」バッジが表示されます

5. **他のフレームも編集**
   - ステップ1-4を繰り返して、他のフレームも編集できます
   - 編集したくないフレームはそのままでOK

### ステップ3: 動画をエクスポート

1. すべての編集が完了したら、右上の**「Export Video」**ボタンをクリック
2. 編集済みフレームで動画が再構築されます（時間がかかる場合があります）
3. 自動的にダウンロードが開始されます

### ステップ4: 別の動画を編集する

- 右上の**「Back」**ボタンでアップロード画面に戻り、別の動画を選べます

## 🎨 編集プロンプトの例

### 照明・色調整
```
夕焼けをもっと鮮やかにして
Make the lighting warmer and more inviting
Add more contrast and saturation
暗い部分を明るくして
```

### 雰囲気変更
```
もっと高級感のある雰囲気にして
Make it feel more luxurious and elegant
Add a modern, minimalist aesthetic
リゾート風の雰囲気を追加して
```

### 天候・環境
```
晴れた日の雰囲気にして
Add dramatic clouds to the sky
Make it look like golden hour
雨上がりの雰囲気にして
```

### 装飾・追加要素
```
ヤシの木を追加して
Add some potted plants in the foreground
もっと緑を増やして
Add subtle lens flare effect
```

## 🔧 技術仕様

### システム要件

- **Python 3.8+**
- **FFmpeg** (動画処理に必要)
- **Google AI API Key** (AI画像生成に必要)

### ディレクトリ構造

```
real-estate-video-generator/
├── frame_editor.py           # フレーム編集ロジック
├── web_ui.py                 # Flaskエンドポイント
├── templates/
│   └── video_editor_ui.html  # エディターUI (/video/editor)
├── frames/                   # 抽出されたフレーム
│   └── <session_id>/
│       ├── <video_name>_<timestamp>/
│       │   ├── frame_000.png
│       │   ├── frame_001.png
│       │   ├── ...
│       │   └── metadata.json
└── output/                   # 生成された動画
    └── <session_id>/
        ├── final_property_video.mp4
        └── final_property_video_edited.mp4
```

### メタデータファイル

フレーム情報は `metadata.json` に保存されます：

```json
{
  "video_path": "output/.../final_property_video.mp4",
  "video_info": {
    "width": 1280,
    "height": 720,
    "fps": 30.0,
    "duration": 24.0
  },
  "frames": {
    "frame_000": {
      "frame_id": "frame_000",
      "frame_path": "frames/.../frame_000.png",
      "timestamp": 4.0,
      "frame_number": 0,
      "original": true,
      "edited": false,
      "edit_history": []
    }
  }
}
```

## 🚀 起動方法

### 1. 環境変数の設定

`.env` ファイルに Vertex 用の情報を設定：

```bash
GOOGLE_CLOUD_PROJECT=your_gcp_project_id
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json  # または gcloud auth application-default login
SECRET_KEY=your_secret_key_here
```

### 2. アプリケーション起動

```bash
python3 app.py
```

アプリケーションは `http://localhost:5001` で起動します。

### 3. ブラウザでアクセス

```
http://localhost:5001
```

## 🐛 トラブルシューティング

### FFmpegがインストールされていない

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt-get install ffmpeg
```

**Windows:**
1. https://ffmpeg.org/download.html からダウンロード
2. PATH に追加

### フレーム抽出が失敗する

- 動画ファイルが存在するか確認
- FFmpegがインストールされているか確認: `ffmpeg -version`
- ディスク容量を確認

### AI生成がエラーになる

- `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` が設定され、ADC/サービスアカウントが有効か確認
- Vertex AIのクォータ制限を確認
- ネットワーク接続を確認

### 動画エクスポートが失敗する

- 編集済みフレームが存在するか確認
- ディスク容量を確認
- FFmpegのバージョンを確認: `ffmpeg -version`

### アーキテクチャエラー (arm64/x86_64)

**Apple Silicon Mac の場合:**
```bash
# arm64 ネイティブの Python を使用
arch -arm64 python3 app.py
```

または、仮想環境を再作成：
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## 📝 API エンドポイント

すべてのエンドポイントの詳細は `VIDEO_EDITOR_INTEGRATION.md` を参照してください。

### 主要エンドポイント

- `POST /frames/extract` - フレーム抽出
- `GET /frames/list` - フレーム一覧取得
- `GET /frames/image/<frame_id>` - フレーム画像取得
- `POST /frames/edit` - AI バリエーション生成
- `POST /frames/apply` - フレーム適用
- `POST /video/export` - 動画エクスポート
- `GET /video/editor` - エディターUI表示

## 💡 ヒント

1. **複数のフレームを編集**: 1つずつ編集するか、まとめて編集するか選べます
2. **編集履歴**: 各フレームの編集履歴は保存されます
3. **元に戻す**: 現在のバージョンでは未実装（将来的に追加予定）
4. **プレビュー**: 各フレームのプレビューは即座に更新されます
5. **バリエーション保存**: 選択しなかったバリエーションは保存されません

## 🎯 今後の機能追加予定

- [ ] アンドゥ/リドゥ機能
- [ ] バッチ編集（複数フレームに同じ編集を適用）
- [ ] カスタムフレーム選択（タイムスタンプ指定）
- [ ] プレビュー動画生成
- [ ] 色補正ツール
- [ ] テキストオーバーレイ
- [ ] バックグラウンド処理
- [ ] 進捗表示の改善

## 📞 サポート

問題が発生した場合は、以下を確認してください：

1. `VIDEO_EDITOR_INTEGRATION.md` - 詳細な技術仕様
2. ログファイル - コンソール出力を確認
3. システム要件 - FFmpeg、Python、依存関係

## 🎉 完了！

これで動画編集機能の使い方の説明は終わりです。
素晴らしい不動産プロモーション動画を作成してください！
