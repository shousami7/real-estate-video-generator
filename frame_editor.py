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
import shutil
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import timedelta

from utils.video_duration import probe_video_duration
from utils.frame_utils import calculate_frame_timestamp, calculate_frame_interval

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

    def __init__(self, video_path: str, output_dir: str = "frames", ffmpeg_path: str = "ffmpeg"):
        """
        Initialize Frame Editor

        Args:
            video_path: Path to the video file
            output_dir: Directory to store extracted frames
            ffmpeg_path: Path to the FFmpeg executable

        Raises:
            RuntimeError: If FFmpeg is not installed or accessible.
        """
        self.video_path = video_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Subdirectories for thumbnails and full-resolution frames
        self.thumbs_dir = self.output_dir / "thumbs"
        self.full_dir = self.output_dir / "full"
        self.frames = []
        self.ffmpeg_path = ffmpeg_path
        self.extraction_timestamp = None  # For cache-busting

        # Verify FFmpeg availability upfront to provide clear error messages
        self._verify_ffmpeg()

        logger.info(f"Initialized FrameEditor for: {video_path}")

    def _verify_ffmpeg(self):
        """Verify that FFmpeg is installed and accessible."""
        try:
            subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                check=True,
                timeout=10
            )
        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.\n"
                "Installation: https://ffmpeg.org/download.html"
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg verification failed: {e}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("FFmpeg verification timed out")

    def get_video_duration(self) -> float:
        """
        Get video duration in seconds

        Returns:
            Duration in seconds

        Raises:
            FileNotFoundError: If the video file does not exist.
            RuntimeError: If duration cannot be determined.
        """
        # Let exceptions propagate - returning 0.0 causes confusing errors downstream
        return probe_video_duration(self.video_path, ffmpeg_path=self.ffmpeg_path)

    def _clear_frame_directory(self):
        """Clear existing frame files before new extraction."""
        # Clear thumbs directory
        if self.thumbs_dir.exists():
            shutil.rmtree(self.thumbs_dir)
        self.thumbs_dir.mkdir(parents=True, exist_ok=True)

        # Clear full directory
        if self.full_dir.exists():
            shutil.rmtree(self.full_dir)
        self.full_dir.mkdir(parents=True, exist_ok=True)

        # Also clear any old-style frame files in output_dir root
        for old_file in self.output_dir.glob("frame_*.jpg"):
            old_file.unlink()
        for old_file in self.output_dir.glob("extracted_frame_*.png"):
            old_file.unlink()

        logger.debug(f"Cleared frame directories: {self.thumbs_dir}, {self.full_dir}")

    def extract_frames(
        self,
        frame_count: int = None,
        fps: float = 5.0,
        thumbnail_width: int = 320,
        jpeg_quality: int = 8,
        full_quality: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Extract frames from video using batch ffmpeg processing (single invocation).
        Produces both thumbnails (for UI) and full-resolution frames (for export/edit).

        Args:
            frame_count: Number of frames to extract (if specified, takes priority over fps)
            fps: Frames per second to extract (default: 5.0, used only if frame_count is None)
            thumbnail_width: Width of thumbnail in pixels (default: 320, height auto-calculated)
            jpeg_quality: JPEG quality for thumbnails (2-31, lower is better quality, default: 8)
            full_quality: JPEG quality for full-resolution frames (2-31, default: 2 for high quality)

        Returns:
            List of frame information (thumb_path, full_path, timestamp, etc.)
        """
        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video not found: {self.video_path}")

        # get_video_duration raises FileNotFoundError or RuntimeError if it fails
        duration = self.get_video_duration()

        if duration <= 0:
            raise RuntimeError(f"Invalid video duration: {duration}")

        # Clear existing frames before extraction
        self._clear_frame_directory()

        # Set extraction timestamp for cache-busting
        self.extraction_timestamp = int(time.time())

        # Calculate frame count based on parameters
        if frame_count is not None:
            # If frame_count is specified, use it directly
            actual_frame_count = max(1, min(frame_count, int(duration * 60)))  # Cap at 60fps equivalent
            logger.debug(f"Extracting {actual_frame_count} frames from video (frame_count specified)...")
        else:
            # Otherwise, use fps to calculate frame count
            actual_frame_count = max(1, int(duration * fps))
            logger.debug(f"Extracting frames at {fps} fps from video ({actual_frame_count} frames total)...")

        # Calculate fps for ffmpeg filter based on frame count and duration
        extract_fps = actual_frame_count / duration if duration > 0 else 1.0

        # Output patterns for batch extraction
        thumb_pattern = str(self.thumbs_dir / "frame_%04d.jpg")
        full_pattern = str(self.full_dir / "frame_%04d.jpg")

        # Extract thumbnails (resized, lower quality for fast UI)
        thumb_vf = f"fps={extract_fps:.6f},scale={thumbnail_width}:-1"
        thumb_cmd = [
            self.ffmpeg_path,
            "-i", self.video_path,
            "-vf", thumb_vf,
            "-q:v", str(jpeg_quality),
            "-y",
            thumb_pattern
        ]

        # Extract full-resolution frames (no resize, high quality for export/edit)
        full_vf = f"fps={extract_fps:.6f}"
        full_cmd = [
            self.ffmpeg_path,
            "-i", self.video_path,
            "-vf", full_vf,
            "-q:v", str(full_quality),
            "-y",
            full_pattern
        ]

        logger.debug(f"Running batch ffmpeg extraction (thumbnails): {' '.join(thumb_cmd)}")
        logger.debug(f"Running batch ffmpeg extraction (full): {' '.join(full_cmd)}")

        try:
            # Extract thumbnails
            subprocess.run(thumb_cmd, capture_output=True, check=True, timeout=120)
            # Extract full-resolution
            subprocess.run(full_cmd, capture_output=True, check=True, timeout=120)
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg batch extraction failed: {e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)}")
            raise RuntimeError(f"Frame extraction failed: {e}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Frame extraction timed out (120s limit)")

        # Collect generated thumbnail files
        thumb_files = sorted(self.thumbs_dir.glob("frame_*.jpg"))
        full_files = sorted(self.full_dir.glob("frame_*.jpg"))

        if not thumb_files:
            raise RuntimeError("No frames were extracted")

        logger.debug(f"Found {len(thumb_files)} thumbnail files, {len(full_files)} full-res files")

        # Build frame information list
        self.frames = []
        actual_extracted = len(thumb_files)
        interval = duration / actual_extracted if actual_extracted > 0 else 1.0

        for i, thumb_path in enumerate(thumb_files):
            timestamp = interval * i
            # Ensure timestamp doesn't exceed duration
            if timestamp >= duration:
                timestamp = max(duration - 0.001, 0)

            # Get corresponding full-res path
            full_path = full_files[i] if i < len(full_files) else thumb_path

            frame_info = {
                "frame_id": i,
                "name": f"extracted frame {i + 1}",
                "path": str(thumb_path),  # Thumbnail path (for backward compatibility)
                "full_path": str(full_path),  # Full-resolution path (for export/edit)
                "timestamp": self._format_timestamp(timestamp),
                "seconds": timestamp,
                "cache_ts": self.extraction_timestamp  # For cache-busting
            }
            self.frames.append(frame_info)
            logger.debug(f"Processed frame {i} at {frame_info['timestamp']}")

        logger.info(f"Successfully extracted {len(self.frames)} frames (batch mode, thumb={thumbnail_width}px + full-res)")
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
        Format seconds to MM:SS.d format (with tenths for 3fps precision)

        Args:
            seconds: Time in seconds

        Returns:
            Formatted timestamp string (e.g., "0:01.3")
        """
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}:{secs:04.1f}"

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
    AI-powered frame editing (placeholder implementation).
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize AI Frame Editor (currently demo/no-op for auth).

        Args:
            api_key: Optional Google AI Studio API key for future AI-backed edits
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
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
