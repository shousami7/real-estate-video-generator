import logging
import os
import json
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse
from urllib.parse import urlparse
from datetime import datetime
import time

try:
    import httpx
    import httpcore
except ImportError:
    httpx = None
    httpcore = None

try:
    # The supabase package is optional at runtime (only required when uploads are enabled)
    from supabase import Client, create_client  # type: ignore
except Exception:  # pragma: no cover - fall back if the package is missing
    Client = None  # type: ignore
    create_client = None  # type: ignore

logger = logging.getLogger(__name__)

TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_truthy(var_name: str, default: str = "") -> bool:
    return os.getenv(var_name, default).strip().lower() in TRUTHY_VALUES


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "uploads")
SUPABASE_REQUIRED = _env_truthy("SUPABASE_REQUIRED", "false")
_SUPABASE_DISABLED_REASON: Optional[str] = None
_PUBLIC_URL_CACHE: Dict[str, Tuple[str, datetime]] = {}
_CACHE_TTL_SECONDS = 3600
_INIT_ERROR: Optional[str] = None


def _disable_supabase(reason: str) -> None:
    """
    Disable Supabase uploads for the current process after a fatal error,
    so we do not keep retrying and spamming stack traces.
    """
    global SUPABASE_CLIENT, _SUPABASE_DISABLED_REASON
    SUPABASE_CLIENT = None
    _SUPABASE_DISABLED_REASON = reason
    logger.warning("Supabase disabled for this process: %s. Falling back to local storage.", reason)
    if SUPABASE_REQUIRED:
        raise RuntimeError(
            "Supabase uploads are required (SUPABASE_REQUIRED=1) but have been disabled: %s" % reason
        )


def _init_supabase_client() -> Optional["Client"]:
    """
    Initialize a Supabase client if credentials are provided.
    """
    global _INIT_ERROR

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or create_client is None:
        if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
            message = (
                "Supabase credentials not provided; storage uploads disabled."
            )
        else:
            message = "Supabase package not available; install supabase-py to enable uploads."

        logger.debug(message)
        _INIT_ERROR = message
        if SUPABASE_REQUIRED:
            raise RuntimeError(
                "Supabase uploads are required (SUPABASE_REQUIRED=1) but cannot be initialized: %s"
                % message
            )
        return None

    parsed_url = urlparse(SUPABASE_URL)
    if not parsed_url.scheme or not parsed_url.netloc:
        message = "Invalid SUPABASE_URL provided; storage uploads will use local disk."
        logger.warning(message)
        _INIT_ERROR = message
        if SUPABASE_REQUIRED:
            raise RuntimeError("Supabase uploads are required but SUPABASE_URL is invalid: %s" % SUPABASE_URL)
        return None

    try:
        client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        logger.info("Supabase client initialized")
        return client
    except Exception:
        logger.exception("Failed to initialize Supabase client; falling back to local storage.")
        if SUPABASE_REQUIRED:
            raise RuntimeError(
                "Supabase uploads are required (SUPABASE_REQUIRED=1) but the client could not be created."
            )
        return None


SUPABASE_CLIENT: Optional["Client"] = _init_supabase_client()


def is_supabase_configured() -> bool:
    """
    Returns True when the Supabase client is available.
    """
    return SUPABASE_CLIENT is not None


def is_supabase_required() -> bool:
    """Return True when SUPABASE_REQUIRED=1 (local fallback should be disabled)."""
    return SUPABASE_REQUIRED


def get_initialization_error() -> Optional[str]:
    """Return the reason why Supabase client initialization failed, if any."""
    return _INIT_ERROR


