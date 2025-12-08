"""API routes for the real-estate video generator backend."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from tasks import extract_frames_from_supabase

logger = logging.getLogger(__name__)

api_blueprint = Blueprint("api", __name__)


@api_blueprint.route("/api/extract", methods=["POST"])
def enqueue_frame_extraction() -> Any:
    """
    Enqueue a Celery task to extract frames from a video stored in Supabase.

    Expected JSON payload:
        {
            "task_id": "<task-id>",
            "video_path": "videos/<id>/input.mp4"
        }
    """

    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    task_id = payload.get("task_id")
    video_path = payload.get("video_path")

    if not task_id or not video_path:
        return jsonify({"error": "task_id and video_path are required"}), 400

    try:
        extract_frames_from_supabase.delay(task_id, video_path)
    except Exception as exc:  # pragma: no cover - depends on celery backend
        logger.exception("Failed to enqueue extract_frames_from_supabase")
        return jsonify({"error": str(exc)}), 500

    return jsonify({"status": "queued", "task_id": task_id}), 202
