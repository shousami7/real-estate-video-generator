"""
Scene Manager - タイムライン・シーン管理システム

動画シーンのタイムライン管理、CRUD操作、永続化を提供します。
"""

import os
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    """
    シーン情報を表すデータクラス

    Attributes:
        scene_id: シーンの一意識別子（例: "scene1", "scene2"）
        video_path: ローカルファイルシステムの動画パス
        video_url: Supabaseなどの公開URL（オプション）
        duration: 動画の長さ（秒）
        prompt: 生成時のプロンプト
        created_at: 作成日時（ISO 8601形式）
        previous_scene_id: 前のシーンID（シーン拡張の場合）
        metadata: 追加メタデータ
    """
    scene_id: str
    video_path: str
    video_url: str
    duration: float
    prompt: str
    created_at: str
    previous_scene_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Scene':
        """辞書からSceneオブジェクトを生成"""
        return cls(**data)


class SceneManager:
    """
    タイムライン・シーン管理システム

    動画シーンの追加、取得、更新、削除を管理し、
    タイムラインをJSON形式でディスクに永続化します。

    使用例:
        manager = SceneManager(session_id="abc123")
        scene = manager.add_scene(
            scene_id="scene1",
            video_path="/path/to/video.mp4",
            video_url="https://...",
            duration=8.0,
            prompt="物件をゆっくりズームイン"
        )
        timeline = manager.get_all_scenes()
        total_duration = manager.get_timeline_duration()
    """

    def __init__(self, session_id: str, storage_dir: str = "output"):
        """
        SceneManagerを初期化

        Args:
            session_id: セッションID（ユーザーまたはプロジェクトごとに一意）
            storage_dir: タイムラインファイルを保存するルートディレクトリ
        """
        self.session_id = session_id
        self.storage_dir = storage_dir
        self.timeline: List[Scene] = []
        self._session_dir = os.path.join(storage_dir, session_id)
        self._timeline_file = os.path.join(self._session_dir, "timeline.json")

        # セッションディレクトリを作成
        os.makedirs(self._session_dir, exist_ok=True)

        # 既存のタイムラインを読み込み
        self._load_timeline()

        logger.info(
            f"SceneManager initialized: session_id={session_id}, "
            f"scenes_count={len(self.timeline)}"
        )

    def add_scene(
        self,
        scene_id: str,
        video_path: str,
        video_url: str,
        duration: float,
        prompt: str,
        previous_scene_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Scene:
        """
        新しいシーンをタイムラインに追加

        Args:
            scene_id: シーンID
            video_path: ローカル動画パス
            video_url: 公開URL
            duration: 動画の長さ（秒）
            prompt: 生成プロンプト
            previous_scene_id: 前のシーンID（オプション）
            metadata: 追加メタデータ（オプション）

        Returns:
            追加されたSceneオブジェクト

        Raises:
            ValueError: scene_idが既に存在する場合
        """
        # 重複チェック
        if self.get_scene(scene_id) is not None:
            raise ValueError(f"Scene ID already exists: {scene_id}")

        # Sceneオブジェクト作成
        scene = Scene(
            scene_id=scene_id,
            video_path=video_path,
            video_url=video_url,
            duration=duration,
            prompt=prompt,
            created_at=datetime.now().isoformat(),
            previous_scene_id=previous_scene_id,
            metadata=metadata or {}
        )

        # タイムラインに追加
        self.timeline.append(scene)

        # ディスクに保存
        self._save_timeline()

        logger.info(
            f"Scene added: {scene_id} (duration={duration}s, "
            f"total_scenes={len(self.timeline)})"
        )

        return scene

    def get_scene(self, scene_id: str) -> Optional[Scene]:
        """
        シーンIDでシーンを取得

        Args:
            scene_id: シーンID

        Returns:
            Sceneオブジェクト、存在しない場合はNone
        """
        for scene in self.timeline:
            if scene.scene_id == scene_id:
                return scene
        return None

    def get_scene_by_index(self, index: int) -> Optional[Scene]:
        """
        インデックスでシーンを取得

        Args:
            index: タイムライン内のインデックス（0始まり）

        Returns:
            Sceneオブジェクト、範囲外の場合はNone
        """
        if 0 <= index < len(self.timeline):
            return self.timeline[index]
        return None

    def get_last_scene(self) -> Optional[Scene]:
        """
        最後のシーンを取得

        Returns:
            最後のSceneオブジェクト、タイムラインが空の場合はNone
        """
        if self.timeline:
            return self.timeline[-1]
        return None

    def get_all_scenes(self) -> List[Scene]:
        """
        全シーンを取得

        Returns:
            Sceneオブジェクトのリスト
        """
        return self.timeline.copy()

    def update_scene(
        self,
        scene_id: str,
        video_path: Optional[str] = None,
        video_url: Optional[str] = None,
        duration: Optional[float] = None,
        prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        既存のシーンを更新

        Args:
            scene_id: シーンID
            video_path: 新しい動画パス（オプション）
            video_url: 新しい公開URL（オプション）
            duration: 新しい動画の長さ（オプション）
            prompt: 新しいプロンプト（オプション）
            metadata: 追加メタデータ（オプション）

        Returns:
            更新成功時はTrue、シーンが見つからない場合はFalse
        """
        scene = self.get_scene(scene_id)
        if scene is None:
            logger.warning(f"Scene not found for update: {scene_id}")
            return False

        # 更新
        if video_path is not None:
            scene.video_path = video_path
        if video_url is not None:
            scene.video_url = video_url
        if duration is not None:
            scene.duration = duration
        if prompt is not None:
            scene.prompt = prompt
        if metadata is not None:
            scene.metadata.update(metadata)

        # ディスクに保存
        self._save_timeline()

        logger.info(f"Scene updated: {scene_id}")
        return True

    def delete_scene(self, scene_id: str) -> bool:
        """
        シーンを削除

        Args:
            scene_id: シーンID

        Returns:
            削除成功時はTrue、シーンが見つからない場合はFalse
        """
        scene = self.get_scene(scene_id)
        if scene is None:
            logger.warning(f"Scene not found for deletion: {scene_id}")
            return False

        self.timeline.remove(scene)
        self._save_timeline()

        logger.info(f"Scene deleted: {scene_id}")
        return True

    def clear_timeline(self):
        """タイムライン全体をクリア"""
        self.timeline = []
        self._save_timeline()
        logger.info("Timeline cleared")

    def get_timeline_duration(self) -> float:
        """
        タイムライン全体の長さを取得

        Returns:
            総動画時間（秒）
        """
        return sum(scene.duration for scene in self.timeline)

    def get_scene_count(self) -> int:
        """
        シーン数を取得

        Returns:
            シーン数
        """
        return len(self.timeline)

    def generate_next_scene_id(self) -> str:
        """
        次のシーンIDを自動生成

        Returns:
            次のシーンID（例: "scene1", "scene2", ...）
        """
        next_index = len(self.timeline) + 1
        return f"scene{next_index}"

    def get_video_paths(self) -> List[str]:
        """
        全シーンの動画パスを取得

        Returns:
            動画パスのリスト
        """
        return [scene.video_path for scene in self.timeline]

    def get_video_urls(self) -> List[str]:
        """
        全シーンの動画URLを取得

        Returns:
            動画URLのリスト
        """
        return [scene.video_url for scene in self.timeline]

    def export_timeline(self) -> Dict[str, Any]:
        """
        タイムラインをエクスポート

        Returns:
            タイムライン情報を含む辞書
        """
        return {
            "session_id": self.session_id,
            "scene_count": len(self.timeline),
            "total_duration": self.get_timeline_duration(),
            "scenes": [scene.to_dict() for scene in self.timeline]
        }

    def _save_timeline(self):
        """タイムラインをディスクに保存（内部メソッド）"""
        try:
            with open(self._timeline_file, 'w', encoding='utf-8') as f:
                json.dump(
                    [scene.to_dict() for scene in self.timeline],
                    f,
                    ensure_ascii=False,
                    indent=2
                )
            logger.debug(f"Timeline saved: {self._timeline_file}")
        except Exception as e:
            logger.error(f"Failed to save timeline: {e}", exc_info=True)

    def _load_timeline(self):
        """タイムラインをディスクから読み込み（内部メソッド）"""
        if not os.path.exists(self._timeline_file):
            logger.debug("No existing timeline file found, starting fresh")
            return

        try:
            with open(self._timeline_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.timeline = [Scene.from_dict(item) for item in data]
            logger.info(f"Timeline loaded: {len(self.timeline)} scenes")
        except Exception as e:
            logger.error(f"Failed to load timeline: {e}", exc_info=True)
            self.timeline = []

    def get_timeline_summary(self) -> str:
        """
        タイムラインのサマリー文字列を取得

        Returns:
            サマリー文字列
        """
        if not self.timeline:
            return "タイムラインは空です"

        summary_lines = [
            f"タイムライン: {len(self.timeline)} シーン, 合計 {self.get_timeline_duration():.1f}秒",
            ""
        ]

        for i, scene in enumerate(self.timeline, 1):
            summary_lines.append(
                f"{i}. {scene.scene_id}: {scene.duration}秒 - {scene.prompt[:50]}..."
            )

        return "\n".join(summary_lines)

    def validate_timeline(self) -> tuple[bool, List[str]]:
        """
        タイムラインの整合性をバリデーション

        Returns:
            (is_valid, error_messages)
        """
        errors = []

        # シーンIDの重複チェック
        scene_ids = [scene.scene_id for scene in self.timeline]
        if len(scene_ids) != len(set(scene_ids)):
            errors.append("重複するシーンIDがあります")

        # 動画ファイルの存在チェック
        for scene in self.timeline:
            if not os.path.exists(scene.video_path):
                errors.append(f"動画ファイルが見つかりません: {scene.video_path}")

        # シーン拡張の連続性チェック
        for scene in self.timeline:
            if scene.previous_scene_id:
                prev_scene = self.get_scene(scene.previous_scene_id)
                if prev_scene is None:
                    errors.append(
                        f"前のシーンが見つかりません: {scene.scene_id} -> {scene.previous_scene_id}"
                    )

        is_valid = len(errors) == 0
        return is_valid, errors


# サンプル使用例（テスト用）
if __name__ == "__main__":
    # ロガー設定
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # テスト用のSceneManager
    manager = SceneManager(session_id="test_session_123", storage_dir="test_output")

    print("=" * 60)
    print("Scene Manager - Test")
    print("=" * 60)

    # タイムラインをクリア
    manager.clear_timeline()

    # シーン1を追加
    scene1 = manager.add_scene(
        scene_id="scene1",
        video_path="/path/to/scene1.mp4",
        video_url="https://example.com/scene1.mp4",
        duration=8.0,
        prompt="物件をゆっくりズームイン"
    )
    print(f"\n✓ Scene1 added: {scene1.scene_id}")

    # シーン2を追加（scene1の拡張）
    scene2 = manager.add_scene(
        scene_id="scene2",
        video_path="/path/to/scene2.mp4",
        video_url="https://example.com/scene2.mp4",
        duration=8.0,
        prompt="玄関のドアが開く",
        previous_scene_id="scene1"
    )
    print(f"✓ Scene2 added: {scene2.scene_id}")

    # シーン3を追加
    scene3 = manager.add_scene(
        scene_id="scene3",
        video_path="/path/to/scene3.mp4",
        video_url="https://example.com/scene3.mp4",
        duration=8.0,
        prompt="明るいリビングを見せる",
        previous_scene_id="scene2"
    )
    print(f"✓ Scene3 added: {scene3.scene_id}")

    # タイムライン情報を表示
    print("\n" + "=" * 60)
    print("Timeline Summary:")
    print("=" * 60)
    print(manager.get_timeline_summary())

    # タイムライン全体の長さ
    print(f"\n総動画時間: {manager.get_timeline_duration()}秒")

    # 全シーンの動画パス
    print(f"\n動画パス:")
    for path in manager.get_video_paths():
        print(f"  - {path}")

    # タイムラインのエクスポート
    print("\n" + "=" * 60)
    print("Timeline Export:")
    print("=" * 60)
    export_data = manager.export_timeline()
    print(json.dumps(export_data, indent=2, ensure_ascii=False))

    # バリデーション
    print("\n" + "=" * 60)
    print("Validation:")
    print("=" * 60)
    is_valid, errors = manager.validate_timeline()
    if is_valid:
        print("✓ Timeline is valid")
    else:
        print("✗ Timeline has errors:")
        for error in errors:
            print(f"  - {error}")

    print("\n" + "=" * 60)