def get_supabase_status() -> Dict[str, Any]:
    """
    Get current Supabase configuration status with user-friendly messages.
    
    Returns:
        {
            "configured": bool,  # Whether Supabase client is available
            "required": bool,  # Whether SUPABASE_REQUIRED=1
            "mode": str,  # "supabase" | "local" | "error"
            "message": str,  # User-friendly message
            "details": str | None,  # Technical details (error message)
        }
    """
    configured = is_supabase_configured()
    required = is_supabase_required()
    
    # Determine mode and message
    if configured:
        return {
            "configured": True,
            "required": required,
            "mode": "supabase",
            "message": "Cloud storage is active. Files are automatically backed up.",
            "details": None,
        }
    
    # Not configured - determine why
    if _SUPABASE_DISABLED_REASON:
        # Supabase was disabled due to repeated failures
        return {
            "configured": False,
            "required": required,
            "mode": "local",
            "message": "Cloud storage temporarily disabled due to connection issues",
            "details": _SUPABASE_DISABLED_REASON,
        }
    
    init_error = get_initialization_error()
    
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        # Credentials not configured
        return {
            "configured": False,
            "required": required,
            "mode": "local",
            "message": "Cloud storage not configured",
            "details": "SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY environment variables are not set",
        }
    
    # Credentials exist but initialization failed (connection error, invalid URL, etc.)
    return {
        "configured": False,
        "required": required,
        "mode": "error",
        "message": "Unable to connect to cloud storage",
        "details": init_error or "Unknown initialization error",
    }


