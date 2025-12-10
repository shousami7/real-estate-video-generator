"""Frame processing utility functions."""

from __future__ import annotations


def calculate_frame_timestamp(frame_index: int, fps: float) -> float:
    """
    Calculate timestamp for a frame at given index.

    Args:
        frame_index: Frame index (0-based)
        fps: Frames per second

    Returns:
        Timestamp in seconds

    Example:
        >>> calculate_frame_timestamp(0, 4.0)
        0.0
        >>> calculate_frame_timestamp(4, 4.0)
        1.0
        >>> calculate_frame_timestamp(10, 5.0)
        2.0
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got: {fps}")
    if frame_index < 0:
        raise ValueError(f"frame_index must be non-negative, got: {frame_index}")

    return frame_index / fps


def calculate_frame_interval(fps: float) -> float:
    """
    Calculate the time interval between frames for a given FPS.

    Args:
        fps: Frames per second

    Returns:
        Interval in seconds between consecutive frames

    Example:
        >>> calculate_frame_interval(5.0)
        0.2
        >>> calculate_frame_interval(4.0)
        0.25
    """
    if fps <= 0:
        raise ValueError(f"fps must be positive, got: {fps}")

    return 1.0 / fps
