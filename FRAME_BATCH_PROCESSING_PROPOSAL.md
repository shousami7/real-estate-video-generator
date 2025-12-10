# Frame Batch Processing Implementation Proposal

## 現状の問題点

1. **フロントエンド**: 1フレームのみ送信（複数選択UI未実装）
2. **バックエンド**: 順次処理（Sequential Processing）で並列化されていない
3. **進捗表示**: バッチ処理の進捗がユーザーに見えない
4. **AI処理**: ダミー実装のため実際のパフォーマンス測定不可

## 実装案

### 案1: クライアント側並列処理（シンプル実装）

**特徴**: フロントエンドで複数フレームを選択し、並列リクエストを送信

#### フロントエンド変更

```javascript
// carousel_view.html

// 状態にフレーム選択機能を追加
const state = {
    frames: [],
    currentIndex: 0,
    selectedFrames: new Set(), // 選択されたフレームのインデックス
    isMultiSelectMode: false
};

// マルチ選択モードの切り替え
function toggleMultiSelectMode() {
    state.isMultiSelectMode = !state.isMultiSelectMode;
    state.selectedFrames.clear();
    renderTimeline(); // UIを更新
}

// フレームの選択/選択解除
function toggleFrameSelection(index) {
    if (!state.isMultiSelectMode) return;

    if (state.selectedFrames.has(index)) {
        state.selectedFrames.delete(index);
    } else {
        state.selectedFrames.add(index);
    }
    renderTimeline();
}

// バッチ編集処理（並列リクエスト）
async function handleBatchEditFrames() {
    const framesToEdit = state.isMultiSelectMode
        ? Array.from(state.selectedFrames).map(i => state.frames[i])
        : [state.frames[state.currentIndex]];

    const model = document.getElementById('model-select').value;
    const prompt = document.getElementById('edit-prompt').value.trim();

    // 進捗モーダル表示
    showProgressModal(framesToEdit.length);

    // 並列処理（Promise.all）
    const editPromises = framesToEdit.map((frame, idx) =>
        editSingleFrame(frame, model, prompt, idx)
    );

    try {
        const results = await Promise.all(editPromises);
        handleBatchResults(results);
    } catch (error) {
        console.error('Batch edit error:', error);
    } finally {
        closeProgressModal();
    }
}

// 単一フレーム編集（個別リクエスト）
async function editSingleFrame(frame, model, prompt, index) {
    updateProgress(index, 'processing');

    try {
        const response = await fetch('/frames/edit-with-ai', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                frames: [{
                    path: frame.path,
                    url: frame.src,
                    frame_number: frame.frame_number
                }],
                model,
                prompt
            })
        });

        const result = await response.json();
        updateProgress(index, 'success');
        return { frame, result, success: true };
    } catch (error) {
        updateProgress(index, 'error');
        return { frame, error, success: false };
    }
}
```

**メリット**:
- 実装がシンプル
- 既存のバックエンドAPIをそのまま利用可能
- ブラウザが並列処理を自動管理

**デメリット**:
- 大量のフレーム（50+）では同時接続数の制限に引っかかる可能性
- サーバー負荷が高い（各リクエストが独立）
- ネットワーク帯域を多く消費

---

### 案2: サーバー側並列処理（推奨）

**特徴**: バックエンドで非同期並列処理を実装し、効率的に処理

#### バックエンド変更

