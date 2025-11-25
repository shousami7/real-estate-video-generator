"""
Server-Sent Events (SSE) streaming for real-time task progress updates.

Provides real-time push updates to clients instead of HTTP polling,
reducing server load and improving responsiveness.
"""

import json
import time
import logging
from typing import Generator, Dict, Any, Optional
from flask import Response

logger = logging.getLogger(__name__)


def create_sse_response(stream_generator: Generator) -> Response:
    """
    Create a Flask Response configured for Server-Sent Events.
    
    Args:
        stream_generator: Generator that yields SSE-formatted messages
        
    Returns:
        Flask Response with appropriate SSE headers
    """
    return Response(
        stream_generator,
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable nginx buffering
            'Connection': 'keep-alive',
        }
    )


def format_sse_message(data: Dict[str, Any], event: str = 'message') -> str:
    """
    Format data as SSE message according to SSE spec.
    
    SSE format:
        event: message
        data: {"key": "value"}
        
    Args:
        data: Dictionary to send
        event: Event type (default: "message")
        
    Returns:
        Formatted SSE message string
    """
    json_data = json.dumps(data)
    return f"event: {event}\ndata: {json_data}\n\n"


def task_progress_stream(task_id: str) -> Generator[str, None, None]:
    """
    Stream task progress updates via Server-Sent Events.
    
    This generator yields SSE-formatted messages with task status updates
    until the task completes or fails.
    
    Args:
        task_id: Celery task ID to monitor
        
    Yields:
        SSE-formatted messages with task progress
    """
    from celery.result import AsyncResult
    from celery_app import celery
    from utils.task_stages import get_stage_progress
    
    logger.info(f"Starting SSE stream for task {task_id}")
    
    last_state = None
    last_stage = None
    last_step = None
    heartbeat_counter = 0
    stage_progress = get_stage_progress()
    
    try:
        while True:
            try:
                task = AsyncResult(task_id, app=celery)
                current_state = task.state
                
                # Get task metadata
                task_info = {}
                if task.info and isinstance(task.info, dict):
                    task_info = task.info
                
                current_stage = task_info.get('stage')
                current_step = task_info.get('step')
                task_type = task_info.get('task_type', current_stage)  # Use stage as fallback
                
                # Check if something changed
                state_changed = (
                    current_state != last_state or
                    current_stage != last_stage or
                    current_step != last_step
                )
                
                if state_changed:
                    logger.debug(
                        f"Task {task_id}: {current_state} - "
                        f"{current_stage}/{current_step}"
                    )
                    
                    # Calculate time remaining
                    time_remaining = {"seconds": 0, "formatted": "calculating...", "confidence": "low"}
                    if task_type and current_step:
                        time_remaining = stage_progress.estimate_time_remaining(
                            task_type,
                            current_step,
                            task_info.get('stage_start_time')
                        )
                    
                    # Get stage label and icon
                    stage_label = task_info.get('message', '')
                    stage_icon = ''
                    if task_type and current_step:
                        stage_label = stage_progress.get_stage_label(task_type, current_step)
                        stage_icon = stage_progress.get_stage_icon(task_type, current_step)
                    
                    # Send update
                    yield format_sse_message({
                        'status': current_state,
                        'stage': current_stage,
                        'step': current_step,
                        'label': stage_label,
                        'icon': stage_icon,
                        'time_remaining': time_remaining,
                        'progress': task_info.get('progress', 0),
                        'video_id': task_info.get('video_id'),
                        'scene_id': task_info.get('scene_id'),
                    })
                    
                    last_state = current_state
                    last_stage = current_stage
                    last_step = current_step
                    heartbeat_counter = 0
                
                # Check if task is complete
                if current_state in ('SUCCESS', 'FAILURE', 'REVOKED'):
                    logger.info(f"Task {task_id} completed with state: {current_state}")
                    
                    # Send final message
                    final_data = {
                        'status': current_state,
                        'final': True
                    }
                    
                    # Include result or error
                    if current_state == 'SUCCESS':
                        final_data['result'] = task.result
                    elif current_state == 'FAILURE':
                        final_data['error'] = str(task.info)
                    
                    yield format_sse_message(final_data)
                    break
                
                # Send heartbeat every 30 seconds to keep connection alive
                heartbeat_counter += 1
                if heartbeat_counter >= 60:  # 60 * 0.5s = 30s
                    yield format_sse_message({'heartbeat': True}, event='heartbeat')
                    heartbeat_counter = 0
                
                # Wait before next check (500ms)
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in SSE stream for task {task_id}: {e}")
                yield format_sse_message({
                    'error': str(e),
                    'recoverable': False
                }, event='error')
                break
    
    except GeneratorExit:
        logger.info(f"Client disconnected from SSE stream for task {task_id}")
    
    except Exception as e:
        logger.error(f"Fatal error in SSE stream for task {task_id}: {e}")
        yield format_sse_message({
            'error': 'Stream terminated unexpectedly',
            'recoverable': True
        }, event='error')
    
    finally:
        logger.info(f"SSE stream ended for task {task_id}")


def video_list_stream() -> Generator[str, None, None]:
    """
    Stream updates about video list changes.
    
    This can be used to push notifications when new videos are created
    or existing videos are updated.
    
    Yields:
        SSE-formatted messages with video list updates
    """
    # This is a placeholder for future video list streaming
    # Could be implemented with Redis pub/sub
    yield format_sse_message({
        'message': 'Video list streaming not yet implemented'
    })
