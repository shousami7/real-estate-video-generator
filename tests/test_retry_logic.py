"""
Unit tests for Veo API retry logic with exponential backoff
"""

import pytest
import time
from unittest.mock import Mock, patch
from google.api_core import exceptions as google_exceptions
import requests

# Import the functions we need to test
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from veo_generator import (
    retry_with_exponential_backoff,
    _is_non_retriable_error,
    _format_user_error,
    RETRY_CONFIG,
)


class TestRetryDecorator:
    """Test suite for retry_with_exponential_backoff decorator"""
    
    def test_successful_operation_no_retry(self):
        """Test that successful operations execute without retry"""
        call_count = 0
        
        @retry_with_exponential_backoff(max_retries=3, initial_delay=0.1)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = successful_func()
        assert result == "success"
        assert call_count == 1  # Should only be called once
    
    def test_transient_failure_then_success(self):
        """Test that transient failures are retried and eventually succeed"""
        call_count = 0
        
        @retry_with_exponential_backoff(max_retries=3, initial_delay=0.1)
        def transient_failure_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary network issue")
            return "success"
        
        result = transient_failure_func()
        assert result == "success"
        assert call_count == 3  # Should be called 3 times (2 failures + 1 success)
    
    def test_permanent_failure_exhausts_retries(self):
        """Test that permanent failures exhaust all retries"""
        call_count = 0
        
        @retry_with_exponential_backoff(max_retries=2, initial_delay=0.1)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Always fails")
        
        with pytest.raises(RuntimeError, match="Always fails"):
            always_fails()
        
        assert call_count == 3  # Initial attempt + 2 retries
    
    def test_exponential_backoff_timing(self):
        """Test that exponential backoff increases delay between retries"""
        call_times = []
        
        @retry_with_exponential_backoff(
            max_retries=3,
            initial_delay=0.1,
            max_delay=1.0,
            exponential_base=2.0
        )
        def failing_func():
            call_times.append(time.time())
            raise ConnectionError("Network error")
        
        with pytest.raises(ConnectionError):
            failing_func()
        
        # Verify increasing delays (should be roughly 0.1s, 0.2s, 0.4s)
        assert len(call_times) == 4  # Initial + 3 retries
        
        # Check delays between calls
        delay1 = call_times[1] - call_times[0]
        delay2 = call_times[2] - call_times[1]
        delay3 = call_times[3] - call_times[2]
        
        # Allow some tolerance for timing precision
        assert 0.08 < delay1 < 0.15  # ~0.1s
        assert 0.15 < delay2 < 0.25  # ~0.2s
        assert 0.3 < delay3 < 0.5   # ~0.4s
    
    def test_non_retriable_error_fails_immediately(self):
        """Test that non-retriable errors fail immediately without retry"""
        call_count = 0
        
        @retry_with_exponential_backoff(max_retries=3, initial_delay=0.1)
        def quota_error_func():
            nonlocal call_count
            call_count += 1
            raise google_exceptions.ResourceExhausted("Quota exceeded")
        
        with pytest.raises(google_exceptions.ResourceExhausted):
            quota_error_func()
        
        assert call_count == 1  # Should not retry


class TestNonRetriableErrorDetection:
    """Test suite for _is_non_retriable_error function"""
    
    def test_quota_exhausted_errors(self):
        """Test that quota exhausted errors are non-retriable"""
        error1 = google_exceptions.ResourceExhausted("Quota exceeded")
        error2 = RuntimeError("RESOURCE_EXHAUSTED: quota limit")
        error3 = ValueError("API quota exceeded")
        
        assert _is_non_retriable_error(error1) is True
        assert _is_non_retriable_error(error2) is True
        assert _is_non_retriable_error(error3) is True
    
    def test_authentication_errors(self):
        """Test that authentication errors are non-retriable"""
        error1 = google_exceptions.Unauthenticated("Invalid API key")
        error2 = google_exceptions.PermissionDenied("Access denied")
        error3 = RuntimeError("invalid api key")
        
        assert _is_non_retriable_error(error1) is True
        assert _is_non_retriable_error(error2) is True
        assert _is_non_retriable_error(error3) is True
    
    def test_bad_request_errors(self):
        """Test that bad request errors are generally non-retriable"""
        error1 = google_exceptions.InvalidArgument("Invalid parameter")
        error2 = RuntimeError("400 bad request")
        
        assert _is_non_retriable_error(error1) is True
        assert _is_non_retriable_error(error2) is True
    
    def test_unsupported_feature_errors_are_retriable(self):
        """Test that 'unsupported feature' errors are retriable (for model fallback)"""
        error = google_exceptions.InvalidArgument("Feature unsupported by model")
        assert _is_non_retriable_error(error) is False
    
    def test_retriable_errors(self):
        """Test that transient errors are retriable"""
        error1 = ConnectionError("Network timeout")
        error2 = requests.exceptions.Timeout("Request timeout")
        error3 = RuntimeError("503 Service Unavailable")
        
        assert _is_non_retriable_error(error1) is False
        assert _is_non_retriable_error(error2) is False
        assert _is_non_retriable_error(error3) is False
    
    def test_rate_limit_errors_are_retriable(self):
        """Test that rate limit errors (429) are retriable"""
        mock_response = Mock()
        mock_response.status_code = 429
        error = requests.exceptions.HTTPError(response=mock_response)
        
        assert _is_non_retriable_error(error) is False