```python
# web_ui.py

import asyncio
from concurrent.futures import ThreadPoolExecutor
import aiohttp

@web_ui_blueprint.route('/frames/edit-with-ai', methods=['POST'])
def edit_frames_with_ai():
    """
    複数フレームをバッチ編集（並列処理）
    """
    data = request.get_json()
    frames = data.get('frames', [])
    model = data.get('model', 'nanobanana-pro')
    prompt = data.get('prompt', '')
    batch_size = data.get('batch_size', 4)  # 並列処理数

    # バッチ処理を実行
    results = process_frames_in_batches(frames, model, prompt, batch_size)

    successful_edits = sum(1 for r in results if r['success'])
    failed_edits = sum(1 for r in results if not r['success'])

    return jsonify({
        "status": "success" if successful_edits > 0 else "error",
        "message": f"Edited {successful_edits} frames, {failed_edits} failed",
        "results": results,
        "successful_edits": successful_edits,
        "failed_edits": failed_edits
    })


def process_frames_in_batches(frames, model, prompt, batch_size=4):
    """
    フレームをバッチで並列処理

    Args:
        frames: 処理するフレームのリスト
        model: 使用するAIモデル
        prompt: 編集プロンプト
        batch_size: 並列処理するフレーム数（デフォルト: 4）

    Returns:
        各フレームの処理結果のリスト
    """
    results = []
    api_key = os.getenv("GOOGLE_API_KEY")
    ai_editor = AIFrameEditor(api_key=api_key)

    session_id = session.get('session_id', str(uuid.uuid4()))
    edited_frames_dir = os.path.join('frames', session_id, 'ai_edited')
    os.makedirs(edited_frames_dir, exist_ok=True)

    # ThreadPoolExecutorで並列処理
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        futures = []

        for frame in frames:
            future = executor.submit(
                process_single_frame,
                frame,
                ai_editor,
                model,
                prompt,
                edited_frames_dir
            )
            futures.append((frame, future))

        # 結果を収集
        for frame, future in futures:
            try:
                result = future.result(timeout=60)  # 60秒タイムアウト
                results.append(result)
            except Exception as e:
                logger.error(f"Frame processing failed: {e}")
                results.append({
                    'success': False,
                    'frame_number': frame.get('frame_number', -1),
                    'error': str(e)
                })

    return results


def process_single_frame(frame, ai_editor, model, prompt, output_dir):
    """
    単一フレームを処理（スレッドセーフ）
    """
    try:
        frame_path = frame.get('path')
        frame_number = frame.get('frame_number', 0)

        if not frame_path or not os.path.exists(frame_path):
            raise ValueError(f"Invalid frame path: {frame_path}")

        # AI編集処理
        variations = ai_editor.generate_frame_variations(
            base_image_path=frame_path,
            prompt=prompt,
            variation_count=1
        )

        if not variations or len(variations) == 0:
            raise ValueError("No variations generated")

        # 保存処理
        variation_data = variations[0]
        if variation_data.startswith('data:image'):
            base64_str = variation_data.split(',')[1]
            image_data = base64.b64decode(base64_str)

            timestamp = int(datetime.now().timestamp())
            edited_filename = f"edited_frame_{frame_number}_{timestamp}.png"
            edited_path = os.path.join(output_dir, edited_filename)

            with open(edited_path, 'wb') as f:
                f.write(image_data)

            # URL生成
            frames_root = os.path.abspath('frames')
            normalized_path = os.path.abspath(edited_path)
            relative_path = os.path.relpath(normalized_path, frames_root)
            edited_url = url_for('web_ui.serve_frame', filename=relative_path)

            return {
                'success': True,
                'frame_number': frame_number,
                'path': edited_path,
                'url': edited_url
            }
        else:
            raise ValueError("Invalid variation data format")

    except Exception as e:
        logger.error(f"Error processing frame {frame.get('frame_number')}: {e}")
        return {
            'success': False,
            'frame_number': frame.get('frame_number', -1),
            'error': str(e)
        }
```

**メリット**:
- サーバー側で並列度を制御可能（リソース管理）
- ネットワークオーバーヘッドが少ない（1リクエスト）
- 大量フレーム処理に適している

**デメリット**:
- サーバー側のリソース（CPU/メモリ）を消費
- タイムアウト管理が必要

---

### 案3: Celeryタスクキュー（スケーラブル）

**特徴**: 非同期タスクキューで処理し、リアルタイム進捗をWebSocketで通知

#### バックエンド実装

```python
# tasks.py（既存のCeleryアプリに追加）

from celery import group, chord

@celery.task(bind=True)
def edit_single_frame_task(self, frame_data, model, prompt, session_id):
    """
    単一フレーム編集タスク（Celeryタスク）
    """
    try:
        # 進捗更新
        self.update_state(state='PROGRESS', meta={'status': 'processing'})

        # AI編集処理
        ai_editor = AIFrameEditor()
        frame_path = frame_data['path']

        variations = ai_editor.generate_frame_variations(
            base_image_path=frame_path,
            prompt=prompt,
            variation_count=1
        )

        # 保存処理
        edited_frames_dir = os.path.join('frames', session_id, 'ai_edited')
        os.makedirs(edited_frames_dir, exist_ok=True)

        # ... 保存ロジック ...

        return {
            'success': True,
            'frame_number': frame_data['frame_number'],
            'edited_url': edited_url
        }

    except Exception as e:
        logger.error(f"Task failed: {e}")
        return {'success': False, 'error': str(e)}


@celery.task
def batch_edit_complete(results):
    """
    バッチ編集完了時のコールバック
    """
    successful = sum(1 for r in results if r.get('success'))
    logger.info(f"Batch edit complete: {successful}/{len(results)} succeeded")
    return results


@web_ui_blueprint.route('/frames/edit-batch', methods=['POST'])
def edit_frames_batch():
    """
    バッチ編集タスクを投入（非同期）
    """
    data = request.get_json()
    frames = data.get('frames', [])
    model = data.get('model')
    prompt = data.get('prompt')
    session_id = session.get('session_id', str(uuid.uuid4()))

    # Celeryタスクグループを作成
    task_group = group(
        edit_single_frame_task.s(frame, model, prompt, session_id)
        for frame in frames
    )

    # タスクを実行（並列）
    job = task_group.apply_async()

    return jsonify({
        'status': 'processing',
        'job_id': job.id,
        'total_frames': len(frames)
    })


@web_ui_blueprint.route('/frames/edit-batch/status/<job_id>', methods=['GET'])
def get_batch_status(job_id):
    """
    バッチ編集の進捗を取得
    """
    from celery.result import GroupResult

    job = GroupResult.restore(job_id)

    if not job:
        return jsonify({'error': 'Job not found'}), 404

    completed = sum(1 for r in job.results if r.ready())
    total = len(job.results)

    return jsonify({
        'total': total,
        'completed': completed,
        'progress': (completed / total) * 100 if total > 0 else 0,
        'ready': job.ready(),
        'successful': job.successful() if job.ready() else None
    })
```

