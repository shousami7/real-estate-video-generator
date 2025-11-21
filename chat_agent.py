"""
AI Chat Agent for Video Editor
Handles natural language understanding and routes to appropriate video editing functions
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from google import genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VideoEditorChatAgent:
    """
    AI-powered chat agent that understands user intents and executes video editing tasks
    """

    # Intent types
    INTENT_GENERATE = "generate_video"
    INTENT_EXTEND = "extend_video"
    INTENT_MERGE = "merge_videos"
    INTENT_EDIT_FRAME = "edit_frame"
    INTENT_UNKNOWN = "unknown"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the chat agent with Gemini API

        Args:
            api_key: Google AI Studio API key (falls back to GOOGLE_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")

        if not self.api_key:
            raise ValueError("api_key is required. Set GOOGLE_API_KEY environment variable or pass api_key parameter.")

        logger.info(f"Initializing Chat Agent with Google AI Studio")
        self.client = genai.Client(api_key=self.api_key)

        self.model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
        logger.info(f"Chat agent initialized with model: {self.model}")

    def analyze_intent(self, user_message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze user message to determine intent and extract parameters

        Args:
            user_message: User's natural language message
            context: Current editor context (available videos, frames, etc.)

        Returns:
            Dict with intent type and extracted parameters
        """
        logger.info(f"Analyzing user message: {user_message}")

        # Build context information for AI
        context_info = self._build_context_info(context)

        # Create structured prompt for intent classification
        prompt = f"""You are an AI assistant for a video editing system. Analyze the user's message and determine their intent.

Available functions:
1. generate_video - Generate a new video from an image
2. extend_video - Extend/lengthen an existing video
3. merge_videos - Merge/combine multiple videos together
4. edit_frame - Edit a specific frame of a video

Current context:
{context_info}

User message: "{user_message}"

Analyze the message and respond in JSON format with:
{{
  "intent": "one of: generate_video, extend_video, merge_videos, edit_frame, unknown",
  "parameters": {{
    // Intent-specific parameters
  }},
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}

Intent-specific parameters:
- generate_video: {{"prompt": str, "duration": int (seconds), "image_attached": bool}}
- extend_video: {{"target_duration": int (seconds), "video_id": str}}
- merge_videos: {{"video_ids": [str], "transition_type": str, "transition_duration": float}}
- edit_frame: {{"frame_id": int, "edit_prompt": str}}

Respond ONLY with valid JSON, no other text."""

        try:
            # Call Gemini API for intent analysis
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )

            # Parse JSON response
            response_text = response.text.strip()

            # Remove markdown code blocks if present
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()

            intent_data = json.loads(response_text)

            logger.info(f"Intent detected: {intent_data['intent']} (confidence: {intent_data.get('confidence', 0)})")
            logger.info(f"Reasoning: {intent_data.get('reasoning', 'N/A')}")

            return intent_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse intent JSON: {e}")
            logger.error(f"Response text: {response_text}")
            return {
                "intent": self.INTENT_UNKNOWN,
                "parameters": {},
                "confidence": 0.0,
                "reasoning": "Failed to parse AI response"
            }
        except Exception as e:
            logger.error(f"Intent analysis failed: {e}")
            return {
                "intent": self.INTENT_UNKNOWN,
                "parameters": {},
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}"
            }

    def _build_context_info(self, context: Dict[str, Any]) -> str:
        """Build human-readable context information for AI"""
        info_parts = []

        # Available videos
        videos = context.get("videos", [])
        if videos:
            info_parts.append(f"Available videos: {len(videos)}")
            for i, video in enumerate(videos):
                info_parts.append(f"  Video {i+1}: {video.get('name', 'unnamed')} ({video.get('duration', '?')}s)")
        else:
            info_parts.append("No videos available yet")

        # Available frames
        frames = context.get("frames", [])
        if frames:
            info_parts.append(f"Extracted frames: {len(frames)}")

        # Uploaded image
        if context.get("uploaded_image"):
            info_parts.append("User has uploaded an image")

        # Current video
        current_video = context.get("current_video")
        if current_video:
            info_parts.append(f"Current video: {current_video.get('name', 'unnamed')} ({current_video.get('duration', '?')}s)")

        return "\n".join(info_parts) if info_parts else "No context available"

    def generate_response(self, intent_result: Dict[str, Any], execution_result: Dict[str, Any]) -> str:
        """
        Generate a natural language response based on intent and execution result

        Args:
            intent_result: Result from analyze_intent()
            execution_result: Result from executing the intended action

        Returns:
            Natural language response to user
        """
        intent = intent_result.get("intent")
        success = execution_result.get("status") == "success"

        if not success:
            error = execution_result.get("error", "Unknown error")
            return f"申し訳ありません。エラーが発生しました: {error}"

        # Generate success responses based on intent
        if intent == self.INTENT_GENERATE:
            duration = intent_result.get("parameters", {}).get("duration", "?")
            return f"✅ {duration}秒の動画を生成しました！プレビューを確認してください。"

        elif intent == self.INTENT_EXTEND:
            target_duration = intent_result.get("parameters", {}).get("target_duration", "?")
            return f"✅ 動画を{target_duration}秒に延長しました！"

        elif intent == self.INTENT_MERGE:
            video_count = len(intent_result.get("parameters", {}).get("video_ids", []))
            return f"✅ {video_count}つの動画を結合しました！"

        elif intent == self.INTENT_EDIT_FRAME:
            frame_id = intent_result.get("parameters", {}).get("frame_id", "?")
            return f"✅ フレーム {frame_id} の編集バリエーションを生成しました。お好みのものを選択してください。"

        else:
            return "✅ 処理が完了しました。"

    def get_clarification_prompt(self, intent_result: Dict[str, Any]) -> Optional[str]:
        """
        Generate a clarification question if intent is unclear or parameters are missing

        Args:
            intent_result: Result from analyze_intent()

        Returns:
            Clarification question or None if no clarification needed
        """
        intent = intent_result.get("intent")
        confidence = intent_result.get("confidence", 0)
        params = intent_result.get("parameters", {})

        # Low confidence - ask for clarification
        if confidence < 0.5:
            return "すみません、よく理解できませんでした。もう少し詳しく教えていただけますか？\n\n可能な操作:\n• 画像から動画を生成\n• 動画を延長\n• 複数の動画を結合\n• フレームを編集"

        # Check for missing required parameters
        if intent == self.INTENT_GENERATE:
            if not params.get("image_attached"):
                return "動画を生成するには、まず画像をアップロードしてください。"
            if not params.get("prompt"):
                return "動画の内容を説明してください（例: 「ゆっくりパンしながら建物を映す」）"

        elif intent == self.INTENT_EXTEND:
            if not params.get("video_id"):
                return "どの動画を延長しますか？"
            if not params.get("target_duration"):
                return "何秒まで延長しますか？"

        elif intent == self.INTENT_MERGE:
            video_ids = params.get("video_ids", [])
            if len(video_ids) < 2:
                return "結合するには少なくとも2つの動画が必要です。"

        elif intent == self.INTENT_EDIT_FRAME:
            if params.get("frame_id") is None:
                return "どのフレームを編集しますか？（フレーム番号を指定してください）"
            if not params.get("edit_prompt"):
                return "どのように編集しますか？（例: 「明るくして」「夕焼けを追加」）"

        return None


