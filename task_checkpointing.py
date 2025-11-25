"""
Task checkpointing for crash recovery and progress persistence.

Saves task state to Redis at key milestones so tasks can survive server restarts
and resume from the last successful checkpoint.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

try:
    import redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

logger = logging.getLogger(__name__)


@dataclass
class CheckpointData:
    """Data stored at a checkpoint"""
    completed: bool
    timestamp: str
    data: Dict[str, Any]


class TaskCheckpoint:
    """
    Manage task state checkpoints in Redis for crash recovery.
    
    Checkpoints are saved at key milestones during task execution:
    - Image uploaded
    - Video generated
    - Video downloaded
    
    This allows tasks to resume from the last checkpoint instead of
    starting over if the server restarts.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None, ttl_hours: int = 48):
        """
        Initialize checkpoint manager.
        
        Args:
            redis_client: Redis client instance. If None, checkpointing is disabled.
            ttl_hours: How long to keep checkpoints in Redis (default 48 hours)
        """
        self.redis = redis_client
        self.ttl = int(timedelta(hours=ttl_hours).total_seconds())
        self.enabled = redis_client is not None
        
        if not self.enabled:
            logger.warning("Task checkpointing disabled (no Redis client available)")
    
    def save_checkpoint(self, task_id: str, state: Dict[str, Any]) -> bool:
        """
        Save complete task state to Redis.
        
        Args:
            task_id: Celery task ID
            state: Full task state dictionary
            
        Returns:
            True if saved successfully, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            # Add timestamp
            state['updated_at'] = datetime.utcnow().isoformat()
            
            # Serialize to JSON
            state_json = json.dumps(state)
            
            # Save to Redis with TTL
            key = f"task:checkpoint:{task_id}"
            self.redis.setex(key, self.ttl, state_json)
            
            logger.debug(f"Saved checkpoint for task {task_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save checkpoint for task {task_id}: {e}")
            return False
    
    def load_checkpoint(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Load task state from Redis.
        
        Args:
            task_id: Celery task ID
            
        Returns:
            Task state dictionary or None if not found
        """
        if not self.enabled:
            return None
        
        try:
            key = f"task:checkpoint:{task_id}"
            state_json = self.redis.get(key)
            
            if not state_json:
                return None
            
            # Deserialize from JSON
            if isinstance(state_json, bytes):
                state_json = state_json.decode('utf-8')
            
            state = json.loads(state_json)
            logger.debug(f"Loaded checkpoint for task {task_id}")
            return state
            
        except Exception as e:
            logger.error(f"Failed to load checkpoint for task {task_id}: {e}")
            return None
    
    def mark_checkpoint(
        self,
        task_id: str,
        checkpoint_name: str,
        data: Dict[str, Any],
        progress: Optional[int] = None
    ) -> bool:
        """
        Mark a specific checkpoint as complete and update progress.
        
        Args:
            task_id: Celery task ID
            checkpoint_name: Name of checkpoint (e.g., "image_uploaded")
            data: Data to save at this checkpoint
            progress: Optional progress percentage (0-100)
            
        Returns:
            True if saved successfully
        """
        if not self.enabled:
            return False
        
        try:
            # Load existing state or create new
            state = self.load_checkpoint(task_id) or {}
            
            # Ensure checkpoints dict exists
            if 'checkpoints' not in state:
                state['checkpoints'] = {}
            
            # Mark checkpoint as complete
            state['checkpoints'][checkpoint_name] = {
                'completed': True,
                'timestamp': datetime.utcnow().isoformat(),
                'data': data
            }
            
            # Update progress if provided
            if progress is not None:
                state['progress'] = progress
            
            # Update status based on checkpoint
            if checkpoint_name == 'image_uploaded':
                state['status'] = 'uploading_complete'
            elif checkpoint_name == 'video_generated':
                state['status'] = 'generating_complete'
            elif checkpoint_name == 'video_downloaded':
                state['status'] = 'complete'
            
            # Save updated state
            return self.save_checkpoint(task_id, state)
            
        except Exception as e:
            logger.error(f"Failed to mark checkpoint {checkpoint_name} for task {task_id}: {e}")
            return False
    
    def initialize_task(
        self,
        task_id: str,
        task_name: str,
        session_id: str,
        scene_id: str,
        input_params: Dict[str, Any]
    ) -> bool:
        """
        Initialize checkpoint state for a new task.
        
        Args:
            task_id: Celery task ID
            task_name: Task function name
            session_id: Session/video ID
            scene_id: Scene ID
            input_params: Input parameters (prompt, duration, etc.)
            
        Returns:
            True if initialized successfully
        """
        state = {
            'task_id': task_id,
            'task_name': task_name,
            'session_id': session_id,
            'scene_id': scene_id,
            'status': 'initializing',
            'progress': 0,
            'checkpoints': {},
            'input_params': input_params,
            'error': None,
            'retry_count': 0,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        return self.save_checkpoint(task_id, state)
    
    def mark_error(self, task_id: str, error: str) -> bool:
        """
        Mark task as failed with error message.
        
        Args:
            task_id: Celery task ID
            error: Error message
            
        Returns:
            True if saved successfully
        """
        if not self.enabled:
            return False
        
        try:
            state = self.load_checkpoint(task_id) or {}
            state['status'] = 'error'
            state['error'] = error
            
            return self.save_checkpoint(task_id, state)
            
        except Exception as e:
            logger.error(f"Failed to mark error for task {task_id}: {e}")
            return False
    
    def clear_checkpoint(self, task_id: str) -> bool:
        """
        Clear checkpoint after successful completion.
        
        Args:
            task_id: Celery task ID
            
        Returns:
            True if cleared successfully
        """
        if not self.enabled:
            return False
        
        try:
            key = f"task:checkpoint:{task_id}"
            self.redis.delete(key)
            logger.debug(f"Cleared checkpoint for task {task_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to clear checkpoint for task {task_id}: {e}")
            return False
    
    def get_resumable_tasks(self, max_age_hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get all tasks that can be resumed.
        
        A task is resumable if:
        - It has a checkpoint
        - Status is not 'complete' or 'error'
        - Created within max_age_hours
        
        Args:
            max_age_hours: Maximum age of tasks to consider (default 24 hours)
            
        Returns:
            List of task state dictionaries
        """
        if not self.enabled:
            return []
        
        try:
            # Find all checkpoint keys
            pattern = "task:checkpoint:*"
            keys = self.redis.keys(pattern)
            
            resumable = []
            cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            for key in keys:
                try:
                    state_json = self.redis.get(key)
                    if not state_json:
                        continue
                    
                    if isinstance(state_json, bytes):
                        state_json = state_json.decode('utf-8')
                    
                    state = json.loads(state_json)
                    
                    # Check if task is resumable
                    status = state.get('status', '')
                    created_at_str = state.get('created_at', '')
                    
                    if status in ('complete', 'error'):
                        continue
                    
                    if created_at_str:
                        created_at = datetime.fromisoformat(created_at_str)
                        if created_at < cutoff:
                            continue
                    
                    resumable.append(state)
                    
                except Exception as e:
                    logger.debug(f"Skipping invalid checkpoint {key}: {e}")
                    continue
            
            logger.info(f"Found {len(resumable)} resumable tasks")
            return resumable
            
        except Exception as e:
            logger.error(f"Failed to get resumable tasks: {e}")
            return []
    
    def can_resume_from_checkpoint(self, task_id: str, checkpoint_name: str) -> bool:
        """
        Check if a specific checkpoint can be resumed from.
        
        Args:
            task_id: Celery task ID
            checkpoint_name: Checkpoint to check
            
        Returns:
            True if checkpoint exists and was completed
        """
        state = self.load_checkpoint(task_id)
        if not state:
            return False
        
        checkpoints = state.get('checkpoints', {})
        checkpoint = checkpoints.get(checkpoint_name, {})
        
        return checkpoint.get('completed', False)


def get_checkpoint_manager(redis_client: Optional[redis.Redis] = None) -> TaskCheckpoint:
    """
    Get a TaskCheckpoint instance.
    
    Args:
        redis_client: Optional Redis client. If None, will try to get from celery backend.
        
    Returns:
        TaskCheckpoint instance
    """
    if redis_client is None:
        # Try to get Redis from Celery backend
        try:
            from celery_app import celery
            backend = celery.backend
            redis_client = getattr(backend, 'client', None)
        except Exception:
            pass
    
    return TaskCheckpoint(redis_client)
