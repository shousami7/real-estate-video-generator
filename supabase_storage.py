import logging
import os
from typing import Optional, Tuple

from dotenv import load_dotenv

try:
    # The supabase package is optional at runtime (only required when uploads are enabled)
    from supabase import Client, create_client  # type: ignore
except Exception:  # pragma: no cover - fall back if the package is missing
    Client = None  # type: ignore
    create_client = None  # type: ignore

load_dotenv()

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "uploads")


def _init_supabase_client() -> Optional["Client"]:
    """
    Initialize a Supabase client if credentials are provided.
    """
    if not SUPABASE_URL or not SUPABASE_KEY or create_client is None:
        if not (SUPABASE_URL and SUPABASE_KEY):
            logger.debug("Supabase credentials not provided; storage uploads disabled.")
        return None

    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("Supabase client initialized")
        return client
    except Exception:
        logger.exception("Failed to initialize Supabase client; falling back to local storage.")
        return None


SUPABASE_CLIENT: Optional["Client"] = _init_supabase_client()


def is_supabase_configured() -> bool:
    """
    Returns True when the Supabase client is available.
    """
    return SUPABASE_CLIENT is not None


def upload_bytes_to_supabase(
    storage_path: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
    cache_control: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Upload raw bytes to Supabase Storage. Returns (public_url, error_message).
    """
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
        logger.warning("Supabase upload failed for %s: %s", storage_path, exc, exc_info=True)
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
