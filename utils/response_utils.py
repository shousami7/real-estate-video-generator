"""
Unified task response builder for MCP orchestration.
All tasks must return this exact format.
"""
from typing import Optional


def build_task_response(
    task_id: str,
    video_id: str,
    stage: str,
    status: str,
    progress: Optional[int] = None,
    output_url: Optional[str] = None,
    frames: Optional[list] = None,
    error: Optional[str] = None,
    local_path: Optional[str] = None,
) -> dict:
    """
    Build a unified task response for MCP orchestration.

    Args:
        task_id: Celery task ID
        video_id: Video/session ID
        stage: Stage name (generate, extend, extract, edit, stitch)
        status: pending, running, completed, error
        progress: Progress percentage (0-100) (optional)
        output_url: Final media URL (optional)
        frames: List of frames for extract/edit (optional)
        error: Error message if status=error (optional)
        local_path: Local filesystem path to the video file (optional)

    Returns:
        Unified response dict with ALL keys in exact order
    """
    return {
        "task_id": task_id,
        "video_id": video_id,
        "stage": stage,
        "status": status,
        "progress": progress,
        "output_url": output_url,
        "local_path": local_path,
        "frames": frames,
        "error": error,
    }