class TestUserErrorFormatting:
    """Test suite for _format_user_error function"""
    
    def test_connection_error_formatting(self):
        """Test formatting of connection errors"""
        error = ConnectionError("Connection refused")
        message = _format_user_error(error, "video upload", 3)
        
        assert "Connection failed" in message
        assert "video upload" in message
        assert "internet connection" in message
    
    def test_timeout_error_formatting(self):
        """Test formatting of timeout errors"""
        error = requests.exceptions.Timeout("Request timed out")
        message = _format_user_error(error, "file download", 2)
        
        assert "timed out" in message
        assert "file download" in message
    
    def test_rate_limit_error_formatting(self):
        """Test formatting of rate limit errors"""
        error = ValueError("429 rate limit exceeded")
        message = _format_user_error(error, "API call", 4)
        
        assert "rate limit" in message
        assert "API call" in message
    
    def test_quota_error_formatting(self):
        """Test formatting of quota errors"""
        error = google_exceptions.ResourceExhausted("Quota exceeded")
        message = _format_user_error(error, "video generation", 3)
        
        assert "quota" in message.lower()
        assert "3 attempt" in message
        assert "https://aistudio.google.com/apikey" in message
    
    def test_authentication_error_formatting(self):
        """Test formatting of authentication errors"""
        error = RuntimeError("Invalid API key")
        message = _format_user_error(error, "image upload", 1)
        
        assert "Authentication failed" in message
        assert "API key" in message
    
    def test_server_error_formatting(self):
        """Test formatting of server errors"""
        error = RuntimeError("503 Service Unavailable")
        message = _format_user_error(error, "video processing", 3)
        
        assert "temporarily unavailable" in message
        assert "3 attempt" in message
    
    def test_generic_error_formatting(self):
        """Test formatting of generic errors"""
        error = RuntimeError("Unknown error occurred")
        message = _format_user_error(error, "operation", 2)
        
        assert "2 attempt" in message
        assert "Unknown error occurred" in message


class TestRetryConfiguration:
    """Test suite for retry configuration"""
    
    def test_retry_config_structure(self):
        """Test that RETRY_CONFIG has the expected structure"""
        assert "file_upload" in RETRY_CONFIG
        assert "api_call" in RETRY_CONFIG
        assert "download" in RETRY_CONFIG
        
        for config_type in ["file_upload", "api_call", "download"]:
            config = RETRY_CONFIG[config_type]
            assert "max_retries" in config
            assert "initial_delay" in config
            assert "max_delay" in config
            assert isinstance(config["max_retries"], int)
            assert isinstance(config["initial_delay"], float)
            assert isinstance(config["max_delay"], float)
    
    def test_retry_config_values(self):
        """Test that retry configuration values are reasonable"""
        # File upload config
        assert RETRY_CONFIG["file_upload"]["max_retries"] >= 1
        assert RETRY_CONFIG["file_upload"]["initial_delay"] > 0
        assert RETRY_CONFIG["file_upload"]["max_delay"] > RETRY_CONFIG["file_upload"]["initial_delay"]
        
        # API call config
        assert RETRY_CONFIG["api_call"]["max_retries"] >= 1
        assert RETRY_CONFIG["api_call"]["initial_delay"] > 0
        assert RETRY_CONFIG["api_call"]["max_delay"] > RETRY_CONFIG["api_call"]["initial_delay"]
        
        # Download config
        assert RETRY_CONFIG["download"]["max_retries"] >= 1
        assert RETRY_CONFIG["download"]["initial_delay"] > 0
        assert RETRY_CONFIG["download"]["max_delay"] > RETRY_CONFIG["download"]["initial_delay"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
