"""
FFmpeg Video Composer Module
Handles video concatenation with transition effects
"""

import subprocess
import os
import logging
from typing import List, Optional
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VideoComposer:
    """
    Manages video composition using FFmpeg
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg"):
        """
        Initialize the Video Composer

        Args:
            ffmpeg_path: Path to ffmpeg executable (default: "ffmpeg")
        """
        self.ffmpeg_path = ffmpeg_path
        self._verify_ffmpeg()

    def _verify_ffmpeg(self):
        """
        Verify that FFmpeg is installed and accessible
        """
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                check=True
            )
            logger.info(f"FFmpeg found: {result.stdout.split()[0]}")
        except FileNotFoundError:
            raise RuntimeError(
                "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH.\n"
                "Installation: https://ffmpeg.org/download.html"
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"FFmpeg verification failed: {e}")

    def get_video_duration(self, video_path: str) -> float:
        """
        Get the duration of a video file in seconds

        Args:
            video_path: Path to the video file

        Returns:
            Duration in seconds
        """
        cmd = [
            self.ffmpeg_path,
            "-i", video_path,
            "-hide_banner"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            # Parse duration from stderr output
            for line in result.stderr.split('\n'):
                if 'Duration:' in line:
                    time_str = line.split('Duration:')[1].split(',')[0].strip()
                    h, m, s = time_str.split(':')
                    duration = float(h) * 3600 + float(m) * 60 + float(s)
                    return duration

            raise ValueError("Could not parse video duration")

        except Exception as e:
            logger.error(f"Error getting video duration: {e}")
            # Return default duration
            return 8.0

    def compose_with_transitions(
        self,
        video_paths: List[str],
        output_path: str,
        transition_type: str = "fade",
        transition_duration: float = 0.5,
        resolution: str = "1280x720"
    ) -> str:
        """
        Compose multiple videos with transition effects

        Args:
            video_paths: List of input video paths
            output_path: Path to save the composed video
            transition_type: Type of transition ("fade", "wipeleft", "wiperight", etc.)
            transition_duration: Duration of transition in seconds
            resolution: Output resolution (default: "1280x720")

        Returns:
            Path to the composed video
        """
        if len(video_paths) < 2:
            raise ValueError("Need at least 2 videos to compose")

        logger.info(f"Composing {len(video_paths)} videos with {transition_type} transitions")

        # Get actual duration of each video
        video_durations = []
        for video_path in video_paths:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")
            duration = self.get_video_duration(video_path)
            video_durations.append(duration)
            logger.info(f"Video {os.path.basename(video_path)} duration: {duration}s")

        # Create output directory if needed
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

        # Build FFmpeg filter graph with actual durations
        filter_complex = self._build_filter_graph(
            video_count=len(video_paths),
            video_durations=video_durations,
            transition_type=transition_type,
            transition_duration=transition_duration,
            resolution=resolution
        )

        # Build FFmpeg command
        cmd = [self.ffmpeg_path, "-y"]  # -y to overwrite output file

        # Add input files
        for video_path in video_paths:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")
            cmd.extend(["-i", video_path])

        # Add filter complex
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path
        ])

        logger.info("Running FFmpeg composition...")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minutes timeout for composition
            )
            logger.info(f"Video composition completed: {output_path}")

            # Verify output file was created
            if not os.path.exists(output_path):
                raise RuntimeError(f"FFmpeg completed but output file not found: {output_path}")

            file_size = os.path.getsize(output_path)
            if file_size == 0:
                raise RuntimeError(f"FFmpeg created empty output file: {output_path}")

            # Check final video duration
            final_duration = self.get_video_duration(output_path)
            logger.info(f"Final video duration: {final_duration}s")
            logger.info(f"Output file size: {file_size} bytes")
            return output_path

        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg composition timed out after 5 minutes")
            raise RuntimeError("Video composition timed out. Try with shorter clips or simpler transitions.")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise RuntimeError(f"Video composition failed: {e.stderr}")
        except BrokenPipeError as e:
            logger.error(f"Broken pipe error during FFmpeg composition: {e}")
            raise RuntimeError("FFmpeg process was interrupted. Please try again.")

    def _build_filter_graph(
        self,
        video_count: int,
        video_durations: List[float],
        transition_type: str,
        transition_duration: float,
        resolution: str
    ) -> str:
        """
        Build FFmpeg filter graph for video transitions with proper timing

        Args:
            video_count: Number of input videos
            video_durations: List of actual video durations in seconds
            transition_type: Type of transition effect
            transition_duration: Duration of transition in seconds
            resolution: Output resolution

        Returns:
            FFmpeg filter complex string
        """
        width, height = resolution.split('x')

        # Scale all inputs to the same resolution and trim to ensure exact duration
        scale_filters = []
        for i in range(video_count):
            # Trim each video to its exact duration to prevent timing issues
            scale_filters.append(
                f"[{i}:v]trim=duration={video_durations[i]},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
            )

        # Build transition chain with proper offset calculation
        transition_filters = []
        current_input = "v0"
        accumulated_offset = 0.0  # Track when each transition should start

        for i in range(1, video_count):
            output_label = f"v{i}out" if i < video_count - 1 else "outv"

            # The offset for xfade is when the transition should start
            # This is the duration of all previous clips minus the overlaps
            if i == 1:
                # First transition: starts at (duration of clip 1 - transition_duration)
                accumulated_offset = video_durations[0] - transition_duration
            else:
                # Subsequent transitions: add the duration of the previous clip minus the overlap
                accumulated_offset += video_durations[i-1] - transition_duration

            transition_filter = f"[{current_input}][v{i}]xfade=transition={transition_type}:duration={transition_duration}:offset={accumulated_offset}[{output_label}]"
            transition_filters.append(transition_filter)

            logger.info(f"Transition {i}: offset={accumulated_offset}s, duration={transition_duration}s")

            current_input = output_label

        # Calculate expected total duration
        total_duration = sum(video_durations) - (video_count - 1) * transition_duration
        logger.info(f"Expected total video duration: {total_duration}s")

        # Combine all filters
        all_filters = scale_filters + transition_filters
        filter_complex = ";".join(all_filters)

        return filter_complex

    def simple_concatenate(
        self,
        video_paths: List[str],
        output_path: str,
        resolution: str = "1280x720"
    ) -> str:
        """
        Simple video concatenation without transitions

        Args:
            video_paths: List of input video paths
            output_path: Path to save the composed video
            resolution: Output resolution

        Returns:
            Path to the composed video
        """
        if len(video_paths) < 2:
            raise ValueError("Need at least 2 videos to concatenate")

        logger.info(f"Concatenating {len(video_paths)} videos without transitions")

        # Create output directory
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

        width, height = resolution.split('x')

        # Build filter complex for simple concatenation
        # Scale all inputs
        scale_filters = []
        for i in range(len(video_paths)):
            scale_filters.append(f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v{i}]")

        # Concatenate
        concat_inputs = "".join([f"[v{i}]" for i in range(len(video_paths))])
        concat_filter = f"{concat_inputs}concat=n={len(video_paths)}:v=1:a=0[outv]"

        filter_complex = ";".join(scale_filters + [concat_filter])

        # Build FFmpeg command
        cmd = [self.ffmpeg_path, "-y"]

        for video_path in video_paths:
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"Video file not found: {video_path}")
            cmd.extend(["-i", video_path])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            output_path
        ])

        logger.info("Running FFmpeg concatenation...")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minutes timeout for concatenation
            )
            logger.info(f"Video concatenation completed: {output_path}")

            # Verify output file was created
            if not os.path.exists(output_path):
                raise RuntimeError(f"FFmpeg completed but output file not found: {output_path}")

            file_size = os.path.getsize(output_path)
            if file_size == 0:
                raise RuntimeError(f"FFmpeg created empty output file: {output_path}")

            logger.info(f"Output file size: {file_size} bytes")
            return output_path

        except subprocess.TimeoutExpired as e:
            logger.error(f"FFmpeg concatenation timed out after 5 minutes")
            raise RuntimeError("Video concatenation timed out. Try with shorter clips.")
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg error: {e.stderr}")
            raise RuntimeError(f"Video concatenation failed: {e.stderr}")
        except BrokenPipeError as e:
            logger.error(f"Broken pipe error during FFmpeg concatenation: {e}")
            raise RuntimeError("FFmpeg process was interrupted. Please try again.")


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 4:
        print("Usage: python video_composer.py <video1> <video2> <video3> ... <output>")
        sys.exit(1)

    video_paths = sys.argv[1:-1]
    output_path = sys.argv[-1]

    composer = VideoComposer()

    try:
        result_path = composer.compose_with_transitions(
            video_paths=video_paths,
            output_path=output_path,
            transition_type="fade",
            transition_duration=0.5
        )
        print(f"Success! Composed video saved to: {result_path}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
