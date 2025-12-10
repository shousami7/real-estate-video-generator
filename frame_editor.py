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
        self.frames = []
        self.ffmpeg_path = ffmpeg_path

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

    def _cleanup_old_frames(self):
        """Delete old frame files from the output directory before extracting new ones."""
        try:
            # Delete all existing frame files (jpg and png)
            deleted_count = 0
            for pattern in ["frame_*.jpg", "frame_*.png"]:
                for frame_file in self.output_dir.glob(pattern):
                    try:
                        frame_file.unlink()
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete old frame {frame_file}: {e}")
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old frame files from {self.output_dir}")
        except Exception as e:
            logger.warning(f"Error during frame cleanup: {e}")

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

    def extract_frames(
        self,
        frame_count: int = None,
        fps: float = 5.0,
        thumbnail_width: int = 320,
        jpeg_quality: int = 8
    ) -> List[Dict[str, Any]]:
        """
        Extract frames from video using batch ffmpeg processing (single invocation).

        Args:
            frame_count: Number of frames to extract (legacy, ignored if fps is set)
            fps: Frames per second to extract (default: 24.0 for standard video rate)

        Returns:
            List of frame information (path, timestamp, base64)
        """
        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video not found: {self.video_path}")

        # Clean up old frames before extracting new ones
        self._cleanup_old_frames()

        # get_video_duration raises FileNotFoundError or RuntimeError if it fails
        duration = self.get_video_duration()

        if duration <= 0:
            raise RuntimeError(f"Invalid video duration: {duration}")

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

        # Output pattern for batch extraction (JPEG format for smaller file size)
        output_pattern = str(self.output_dir / "frame_%04d.jpg")

        # Build ffmpeg command for batch extraction
        # Using fps filter to extract frames at calculated intervals
        # scale filter resizes to thumbnail width while maintaining aspect ratio
        vf_filters = f"fps={extract_fps:.6f},scale={thumbnail_width}:-1"

        cmd = [
            self.ffmpeg_path,
            "-i", self.video_path,
            "-vf", vf_filters,
            "-q:v", str(jpeg_quality),  # JPEG quality (2-31, lower is better)
            "-y",  # Overwrite output files
            output_pattern
        ]

        logger.debug(f"Running batch ffmpeg extraction: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=120  # Longer timeout for batch processing
            )
            logger.debug(f"ffmpeg stdout: {result.stdout.decode('utf-8', errors='ignore')}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg batch extraction failed: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Frame extraction failed: {e}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Frame extraction timed out (120s limit)")

        # Collect generated frame files
        frame_files = sorted(self.output_dir.glob("frame_*.jpg"))

        if not frame_files:
            raise RuntimeError("No frames were extracted")

        logger.debug(f"Found {len(frame_files)} extracted frame files")

        # Build frame information list
        self.frames = []
        actual_extracted = len(frame_files)
        interval = duration / actual_extracted if actual_extracted > 0 else 1.0

        for i, frame_path in enumerate(frame_files):
            timestamp = interval * i
            # Ensure timestamp doesn't exceed duration
            if timestamp >= duration:
                timestamp = max(duration - 0.001, 0)

            frame_info = {
                "frame_id": i,
                "name": f"extracted frame {i + 1}",
                "path": str(frame_path),
                "timestamp": self._format_timestamp(timestamp),
                "seconds": timestamp,
                "base64": f"data:image/jpeg;base64,{self._image_to_base64(str(frame_path))}"
            }
            self.frames.append(frame_info)
            logger.debug(f"Processed frame {i} at {frame_info['timestamp']}")

        logger.info(f"Successfully extracted {len(self.frames)} frames (batch mode, JPEG {thumbnail_width}px)")
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

    def extract_frame_at_timestamp(
        self,
        timestamp: float,
        thumbnail_width: int = 320,
        jpeg_quality: int = 8
    ) -> Dict[str, Any]:
        """
        Extract a single frame at a specific timestamp (on-demand extraction).

        Args:
            timestamp: Time in seconds to extract frame from
            thumbnail_width: Width of thumbnail in pixels (default: 320)
            jpeg_quality: JPEG quality for ffmpeg (2-31, lower is better, default: 8)

        Returns:
            Frame information dictionary with path, timestamp, and base64 data

        Raises:
            ValueError: If timestamp is invalid
            RuntimeError: If frame extraction fails
        """
        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video not found: {self.video_path}")

        duration = self.get_video_duration()

        if timestamp < 0 or timestamp > duration:
            raise ValueError(f"Invalid timestamp {timestamp}s (video duration: {duration}s)")

        # Generate unique filename based on timestamp
        timestamp_ms = int(timestamp * 1000)
        frame_filename = f"frame_at_{timestamp_ms}ms.jpg"
        output_path = str(self.output_dir / frame_filename)

        # Extract single frame at timestamp using FFmpeg
        extract_cmd = [
            self.ffmpeg_path,
            "-y",  # Overwrite if exists
            "-ss", str(timestamp),
            "-i", self.video_path,
            "-vframes", "1",
            "-vf", f"scale={thumbnail_width}:-1",
            "-q:v", str(jpeg_quality),
            output_path
        ]

        logger.info(f"Extracting frame at {timestamp}s: {' '.join(extract_cmd)}")

        try:
            result = subprocess.run(
                extract_cmd,
                capture_output=True,
                check=True,
                timeout=30
            )
            logger.debug(f"ffmpeg stdout: {result.stdout.decode('utf-8', errors='ignore')}")
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg frame extraction failed: {e.stderr.decode('utf-8', errors='ignore')}")
            raise RuntimeError(f"Frame extraction at {timestamp}s failed: {e}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Frame extraction timed out (30s limit)")

        # Validate output
        if not os.path.exists(output_path):
            raise RuntimeError(f"Frame extraction failed - no output file created")

        file_size = os.path.getsize(output_path)
        if file_size == 0:
            raise RuntimeError(f"Frame extraction failed - empty file created")

        logger.info(f"Successfully extracted frame at {timestamp}s ({file_size} bytes)")

        # Build frame information
        frame_info = {
            "frame_id": 0,  # Single frame, ID is always 0
            "name": f"frame at {self._format_timestamp(timestamp)}",
            "path": output_path,
            "timestamp": self._format_timestamp(timestamp),
            "seconds": timestamp,
            "base64": f"data:image/jpeg;base64,{self._image_to_base64(output_path)}"
        }

        return frame_info


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
