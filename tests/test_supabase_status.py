"""
Tests for Supabase graceful degradation - storage status API
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase_storage import get_supabase_status


class TestSupabaseStatus:
    """Test suite for Supabase status API"""
    
    def test_status_when_configured(self):
        """Test status when Supabase is properly configured"""
        with patch('supabase_storage.is_supabase_configured', return_value=True), \
             patch('supabase_storage.is_supabase_required', return_value=False):
            
            status = get_supabase_status()
            
            assert status['configured'] is True
            assert status['mode'] == 'supabase'
            assert status['details'] is None
            assert 'active' in status['message'].lower()
    
    def test_status_when_not_configured_no_credentials(self):
        """Test status when Supabase credentials are not set"""
        with patch('supabase_storage.is_supabase_configured', return_value=False), \
             patch('supabase_storage.is_supabase_required', return_value=False), \
             patch('supabase_storage.SUPABASE_URL', None), \
             patch('supabase_storage.SUPABASE_SERVICE_ROLE_KEY', None), \
             patch('supabase_storage._SUPABASE_DISABLED_REASON', None), \
             patch('supabase_storage.get_initialization_error', return_value=None):
            
            status = get_supabase_status()
            
            assert status['configured'] is False
            assert status['mode'] == 'local'
            assert 'not configured' in status['message'].lower()
            assert 'not set' in status['details'].lower()
    
    def test_status_when_temporarily_disabled(self):
        """Test status when Supabase was disabled due to failures"""
        with patch('supabase_storage.is_supabase_configured', return_value=False), \
             patch('supabase_storage.is_supabase_required', return_value=False), \
             patch('supabase_storage._SUPABASE_DISABLED_REASON', 'Connection failed after 5 retries'):
            
            status = get_supabase_status()
            
            assert status['configured'] is False
            assert status['mode'] == 'local'
            assert 'disabled' in status['message'].lower()
            assert 'Connection failed' in status['details']
    
    def test_status_when_connection_error(self):
        """Test status when credentials exist but connection fails"""
        with patch('supabase_storage.is_supabase_configured', return_value=False), \
             patch('supabase_storage.is_supabase_required', return_value=False), \
             patch('supabase_storage.SUPABASE_URL', 'https://test.supabase.co'), \
             patch('supabase_storage.SUPABASE_SERVICE_ROLE_KEY', 'test-key'), \
             patch('supabase_storage._SUPABASE_DISABLED_REASON', None), \
             patch('supabase_storage.get_initialization_error', return_value='Invalid SUPABASE_URL'):
            
            status = get_supabase_status()
            
            assert status['configured'] is False
            assert status['mode'] == 'error'
            assert 'unable to connect' in status['message'].lower()
            assert status['details'] == 'Invalid SUPABASE_URL'
    
    def test_required_flag_reflected(self):
        """Test that SUPABASE_REQUIRED flag is included in status"""
        with patch('supabase_storage.is_supabase_configured', return_value=True), \
             patch('supabase_storage.is_supabase_required', return_value=True):
            
            status = get_supabase_status()
            
            assert status['required'] is True
    
    def test_status_structure(self):
        """Test that status has all required fields"""
        with patch('supabase_storage.is_supabase_configured', return_value=True), \
             patch('supabase_storage.is_supabase_required', return_value=False):
            
            status = get_supabase_status()
            
            # Verify all required keys exist
            required_keys = {'configured', 'required', 'mode', 'message', 'details'}
            assert set(status.keys()) == required_keys
            
            # Verify types
            assert isinstance(status['configured'], bool)
            assert isinstance(status['required'], bool)
            assert isinstance(status['mode'], str)
            assert isinstance(status['message'], str)
            assert status['details'] is None or isinstance(status['details'], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
