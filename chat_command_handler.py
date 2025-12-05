"""
Chat Command Handler - 自然言語コマンド解釈エンジン

ユーザーのチャット入力を解析して、適切なビデオ編集コマンドにルーティングします。
"""

import re
import logging
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class CommandIntent(Enum):
    """コマンドインテント（意図）"""
    CREATE = "create"           # 新しい動画を作る
    EXTEND = "extend"           # シーンを追加
    TRANSITION = "transition"   # 動画を繋げる
    FRAME_EDIT = "frame_edit"   # フレーム編集
    ADJUST = "adjust"           # 画像をフレームに挿入
    UNKNOWN = "unknown"         # 不明なコマンド


class ChatCommandHandler:
    """
    自然言語をコマンドに変換するハンドラー

    使用例:
        handler = ChatCommandHandler()
        command = handler.parse_command("この画像から8秒の動画を作って")
        # => {
        #     "intent": CommandIntent.CREATE,
        #     "params": {
        #         "duration": "8s",
        #         "prompt": "この画像から8秒の動画を作って"
        #     }
        # }
    """

    # インテント分類用のキーワードパターン
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

    def __init__(self):
        """コマンドハンドラーを初期化"""
        logger.info("ChatCommandHandler initialized")

    def parse_command(self, user_input: str) -> Dict[str, Any]:
        """
        ユーザー入力を解析してコマンドに変換

        Args:
            user_input: ユーザーのチャット入力（自然言語）

        Returns:
            {
                "intent": CommandIntent,
                "params": {
                    "image_path": str,
                    "prompt": str,
                    "duration": str,
                    ...
                },
                "original_input": str
            }
        """
        logger.info(f"Parsing command: {user_input}")

        intent = self._classify_intent(user_input)
        params = self._extract_parameters(user_input, intent)

        result = {
            "intent": intent,
            "params": params,
            "original_input": user_input
        }

        logger.info(f"Parsed command: intent={intent.value}, params={params}")
        return result

    def _classify_intent(self, text: str) -> CommandIntent:
        """
        インテント分類

        Args:
            text: ユーザー入力テキスト

        Returns:
            CommandIntent: 分類されたインテント
        """
        # 各インテントパターンをチェック
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    logger.debug(f"Intent matched: {intent.value} (pattern: {pattern})")
                    return intent

        # マッチしない場合はUNKNOWN
        logger.warning(f"No intent matched for: {text}")
        return CommandIntent.UNKNOWN

    def _extract_parameters(
        self,
        text: str,
        intent: CommandIntent
    ) -> Dict[str, Any]:
        """
        パラメータ抽出

        Args:
            text: ユーザー入力テキスト
            intent: 分類されたインテント

        Returns:
            抽出されたパラメータ辞書
        """
        params = {}

        # 1. 秒数抽出: "8秒", "10s", "5 seconds" など
        duration_match = re.search(r'(\d+)\s*[秒s]', text)
        if duration_match:
            params['duration'] = f"{duration_match.group(1)}s"
            logger.debug(f"Duration extracted: {params['duration']}")
        else:
            params['duration'] = "8s"  # デフォルト8秒

        # 2. 画像パス抽出: "image1.jpg", "IMG_001.png", "外観.jpg" など
        # 一般的な画像ファイル拡張子をサポート
        image_patterns = [
            r'([a-zA-Z0-9_\-\.ぁ-んァ-ヶー一-龠]+\.(jpg|jpeg|png|webp|gif))',
            r'file://([^\s]+)',
            r'uploaded:([^\s]+)'
        ]

        for pattern in image_patterns:
            image_match = re.search(pattern, text, re.IGNORECASE)
            if image_match:
                params['image_path'] = image_match.group(1)
                logger.debug(f"Image path extracted: {params['image_path']}")
                break

        # 3. トランジションタイプ: "フェード", "fade", "ワイプ" など
        transition_keywords = {
            'fade': ['フェード', 'fade', 'dissolve'],
            'wipeleft': ['左ワイプ', 'wipe left', 'wipeleft'],
            'wiperight': ['右ワイプ', 'wipe right', 'wiperight'],
            'cut': ['カット', 'cut', 'そのまま']
        }

        for transition_type, keywords in transition_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text.lower():
                    params['transition_type'] = transition_type
                    logger.debug(f"Transition type extracted: {transition_type}")
                    break
            if 'transition_type' in params:
                break

        # デフォルトはカット（単純連結）
        if 'transition_type' not in params:
            params['transition_type'] = 'cut'

        # 4. タイムスタンプ抽出: "3秒目", "5秒の部分", "at 2.5s" など
        timestamp_patterns = [
            r'(\d+(?:\.\d+)?)\s*秒目',
            r'at\s+(\d+(?:\.\d+)?)\s*s',
            r'(\d+(?:\.\d+)?)\s*秒.*部分'
        ]

        for pattern in timestamp_patterns:
            timestamp_match = re.search(pattern, text)
            if timestamp_match:
                params['timestamp'] = float(timestamp_match.group(1))
                logger.debug(f"Timestamp extracted: {params['timestamp']}")
                break

        # 5. シーンID: "Scene1", "scene2", "シーン3" など
        scene_patterns = [
            r'[Ss]cene\s*(\d+)',
            r'シーン\s*(\d+)'
        ]

        for pattern in scene_patterns:
            scene_match = re.search(pattern, text)
            if scene_match:
                params['scene_id'] = f"scene{scene_match.group(1)}"
                logger.debug(f"Scene ID extracted: {params['scene_id']}")
                break

        # 6. プロンプト（AIへの指示）
        # クリーニング: コマンド固有のキーワードを除去してプロンプトを抽出
        prompt = text

        # 不要なキーワードを削除
        cleanup_patterns = [
            r'動画.*作って',
            r'シーン.*追加',
            r'繋げて',
            r'編集して',
            r'\d+秒',
            r'から',
            r'について'
        ]

        for pattern in cleanup_patterns:
            prompt = re.sub(pattern, '', prompt, flags=re.IGNORECASE)

        # 余分な空白を削除
        prompt = ' '.join(prompt.split()).strip()

        # プロンプトが空の場合は元のテキストを使用
        if not prompt:
            prompt = text

        params['prompt'] = prompt

        # 7. アスペクト比: "16:9", "9:16", "縦", "横" など
        aspect_ratio_keywords = {
            '16:9': ['16:9', '横', 'landscape', 'horizontal'],
            '9:16': ['9:16', '縦', 'portrait', 'vertical']
        }

        for aspect_ratio, keywords in aspect_ratio_keywords.items():
            for keyword in keywords:
                if keyword in text.lower():
                    params['aspect_ratio'] = aspect_ratio
                    logger.debug(f"Aspect ratio extracted: {aspect_ratio}")
                    break
            if 'aspect_ratio' in params:
                break

        # デフォルトは16:9
        if 'aspect_ratio' not in params:
            params['aspect_ratio'] = '16:9'

        # 8. 解像度: "720p", "1080p", "HD", "Full HD" など
        resolution_keywords = {
            '720p': ['720p', 'hd'],
            '1080p': ['1080p', 'full hd', 'fullhd', 'fhd']
        }

        for resolution, keywords in resolution_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text.lower():
                    params['resolution'] = resolution
                    logger.debug(f"Resolution extracted: {resolution}")
                    break
            if 'resolution' in params:
                break

        # デフォルトは720p
        if 'resolution' not in params:
            params['resolution'] = '720p'

        return params

    def get_intent_help_message(self, intent: CommandIntent) -> str:
        """
        インテントに応じたヘルプメッセージを返す

        Args:
            intent: コマンドインテント

        Returns:
            ヘルプメッセージ
        """
        help_messages = {
            CommandIntent.CREATE: (
                "動画を生成するには、以下のように入力してください：\n"
                "例: 「この画像から8秒の動画を作って」\n"
                "例: 「image1.jpgをゆっくりズームインする動画にして」"
            ),
            CommandIntent.EXTEND: (
                "シーンを追加するには、以下のように入力してください：\n"
                "例: 「次のシーンを追加して」\n"
                "例: 「image2.jpgで続きを作って」"
            ),
            CommandIntent.TRANSITION: (
                "動画を連結するには、以下のように入力してください：\n"
                "例: 「今までのシーンを繋げて」\n"
                "例: 「フェード効果で連結して」"
            ),
            CommandIntent.FRAME_EDIT: (
                "フレームを編集するには、以下のように入力してください：\n"
                "例: 「Scene1の3秒目を明るくして」\n"
                "例: 「最初のシーンの色を鮮やかにして」"
            ),
            CommandIntent.UNKNOWN: (
                "申し訳ございません。コマンドを理解できませんでした。\n"
                "以下のような操作が可能です：\n"
                "• 動画生成: 「画像から動画を作って」\n"
                "• シーン追加: 「次のシーンを追加して」\n"
                "• 動画連結: 「シーンを繋げて」\n"
                "• フレーム編集: 「3秒目を明るくして」"
            )
        }

        return help_messages.get(intent, help_messages[CommandIntent.UNKNOWN])

    def validate_command(self, command: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        コマンドのバリデーション

        Args:
            command: parse_command()の戻り値

        Returns:
            (is_valid, error_message)
        """
        intent = command['intent']
        params = command['params']

        # UNKNOWNインテントはバリデーション失敗
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
                return False, "編集するシーンまたはタイムスタンプを指定してください"

        return True, None


# サンプル使用例（テスト用）
if __name__ == "__main__":
    # ロガー設定
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    handler = ChatCommandHandler()

    # テストケース
    test_inputs = [
        "外観.jpgから8秒の動画を作って。物件をゆっくりズームイン",
        "次に玄関.jpgで玄関のドアが開くシーンを追加",
        "全部フェード効果で繋げて",
        "Scene1の3秒目を明るくして",
        "これはテストです"  # UNKNOWN
    ]

    print("=" * 60)
    print("Chat Command Handler - Test Results")
    print("=" * 60)

    for i, user_input in enumerate(test_inputs, 1):
        print(f"\n[Test {i}] Input: {user_input}")
        command = handler.parse_command(user_input)

        print(f"  Intent: {command['intent'].value}")
        print(f"  Params:")
        for key, value in command['params'].items():
            print(f"    - {key}: {value}")

        # バリデーション
        is_valid, error_msg = handler.validate_command(command)
        if is_valid:
            print("  ✓ Valid command")
        else:
            print(f"  ✗ Invalid: {error_msg}")

    print("\n" + "=" * 60)
