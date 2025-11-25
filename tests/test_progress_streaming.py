"""
Tests for SSE streaming and stage progress tracking
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

from utils.task_stages import StageProgress, TASK_STAGES
from utils.progress_streaming import format_sse_message


class TestStageProgress:
    """Test stage progress tracking"""
    
    def test_get_stage_label(self):
        """Test getting stage labels"""
        sp = StageProgress()
        
        label = sp.get_stage_label("generate", "uploading")
        assert "Uploading" in label
        
        label = sp.get_stage_label("generate", "generating")
        assert "2-3 min" in label
    
    def test_get_stage_icon(self):
        """Test getting stage icons"""
        sp = StageProgress()
        
        icon = sp.get_stage_icon("generate", "uploading")
        assert icon == "📤"
        
        icon = sp.get_stage_icon("generate", "generating")
        assert icon == "🎬"
    
    def test_get_all_stages(self):
        """Test getting all stages for a task type"""
        sp = StageProgress()
        
        stages = sp.get_all_stages("generate")
        assert len(stages) == 5
        assert stages[0]['id'] == 'validating'
        assert stages[-1]['id'] == 'finalizing'
    
    def test_get_stage_index(self):
        """Test getting stage index"""
        sp = StageProgress()
        
        idx = sp.get_stage_index("generate", "uploading")
        assert idx == 1
        
        idx = sp.get_stage_index("generate", "generating")
        assert idx == 2
        
        idx = sp.get_stage_index("generate", "nonexistent")
        assert idx == -1
    
    def test_time_formatting(self):
        """Test time formatting"""
        sp = StageProgress()
        
        assert sp._format_time(3) == "finishing up..."
        assert sp._format_time(30) == "~30s"
        assert sp._format_time(75) == "~1 min"
        assert sp._format_time(150) == "~2 min"  # Round down from 2.5
    
    def test_estimate_without_history(self):
        """Test time estimation without historical data"""
        sp = StageProgress(None)  # No Redis
        
        estimate = sp.estimate_time_remaining("generate", "uploading")
        
        assert 'seconds' in estimate
        assert 'formatted' in estimate
        assert 'confidence' in estimate
        assert estimate['confidence'] == 'low'  # No history
    
    def test_record_duration(self):
        """Test recording stage duration"""
        mock_redis = Mock()
        sp = StageProgress(mock_redis)
        
        sp.record_stage_duration("generate", "uploading", 4.5)
        
        # Verify Redis calls
        mock_redis.lpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.expire.assert_called_once()


class TestSSEFormatting:
    """Test SSE message formatting"""
    
    def test_format_sse_message(self):
        """Test SSE message formatting"""
        data = {"status": "PROGRESS", "progress": 50}
        message = format_sse_message(data)
        
        assert "event: message\n" in message
        assert "data: " in message
        assert "\n\n" in message  # SSE requires double newline
        
        # Verify JSON is valid
        json_part = message.split("data: ")[1].split("\n")[0]
        parsed = json.loads(json_part)
        assert parsed['status'] == "PROGRESS"
        assert parsed['progress'] == 50
    
    def test_format_sse_message_custom_event(self):
        """Test SSE message with custom event type"""
        data = {"heartbeat": True}
        message = format_sse_message(data, event="heartbeat")
        
        assert "event: heartbeat\n" in message


class TestTaskStages:
    """Test task stage definitions"""
    
    def test_all_task_types_defined(self):
        """Test that expected task types have stages defined"""
        assert "generate" in TASK_STAGES
        assert "extend" in TASK_STAGES
        assert "merge" in TASK_STAGES
    
    def test_stage_structure(self):
        """Test each stage has required fields"""
        for task_type, stages in TASK_STAGES.items():
            for stage in stages:
                assert 'id' in stage
                assert 'label' in stage
                assert 'duration_estimate' in stage
                assert 'icon' in stage
                
                # Validate types
                assert isinstance(stage['id'], str)
                assert isinstance(stage['label'], str)
                assert isinstance(stage['duration_estimate'], (int, float))
                assert isinstance(stage['icon'], str)
    
    def test_generate_stages(self):
        """Test generate task has expected stages"""
        stages = TASK_STAGES["generate"]
        stage_ids = [s['id'] for s in stages]
        
        assert 'validating' in stage_ids
        assert 'uploading' in stage_ids
        assert 'generating' in stage_ids
        assert 'downloading' in stage_ids
        assert 'finalizing' in stage_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
