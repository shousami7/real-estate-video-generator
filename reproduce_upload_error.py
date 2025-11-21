import os
import time
import logging

try:
    import httpx
    import httpcore
except ImportError:
    httpx = None
    httpcore = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load .env manually
try:
    with open('.env', 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key] = value
except Exception as e:
    logger.warning(f"Could not load .env file: {e}")

from supabase_storage import upload_bytes_to_supabase, is_supabase_configured

def test_upload():
    if not is_supabase_configured():
        logger.error("Supabase is not configured.")
        return

    logger.info("Starting upload test...")
    
    # Create a dummy file (1MB)
    file_content = os.urandom(1024 * 1024)
    
    try:
        url, error = upload_bytes_to_supabase(
            storage_path="test_upload_1mb.bin",
            file_bytes=file_content,
            content_type="application/octet-stream"
        )
        
        if error:
            logger.error(f"Upload failed: {error}")
        else:
            logger.info(f"Upload successful! URL: {url}")
            
    except Exception as e:
        logger.exception(f"Exception during upload: {e}")

if __name__ == "__main__":
    test_upload()
