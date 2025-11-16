import logging
import os
from typing import Optional, Tuple
from urllib.parse import urlparse

from dotenv import load_dotenv

try:
    # The supabase package is optional at runtime (only required when uploads are enabled)
    from supabase import Client, create_client  # type: ignore
except Exception:  # pragma: no cover - fall back if the package is missing
    Client = None  # type: ignore
    create_client = None  # type: ignore

load_dotenv()

logger = logging.getLogger(__name__)

TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_truthy(var_name: str, default: str = "") -> bool:
    return os.getenv(var_name, default).strip().lower() in TRUTHY_VALUES


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "uploads")
SUPABASE_REQUIRED = _env_truthy("SUPABASE_REQUIRED", "false")
_SUPABASE_DISABLED_REASON: Optional[str] = None


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
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY or create_client is None:
        if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
            message = (
                "Supabase credentials not provided; storage uploads disabled."
            )
        else:
            message = "Supabase package not available; install supabase-py to enable uploads."

        logger.debug(message)
        if SUPABASE_REQUIRED:
            raise RuntimeError(
                "Supabase uploads are required (SUPABASE_REQUIRED=1) but cannot be initialized: %s"
                % message
            )
        return None

    parsed_url = urlparse(SUPABASE_URL)
    if not parsed_url.scheme or not parsed_url.netloc:
        logger.warning("Invalid SUPABASE_URL provided; storage uploads will use local disk.")
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
        # If Supabase is unreachable (e.g., network/DNS blocked), disable further attempts.
        _disable_supabase(f"upload failed: {exc}")
        logger.error("Supabase upload failed for %s: %s", storage_path, exc)
        logger.debug("Detailed Supabase upload failure for %s", storage_path, exc_info=True)
        return None, str(exc)


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
