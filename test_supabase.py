#!/usr/bin/env python3
"""
Quick test script to verify Supabase configuration.
"""
import os
import time
from dotenv import load_dotenv

# Load environment variables FIRST before importing supabase_storage
load_dotenv()

import supabase_storage

def test_supabase():
    print("=" * 60)
    print("Supabase Configuration Test")
    print("=" * 60)
    
    # Check environment variables
    print("\n1. Environment Variables:")
    print(f"   SUPABASE_URL: {os.getenv('SUPABASE_URL', 'NOT SET')}")
    print(f"   SUPABASE_SERVICE_ROLE_KEY: {'SET' if os.getenv('SUPABASE_SERVICE_ROLE_KEY') else 'NOT SET'}")
    print(f"   SUPABASE_BUCKET_NAME: {os.getenv('SUPABASE_BUCKET_NAME', 'uploads')}")
    
    # Check if Supabase is configured
    print("\n2. Supabase Client Status:")
    is_configured = supabase_storage.is_supabase_configured()
    print(f"   Configured: {is_configured}")
    
    if not is_configured:
        error = supabase_storage.get_initialization_error()
        print(f"   Error: {error}")
        print("\n❌ Supabase is NOT working")
        return False
    
    # Try a simple test upload
    print("\n3. Testing Upload:")
    test_data = b"Hello, Supabase!"
    # Use a unique path per run to avoid 409 "resource already exists" errors
    unique_suffix = os.getenv("SUPABASE_TEST_SUFFIX") or str(int(time.time()))
    test_path = f"test/connection_test_{unique_suffix}.txt"
    
    try:
        print(f"   Upload path: {test_path}")
        public_url, error = supabase_storage.upload_bytes_to_supabase(
            storage_path=test_path,
            file_bytes=test_data,
            content_type="text/plain"
        )
        
        if error:
            print(f"   ❌ Upload failed: {error}")
            return False
        
        print(f"   ✅ Upload successful!")
        print(f"   Public URL: {public_url}")
        
        print("\n" + "=" * 60)
        print("✅ Supabase is working correctly!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"   ❌ Upload failed with exception: {e}")
        return False

if __name__ == "__main__":
    success = test_supabase()
    exit(0 if success else 1)