if __name__ == "__main__":
    # Test the chat agent
    import sys

    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        print("Error: GOOGLE_API_KEY not set")
        sys.exit(1)

    try:
        agent = VideoEditorChatAgent(api_key=api_key)
    except Exception as e:
        print(f"Failed to initialize agent: {e}")
        sys.exit(1)

    # Test cases
    test_messages = [
        "この画像から10秒の動画を作って",
        "この動画を20秒に延長して",
        "動画1と動画2をフェードで繋げて",
        "3番目のフレームを明るくして",
    ]

    test_context = {
        "videos": [
            {"name": "video1.mp4", "duration": 8},
            {"name": "video2.mp4", "duration": 8}
        ],
        "frames": [{"frame_id": i} for i in range(6)],
        "uploaded_image": True
    }

    for msg in test_messages:
        print(f"\n{'='*60}")
        print(f"User: {msg}")
        print(f"{'='*60}")
        result = agent.analyze_intent(msg, test_context)
        print(f"Intent: {result['intent']}")
        print(f"Parameters: {result['parameters']}")
        print(f"Confidence: {result['confidence']}")
        print(f"Reasoning: {result['reasoning']}")

        clarification = agent.get_clarification_prompt(result)
        if clarification:
            print(f"Clarification needed: {clarification}")