#### フロントエンド（進捗ポーリング）

```javascript
// バッチ編集開始
async function startBatchEdit(frames, model, prompt) {
    const response = await fetch('/frames/edit-batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ frames, model, prompt })
    });

    const { job_id, total_frames } = await response.json();

    // 進捗をポーリング
    pollBatchProgress(job_id, total_frames);
}

async function pollBatchProgress(jobId, totalFrames) {
    const interval = setInterval(async () => {
        const response = await fetch(`/frames/edit-batch/status/${jobId}`);
        const status = await response.json();

        // 進捗バーを更新
        updateProgressBar(status.completed, status.total);

        if (status.ready) {
            clearInterval(interval);
            handleBatchComplete(jobId);
        }
    }, 1000); // 1秒ごとにポーリング
}
```

**メリット**:
- 最も堅牢でスケーラブル
- 長時間処理に対応
- タスクの再試行・優先度管理が可能
- 進捗のリアルタイム追跡

**デメリット**:
- 実装が複雑
- Celery・Redisのインフラが必要（既に利用中）
- オーバーエンジニアリングの可能性

---

## 推奨実装

### フェーズ1: サーバー側並列処理（案2）

**理由**:
1. バランスが良い（実装コスト vs パフォーマンス）
2. 既存インフラで実現可能
3. 10-20フレーム程度のバッチ処理に十分対応

**実装順序**:
1. フロントエンド: マルチ選択UI追加
2. バックエンド: ThreadPoolExecutorで並列処理実装
3. 進捗表示: シンプルなプログレスバー

### フェーズ2: Celeryタスクキュー（案3）※必要に応じて

**条件**:
- ユーザーが50+フレームを編集するユースケースが発生した場合
- リアルタイム進捗が重要になった場合

---

## UI設計案

### マルチ選択モード

```
┌─────────────────────────────────────────────────┐
│ Frame Timeline                    [Multi-Select] │
│                                                   │
│  ┌──┐  ┌──┐  ┌──┐  ┌──┐                        │
│  │✓1│  │ 2│  │✓3│  │ 4│  ...                   │
│  └──┘  └──┘  └──┘  └──┘                        │
│                                                   │
│  Selected: 2 frames                               │
│  [Edit Selected Frames]                           │
└─────────────────────────────────────────────────┘
```

### 進捗モーダル

```
┌─────────────────────────────────────┐
│  Editing Frames...                  │
│                                     │
│  ████████░░░░  8 / 10 (80%)        │
│                                     │
│  ✓ Frame 1 - Success               │
│  ✓ Frame 3 - Success               │
│  ⚠ Frame 5 - Failed (retry...)     │
│  ⏳ Frame 7 - Processing...         │
│                                     │
│  [Cancel]                           │
└─────────────────────────────────────┘
```

---

## パフォーマンス見積もり

### 現状（順次処理）
- 1フレーム編集: 5秒（AI処理時間）
- 10フレーム: 50秒

### 案2実装後（並列4スレッド）
- 10フレーム: 12.5秒（4倍高速化）

### 案3実装後（Celeryワーカー8台）
- 10フレーム: 6.25秒（8倍高速化）

---

## 実装チェックリスト

### フロントエンド
- [ ] マルチ選択モードUI
- [ ] フレーム選択/選択解除ロジック
- [ ] 選択フレームのビジュアル表示
- [ ] バッチ編集モーダル
- [ ] 進捗表示（プログレスバー）
- [ ] エラーハンドリング（個別フレーム失敗）

### バックエンド
- [ ] ThreadPoolExecutor並列処理
- [ ] batch_size設定（動的調整）
- [ ] タイムアウト処理
- [ ] エラーハンドリング（スレッドセーフ）
- [ ] ログ記録（成功/失敗）

### テスト
- [ ] 1フレーム編集（従来通り動作）
- [ ] 5フレームバッチ編集
- [ ] 20フレームバッチ編集
- [ ] エラーケース（一部失敗）
- [ ] パフォーマンステスト

---

## 次のステップ

1. **案2の実装を開始**（推奨）
2. プロトタイプを作成して効果測定
3. ユーザーフィードバックを収集
4. 必要に応じて案3へ移行
