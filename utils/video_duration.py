"""Utility helpers for probing video duration metadata.

This module provides a lightweight alternative to FFmpeg/ffprobe so that
we can still inspect clip durations in restricted environments where the
binary is unavailable.  When FFmpeg is present we keep using it because it
supports every format we rely on, but otherwise we fall back to a tiny
MP4/MOV parser that reads the ``mvhd`` atom.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def probe_video_duration(video_path: str, ffmpeg_path: str = "ffmpeg") -> float:
    """Return the duration of ``video_path`` in seconds.

    The helper first attempts to use FFmpeg because it supports every
    container we care about.  If FFmpeg is not installed (or we fail to parse
    the output) we fall back to a lightweight MP4/MOV parser.

    Args:
        video_path: Absolute or relative path to the video file.
        ffmpeg_path: Path to the FFmpeg binary (defaults to ``ffmpeg``).

    Raises:
        FileNotFoundError: If ``video_path`` does not exist.
        RuntimeError: If we cannot determine the duration via any strategy.
    """

    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    duration = _probe_with_ffmpeg(path, ffmpeg_path)
    if duration is not None:
        return duration

    duration = _probe_mp4_atom(path)
    if duration is not None:
        logger.debug("Duration resolved via MP4 atom parser: %.3fs", duration)
        return duration

    raise RuntimeError(f"Could not determine video duration for {video_path}")


def _probe_with_ffmpeg(video_path: Path, ffmpeg_path: Optional[str]) -> Optional[float]:
    """Use ``ffmpeg -i`` to read duration information.

    Returns ``None`` when FFmpeg is missing or when the stderr output does not
    include a ``Duration:`` line.
    """

    if not ffmpeg_path:
        return None

    cmd = [ffmpeg_path, "-i", str(video_path), "-hide_banner"]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("FFmpeg not available. Falling back to MP4 parser.")
        return None
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.debug("FFmpeg duration probe failed: %s", exc)
        return None

    for line in result.stderr.splitlines():
        if "Duration:" in line:
            time_str = line.split("Duration:")[1].split(",")[0].strip()
            parts = time_str.split(":")
            if len(parts) != 3:
                continue
            hours, minutes, seconds = parts
            try:
                total_seconds = (
                    float(hours) * 3600 + float(minutes) * 60 + float(seconds)
                )
                logger.debug("Duration resolved via FFmpeg: %.3fs", total_seconds)
                return total_seconds
            except ValueError:
                logger.debug("Unable to parse FFmpeg duration line: %s", line)
                return None
    return None


def _probe_mp4_atom(video_path: Path) -> Optional[float]:
    """Parse the ``mvhd`` atom from MP4/MOV containers."""

    if video_path.suffix.lower() not in {".mp4", ".m4v", ".mov"}:
        return None

    try:
        data = video_path.read_bytes()
    except OSError as exc:
        logger.debug("Failed to read video file %s: %s", video_path, exc)
        return None

    mvhd_chunk = _find_atom(data, target=b"mvhd")
    if mvhd_chunk is None:
        return None

    return _parse_mvhd(mvhd_chunk)


def _find_atom(data: bytes, target: bytes) -> Optional[bytes]:
    offset = 0
    total_len = len(data)

    while offset + 8 <= total_len:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        header_size = 8

        if size == 1:
            if offset + 16 > total_len:
                return None
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16

        if size == 0:
            size = total_len - offset

        if box_type == target:
            return data[offset + header_size : offset + size]

        # ``moov`` contains nested atoms. When we encounter it we need to keep
        # searching inside for ``mvhd``.
        if box_type == b"moov":
            nested = _find_atom(data[offset + header_size : offset + size], target)
            if nested is not None:
                return nested

        offset += size

    return None


def _parse_mvhd(chunk: bytes) -> Optional[float]:
    if not chunk:
        return None

    version = chunk[0]

    try:
        if version == 1:
            if len(chunk) < 32:
                return None
            timescale = int.from_bytes(chunk[20:24], "big")
            duration = int.from_bytes(chunk[24:32], "big")
        else:
            if len(chunk) < 20:
                return None
            timescale = int.from_bytes(chunk[12:16], "big")
            duration = int.from_bytes(chunk[16:20], "big")
    except Exception:  # pragma: no cover - defensive guard
        return None

    if timescale == 0:
        return None

    return duration / timescale


__all__ = ["probe_video_duration"]