def upload_bytes_to_supabase(
    storage_path: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    cache_control: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Upload raw bytes to Supabase Storage. Returns (public_url, error_message).
    """
    if _SUPABASE_DISABLED_REASON:
        return None, _SUPABASE_DISABLED_REASON

    client = SUPABASE_CLIENT
    if not client:
        return None, "Supabase client is not configured."

    file_options = {
        "content-type": content_type or "application/octet-stream",
    }
    if cache_control:
        file_options["cache-control"] = cache_control

    # Retry logic
    max_retries = 5
    last_exception = None

    for attempt in range(max_retries):
        try:
            upload_response = client.storage.from_(SUPABASE_BUCKET_NAME).upload(
                path=storage_path,
                file=file_bytes,
                file_options=file_options,
            )

            response_error = None
            if isinstance(upload_response, dict):
                response_error = upload_response.get("error")
            else:
                response_error = getattr(upload_response, "error", None)

            if response_error:
                if isinstance(response_error, dict):
                    error_message = response_error.get("message", "Unknown Supabase upload error")
                else:
                    error_message = str(response_error)
                logger.error("Supabase upload error for %s: %s", storage_path, error_message)
                raise RuntimeError(error_message)

            public_url_response = client.storage.from_(SUPABASE_BUCKET_NAME).get_public_url(storage_path)
            public_url = None
            if isinstance(public_url_response, dict):
                data = public_url_response.get("data") or {}
                public_url = data.get("publicUrl") or data.get("publicURL")
            elif isinstance(public_url_response, str):
                public_url = public_url_response

            if not public_url:
                raise RuntimeError("Failed to resolve Supabase public URL.")

            return public_url, None

        except Exception as exc:
            last_exception = exc
            is_last_attempt = attempt == max_retries - 1
            
            # Check if it's a connection/protocol error that is worth retrying
            should_retry = False
            exc_str = str(exc)
            if httpx and isinstance(exc, (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
                should_retry = True
            elif httpcore and isinstance(exc, (httpcore.RemoteProtocolError, httpcore.ConnectError, httpcore.ReadTimeout, httpcore.WriteTimeout)):
                should_retry = True
            elif "Server disconnected" in exc_str or "Connection refused" in exc_str or "timed out" in exc_str.lower():
                should_retry = True
            
            if should_retry and not is_last_attempt:
                # Exponential backoff: 2, 4, 8, 16... seconds
                wait_time = 2 ** (attempt + 1)
                logger.warning(f"Supabase upload failed (attempt {attempt+1}/{max_retries}): {exc}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            # If we reach here, it's a fatal error or we ran out of retries
            if is_last_attempt:
                # Only disable Supabase if it looks like a persistent network/config issue, 
                # but for now we keep the existing behavior of disabling it to be safe,
                # or we can just log it. The original code disabled it.
                # We'll keep the disable logic but only on the final failure.
                _disable_supabase(f"upload failed after {max_retries} attempts: {exc}")
                logger.error("Supabase upload failed for %s: %s", storage_path, exc)
                logger.debug("Detailed Supabase upload failure for %s", storage_path, exc_info=True)
                return None, str(exc)
            
            # If it's not a retryable error (e.g. auth error), fail immediately
            logger.error("Supabase upload failed for %s (non-retryable): %s", storage_path, exc)
            return None, str(exc)
            
    return None, "Upload failed (unknown reason)"


def upload_file_to_supabase(
    storage_path: str,
    local_file_path: str,
    content_type: str = "application/octet-stream",
    cache_control: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Read a local file and upload it to Supabase Storage.
    """
    if not is_supabase_configured():
        return None, "Supabase client is not configured."

    if not os.path.exists(local_file_path):
        return None, f"File not found: {local_file_path}"

    with open(local_file_path, "rb") as source_file:
        file_bytes = source_file.read()

    return upload_bytes_to_supabase(
        storage_path=storage_path,
        file_bytes=file_bytes,
        content_type=content_type,
        cache_control=cache_control,
    )


# -----------------------------------------------------------------------------
# Standard Supabase Folder Structure Helpers
# -----------------------------------------------------------------------------
# Required structure:
#   videos/{video_id}/input/
#   videos/{video_id}/frames_raw/
#   videos/{video_id}/frames_edited/
#   videos/{video_id}/output/
#   videos/{video_id}/logs/
# -----------------------------------------------------------------------------

def build_storage_path(video_id: str, folder: str, filename: str) -> str:
    """
    Build a standardized Supabase storage path.

    Args:
        video_id: Video/session ID
        folder: Folder name (input, output, frames_raw, frames_edited, logs)
        filename: File name

    Returns:
        Standardized path: videos/{video_id}/{folder}/{filename}
    """
    if folder not in {"input", "output", "frames_raw", "frames_edited", "logs"}:
        logger.warning(f"Non-standard folder '{folder}' used in storage path")

    return f"videos/{video_id}/{folder}/{filename}"


def upload_video_file(
    local_path: str,
    video_id: str,
    filename: str,
    folder: str = "output",
    cache_control: Optional[str] = "3600",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Upload a video file to Supabase using standard folder structure.

    Args:
        local_path: Local file path
        video_id: Video/session ID
        filename: Target filename (e.g., "generate_123.mp4")
        folder: Target folder (default: "output")
        cache_control: Cache control header

    Returns:
        Tuple of (public_url, error_message)
    """
    storage_path = build_storage_path(video_id, folder, filename)

    return upload_file_to_supabase(
        storage_path=storage_path,
        local_file_path=local_path,
        content_type="video/mp4",
        cache_control=cache_control,
    )


def upload_frame_file(
    local_path: str,
    video_id: str,
    filename: str,
    folder: str = "frames_raw",
    cache_control: Optional[str] = "3600",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Upload a frame image to Supabase using standard folder structure.

    Args:
        local_path: Local file path
        video_id: Video/session ID
        filename: Target filename (e.g., "frame_00001.png")
        folder: Target folder (frames_raw or frames_edited)
        cache_control: Cache control header

    Returns:
        Tuple of (public_url, error_message)
    """
    if folder not in {"frames_raw", "frames_edited"}:
        logger.warning(f"Unexpected folder for frames: {folder}")

    storage_path = build_storage_path(video_id, folder, filename)

    return upload_file_to_supabase(
        storage_path=storage_path,
        local_file_path=local_path,
        content_type="image/png",
        cache_control=cache_control,
    )


def upload_log_file(
    log_data: dict,
    video_id: str,
    task_id: str,
    cache_control: Optional[str] = "3600",
) -> Tuple[Optional[str], Optional[str]]:
    """
    Upload a task log file to Supabase.

    Args:
        log_data: Dictionary to serialize as JSON
        video_id: Video/session ID
        task_id: Task ID for the log filename
        cache_control: Cache control header

    Returns:
        Tuple of (public_url, error_message)
    """
    filename = f"{task_id}.json"
    storage_path = build_storage_path(video_id, "logs", filename)

    log_bytes = json.dumps(log_data, indent=2).encode("utf-8")

    return upload_bytes_to_supabase(
        storage_path=storage_path,
        file_bytes=log_bytes,
        content_type="application/json",
        cache_control=cache_control,
    )


def get_public_url(video_id: str, folder: str, filename: str) -> Optional[str]:
    """
    Build a public URL for a file in Supabase storage.

    Args:
        video_id: Video/session ID
        folder: Folder name
        filename: File name

    Returns:
        Public URL or None if Supabase is not configured
    """
    if not is_supabase_configured():
        return None

    storage_path = build_storage_path(video_id, folder, filename)
    now = datetime.now()

    # Check cache with TTL
    if storage_path in _PUBLIC_URL_CACHE:
        cached_url, cached_time = _PUBLIC_URL_CACHE[storage_path]
        if (now - cached_time).total_seconds() < _CACHE_TTL_SECONDS:
            return cached_url
        else:
            # Expired
            del _PUBLIC_URL_CACHE[storage_path]

    try:
        client = SUPABASE_CLIENT
        public_url_response = client.storage.from_(SUPABASE_BUCKET_NAME).get_public_url(storage_path)

        if isinstance(public_url_response, dict):
            data = public_url_response.get("data") or {}
            public_url = data.get("publicUrl") or data.get("publicURL")
        elif isinstance(public_url_response, str):
            public_url = public_url_response
        else:
            public_url = None

        if public_url:
            _PUBLIC_URL_CACHE[storage_path] = (public_url, now)
        return public_url
    except Exception as exc:
        logger.error(f"Failed to get public URL for {storage_path}: {exc}")
        return None


def download_log_file(video_id: str, task_id: str) -> Optional[dict]:
    """
    Download and parse a task log file from Supabase.

    Args:
        video_id: Video/session ID
        task_id: Task ID

    Returns:
        Parsed JSON dict or None if not found
    """
    if not is_supabase_configured():
        return None

    client = SUPABASE_CLIENT
    log_path = build_storage_path(video_id, "logs", f"{task_id}.json")

    try:
        log_bytes = client.storage.from_(SUPABASE_BUCKET_NAME).download(log_path)
        if log_bytes:
            return json.loads(log_bytes)
        return None
    except Exception as exc:
        logger.debug(f"Could not download log file {log_path}: {exc}")
        return None


def get_latest_input_video(video_id: str) -> Optional[str]:
    """
    Get the most recent input video for a video_id.

    Priority:
        1. Most recent file in videos/{video_id}/output/
        2. videos/{video_id}/input/initial.mp4

    Args:
        video_id: Video/session ID

    Returns:
        Public URL of the input video, or None if not found
    """
    if not is_supabase_configured():
        logger.warning("Supabase not configured; cannot retrieve input video")
        return None

    client = SUPABASE_CLIENT

    # Try output folder first (most recent)
    try:
        prefix = build_storage_path(video_id, "output", "").rstrip("/")
        output_files = client.storage.from_(SUPABASE_BUCKET_NAME).list(prefix)
        if output_files and len(output_files) > 0:
            # Sort by created_at descending and get the first file
            sorted_files = sorted(output_files, key=lambda x: x.get("created_at", ""), reverse=True)
            latest_file = sorted_files[0]["name"]
            return get_public_url(video_id, "output", latest_file)
    except Exception as exc:
        logger.debug(f"No output files found for {video_id}: {exc}")

    # Fallback to input/initial.mp4
    try:
        input_url = get_public_url(video_id, "input", "initial.mp4")
        if input_url:
            return input_url
    except Exception as exc:
        logger.debug(f"No initial input file found for {video_id}: {exc}")

    logger.warning(f"No input video found for video_id={video_id}")
    return None
