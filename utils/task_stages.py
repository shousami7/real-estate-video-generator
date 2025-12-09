"""
Task stage definitions and progress tracking.

Manages stage-based progress for tasks with historical duration tracking
and time-remaining estimates.
"""

import time
import logging
from typing import Dict, List, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # Only import for type checking, not at runtime
    import redis

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    # Create a dummy type for when redis is not available
    redis = type('redis', (), {'Redis': type('Redis', (), {})})  # type: ignore

logger = logging.getLogger(__name__)


# Stage definitions for each task type
TASK_STAGES = {
    "generate": [
        {
            "id": "validating",
            "label": "Validating image...",
            "duration_estimate": 1,
            "icon": "✓"
        },
        {
            "id": "uploading",
            "label": "Uploading image...",
            "duration_estimate": 5,
            "icon": "📤"
        },
        {
            "id": "generating",
            "label": "Generating video (this takes 2-3 min)...",
            "duration_estimate": 150,
            "icon": "🎬"
        },
        {
            "id": "downloading",
            "label": "Downloading video...",
            "duration_estimate": 10,
            "icon": "📥"
        },
        {
            "id": "finalizing",
            "label": "Finalizing...",
            "duration_estimate": 2,
            "icon": "✨"
        }
    ],
    "extend": [
        {
            "id": "extracting_frame",
            "label": "Extracting reference frame...",
            "duration_estimate": 3,
            "icon": "🎞️"
        },
        {
            "id": "uploading",
            "label": "Uploading...",
            "duration_estimate": 5,
            "icon": "📤"
        },
        {
            "id": "generating",
            "label": "Extending video (2-3 min)...",
            "duration_estimate": 150,
            "icon": "🎬"
        },
        {
            "id": "adding_transitions",
            "label": "Adding transitions...",
            "duration_estimate": 5,
            "icon": "✨"
        },
        {
            "id": "finalizing",
            "label": "Finalizing...",
            "duration_estimate": 2,
            "icon": "✅"
        }
    ],
    "merge": [
        {
            "id": "loading",
            "label": "Loading video clips...",
            "duration_estimate": 3,
            "icon": "📁"
        },
        {
            "id": "adding_transitions",
            "label": "Adding transitions...",
            "duration_estimate": 10,
            "icon": "✨"
        },
        {
            "id": "encoding",
            "label": "Encoding final video...",
            "duration_estimate": 15,
            "icon": "🎬"
        },
        {
            "id": "finalizing",
            "label": "Finalizing...",
            "duration_estimate": 2,
            "icon": "✅"
        }
    ]
}


