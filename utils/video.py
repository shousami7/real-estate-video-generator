"""Video processing utilities for frame extraction using ffmpeg."""

from __future__ import annotations

import glob
import logging
import os
import subprocess
from typing import List

logger = logging.getLogger(__name__)


def extract_frames_ffmpeg(input_path: str, output_dir: str, fps: int = 4) -> List[str]:
    """
    Extract frames from a video file using ffmpeg.

    Args:
        input_path: Local path to the video file.
        output_dir: Directory where frames will be written.
        fps: Frames per second to extract (default: 4).

    Returns:
        Sorted list of generated frame file paths.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    os.makedirs(output_dir, exist_ok=True)

    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")
    command = [
        "ffmpeg",
        "-y",  # overwrite existing files
        "-i", input_path,
        "-vf", f"fps={fps}",
        output_pattern,
    ]


    logger.info("Running ffmpeg for frame extraction: %s", " ".join(command))

    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
        logger.error("ffmpeg failed: %s", stderr)
        raise RuntimeError(f"ffmpeg failed with exit code {exc.returncode}: {stderr}") from exc

    frames = sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg")))
    logger.info("Extracted %d frames", len(frames))
    return frames
