"""
Frame Editor Module
Handles video frame extraction and AI-powered frame editing
"""

import os
import json
import base64
import subprocess
import logging
import time
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import timedelta

# PIL is optional - only needed if image resizing is required
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logging.warning("PIL/Pillow not available. Image processing features may be limited.")

logger = logging.getLogger(__name__)

class FrameEditor:
    """
    Manages video frame extraction and AI editing
    """

    def __init__(self, video_path: str, output_dir: str = "frames"):
        """
        Initialize Frame Editor

        Args:
            video_path: Path to the video file
            output_dir: Directory to store extracted frames
        """
        self.video_path = video_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.frames = []
        self.ffmpeg_path = "ffmpeg"

        logger.info(f"Initialized FrameEditor for: {video_path}")

    def get_video_duration(self) -> float:
        """
        Get video duration in seconds

        Returns:
            Duration in seconds
        """
        cmd = [
            self.ffmpeg_path,
            "-i", self.video_path,
            "-hide_banner"
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)

            for line in result.stderr.split('\n'):
                if 'Duration:' in line:
                    time_str = line.split('Duration:')[1].split(',')[0].strip()
                    h, m, s = time_str.split(':')
                    duration = float(h) * 3600 + float(m) * 60 + float(s)
                    return duration

            return 0.0
        except Exception as e:
            logger.error(f"Error getting video duration: {e}")
            return 0.0

    def extract_frames(self, frame_count: int = 6) -> List[Dict[str, Any]]:
        """
        Extract frames from video at regular intervals

        Args:
            frame_count: Number of frames to extract

        Returns:
            List of frame information (path, timestamp, base64)
        """
        logger.info(f"Extracting {frame_count} frames from video...")

        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video not found: {self.video_path}")

        duration = self.get_video_duration()
        if duration == 0:
            raise ValueError("Could not determine video duration")

        interval = duration / (frame_count + 1)
        self.frames = []

        for i in range(frame_count):
            timestamp = interval * (i + 1)
            frame_path = self.output_dir / f"frame_{i:03d}.png"

            # FFmpegでフレームを抽出
            cmd = [
                self.ffmpeg_path,
                "-ss", str(timestamp),
                "-i", self.video_path,
                "-vframes", "1",
                "-q:v", "2",
                "-y",
                str(frame_path)
            ]

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    check=True,
                    timeout=30
                )

                # フレーム情報を保存
                frame_info = {
                    "frame_id": i,
                    "path": str(frame_path),
                    "timestamp": self._format_timestamp(timestamp),
                    "seconds": timestamp,
                    "base64": f"data:image/png;base64,{self._image_to_base64(str(frame_path))}"
                }
                self.frames.append(frame_info)
                logger.info(f"Extracted frame {i} at {frame_info['timestamp']}")

            except Exception as e:
                logger.error(f"Error extracting frame {i}: {e}")
                raise

        logger.info(f"Successfully extracted {len(self.frames)} frames")
        return self.frames

    def get_frame_by_id(self, frame_id: int) -> Optional[Dict[str, Any]]:
        """
        Get frame information by ID

        Args:
            frame_id: Frame ID

        Returns:
            Frame information dictionary
        """
        if 0 <= frame_id < len(self.frames):
            return self.frames[frame_id]
        return None

    def _format_timestamp(self, seconds: float) -> str:
        """
        Format seconds to MM:SS format

        Args:
            seconds: Time in seconds

        Returns:
            Formatted timestamp string
        """
        td = timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes}:{secs:02d}"

    def _image_to_base64(self, image_path: str) -> str:
        """
        Convert image to base64 string

        Args:
            image_path: Path to image file

        Returns:
            Base64 encoded image string
        """
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error converting image to base64: {e}")
            return ""


class AIFrameEditor:
    """
    AI-powered frame editing using Google AI
    """

    def __init__(self, api_key: str):
        """
        Initialize AI Frame Editor

        Args:
            api_key: Google AI API key
        """
        self.api_key = api_key
        logger.info("Initialized AI Frame Editor (Demo Mode)")

    def generate_frame_variations(
        self,
        base_image_path: str,
        prompt: str,
        variation_count: int = 4
    ) -> List[str]:
        """
        Generate multiple variations of a frame

        Args:
            base_image_path: Path to base frame image
            prompt: Edit prompt description
            variation_count: Number of variations to generate

        Returns:
            List of base64 encoded image strings
        """
        logger.info(f"Generating {variation_count} frame variations with prompt: {prompt}")

        # TODO: Google AI Image Generation API と統合
        # 現在はダミーデータを返す（元画像のbase64）
        try:
            with open(base_image_path, "rb") as img_file:
                img_data = base64.b64encode(img_file.read()).decode('utf-8')
                base64_img = f"data:image/png;base64,{img_data}"

            # 同じ画像を4つ返す（実際のAI生成に置き換える）
            variations = [base64_img] * variation_count

            logger.info(f"Generated {len(variations)} variations")
            return variations

        except Exception as e:
            logger.error(f"Error generating variations: {e}")
            # フォールバック: 小さなダミー画像
            dummy_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            return [dummy_img] * variation_count

    def generate_video_from_image(
        self,
        image_path: str,
        prompt: str,
        output_path: str,
        duration: int = 8
    ) -> str:
        """
        Generate video from uploaded image (Demo: returns pre-saved video)

        Args:
            image_path: Path to uploaded image (not used in demo)
            prompt: User's text prompt (not used in demo)
            output_path: Path to save generated video (not used in demo)
            duration: Video duration in seconds (default: 8)

        Returns:
            Path to pre-saved demo video
        """
        logger.info(f"[DEMO MODE] Simulating video generation...")
        logger.info(f"Prompt: {prompt}")

        # リアル感のために7秒待機
        logger.info("Waiting 7 seconds to simulate AI generation...")
        time.sleep(7)

        # 事前保存した動画のパスを返す
        demo_video_path = "static/demo_videos/parking_lot_demo.mp4"

        if not os.path.exists(demo_video_path):
            logger.error(f"Demo video not found: {demo_video_path}")
            raise FileNotFoundError(
                f"Demo video not found at: {demo_video_path}\n"
                f"Please place your demo video at this location."
            )

        logger.info(f"[DEMO MODE] Returning pre-saved video: {demo_video_path}")
        return demo_video_path