class StageProgress:
    """
    Manage stage-based progress tracking with historical duration data.
    
    Features:
    - Track actual stage durations in Redis
    - Calculate time estimates based on history
    - Provide user-friendly progress messages
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize stage progress tracker.
        
        Args:
            redis_client: Redis client for historical data. If None, uses estimates only.
        """
        self.redis = redis_client
        self.enabled = redis_client is not None
        
        if not self.enabled:
            logger.debug("Historical duration tracking disabled (no Redis client)")
    
    def record_stage_duration(self, task_type: str, stage_id: str, duration: float) -> None:
        """
        Record actual duration for a stage to improve future estimates.
        
        Args:
            task_type: Type of task (e.g., "generate", "extend")
            stage_id: ID of the stage (e.g., "uploading")
            duration: Actual duration in seconds
        """
        if not self.enabled:
            return
        
        try:
            key = f"task:duration:{task_type}:{stage_id}"
            
            # Store last 20 durations (rolling window)
            self.redis.lpush(key, duration)
            self.redis.ltrim(key, 0, 19)
            
            # Keep for 30 days
            self.redis.expire(key, 86400 * 30)
            
            logger.debug(f"Recorded duration for {task_type}.{stage_id}: {duration:.1f}s")
            
        except Exception as e:
            logger.error(f"Failed to record stage duration: {e}")
    
    def get_average_duration(self, task_type: str, stage_id: str) -> Optional[float]:
        """
        Get average duration for a stage based on historical data.
        
        Args:
            task_type: Type of task
            stage_id: ID of the stage
            
        Returns:
            Average duration in seconds, or None if no history available
        """
        if not self.enabled:
            return None
        
        try:
            key = f"task:duration:{task_type}:{stage_id}"
            durations = self.redis.lrange(key, 0, -1)
            
            if not durations:
                return None
            
            # Convert to floats and calculate average
            durations_float = [float(d) for d in durations]
            avg = sum(durations_float) / len(durations_float)
            
            logger.debug(f"Average duration for {task_type}.{stage_id}: {avg:.1f}s (from {len(durations_float)} samples)")
            return avg
            
        except Exception as e:
            logger.error(f"Failed to get average duration: {e}")
            return None
    
    def estimate_time_remaining(
        self,
        task_type: str,
        current_stage: str,
        stage_start_time: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Calculate time remaining for task from current stage.
        
        Args:
            task_type: Type of task (e.g., "generate")
            current_stage: Current stage ID
            stage_start_time: When current stage started (Unix timestamp)
            
        Returns:
            {
                "seconds": int,           # Total seconds remaining
                "formatted": str,         # User-friendly format (e.g., "~2 min")
                "confidence": str         # "high", "medium", or "low"
            }
        """
        stages = TASK_STAGES.get(task_type, [])
        if not stages:
            return {
                "seconds": 0,
                "formatted": "calculating...",
                "confidence": "low"
            }
        
        # Find current stage index
        current_idx = next(
            (i for i, s in enumerate(stages) if s['id'] == current_stage),
            -1
        )
        
        if current_idx == -1:
            return {
                "seconds": 0,
                "formatted": "calculating...",
                "confidence": "low"
            }
        
        # Calculate remaining time
        total_seconds = 0.0
        has_historical = False
        
        # Add remaining time for current stage
        if stage_start_time:
            current_stage_def = stages[current_idx]
            historical_duration = self.get_average_duration(task_type, current_stage)
            expected_duration = historical_duration or current_stage_def['duration_estimate']
            
            elapsed = time.time() - stage_start_time
            remaining_in_stage = max(0, expected_duration - elapsed)
            total_seconds += remaining_in_stage
            
            if historical_duration:
                has_historical = True
        
        # Add time for future stages
        for stage in stages[current_idx + 1:]:
            historical = self.get_average_duration(task_type, stage['id'])
            if historical:
                total_seconds += historical
                has_historical = True
            else:
                total_seconds += stage['duration_estimate']
        
        # Determine confidence level
        if has_historical:
            # High confidence if we have data and not on last stage
            confidence = "high" if current_idx < len(stages) - 1 else "medium"
        else:
            # Low confidence without historical data
            confidence = "low"
        
        # Format time for display
        formatted = self._format_time(total_seconds)
        
        return {
            "seconds": int(total_seconds),
            "formatted": formatted,
            "confidence": confidence
        }
    
    def _format_time(self, seconds: float) -> str:
        """
        Format seconds into user-friendly time string.
        
        Args:
            seconds: Number of seconds
            
        Returns:
            Formatted string like "~2 min" or "finishing up..."
        """
        if seconds < 5:
            return "finishing up..."
        elif seconds < 60:
            return f"~{int(seconds)}s"
        elif seconds < 90:
            return "~1 min"
        elif seconds < 120:
            return "~2 min"
        else:
            mins = round(seconds / 60)
            return f"~{mins} min"
    
    def get_stage_label(self, task_type: str, stage_id: str) -> str:
        """
        Get user-friendly label for a stage.
        
        Args:
            task_type: Type of task
            stage_id: ID of the stage
            
        Returns:
            Label string (e.g., "Generating video (this takes 2-3 min)...")
        """
        stages = TASK_STAGES.get(task_type, [])
        stage = next((s for s in stages if s['id'] == stage_id), None)
        
        if stage:
            return stage['label']
        else:
            return "Processing..."
    
    def get_stage_icon(self, task_type: str, stage_id: str) -> str:
        """Get icon for a stage"""
        stages = TASK_STAGES.get(task_type, [])
        stage = next((s for s in stages if s['id'] == stage_id), None)
        return stage['icon'] if stage else "⏳"
    
    def get_all_stages(self, task_type: str) -> List[Dict[str, Any]]:
        """
        Get all stages for a task type.
        
        Args:
            task_type: Type of task
            
        Returns:
            List of stage dictionaries
        """
        return TASK_STAGES.get(task_type, [])
    
    def get_stage_index(self, task_type: str, stage_id: str) -> int:
        """
        Get the index of a stage in the task flow.
        
        Args:
            task_type: Type of task
            stage_id: ID of the stage
            
        Returns:
            Index (0-based) or -1 if not found
        """
        stages = TASK_STAGES.get(task_type, [])
        return next(
            (i for i, s in enumerate(stages) if s['id'] == stage_id),
            -1
        )


def get_stage_progress(redis_client: Optional[redis.Redis] = None) -> StageProgress:
    """
    Get a StageProgress instance.
    
    Args:
        redis_client: Optional Redis client. If None, tries to get from celery backend.
        
    Returns:
        StageProgress instance
    """
    if redis_client is None:
        # Try to get Redis from Celery backend
        try:
            from celery_app import celery
            backend = celery.backend
            redis_client = getattr(backend, 'client', None)
        except Exception:
            pass
    
    return StageProgress(redis_client)
