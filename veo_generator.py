"""
Google Veo Video Generator Module
Handles image-to-video generation using Google Generative AI (Veo) API
Supports both Google AI Studio (API key) and Vertex AI (GCP project)
"""

from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions
import os
import time
from typing import Optional, Dict, Any
from pathlib import Path
import logging
import requests
from urllib.parse import urlparse
try:
    from google.auth.transport.requests import Request
    from google.auth import default as get_default_credentials
    HAS_GOOGLE_AUTH = True
except ImportError:
    HAS_GOOGLE_AUTH = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VeoVideoGenerator:
    """
    Manages video generation using Google Generative AI Veo Image-to-Video API

    Supports two modes:
    1. Google AI Studio (API key authentication)
    2. Vertex AI (GCP project + service account authentication)
    """

    # Available Veo models (3.0 general supports image conditioning)
    VEO_MODEL_STUDIO = "veo-3.0-generate-001"  # Google AI Studio (General)
    VEO_MODEL_VERTEX = "veo-3.0-generate-001"  # Vertex AI (General)
    # If an override points to a model without image conditioning (e.g. 3.0 Fast),
    # fall back to a compatible model by default.
    VEO_IMAGE_CONDITIONING_FALLBACK = "veo-3.0-generate-001"

    def __init__(
        self,
        api_key: Optional[str] = None,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        use_vertex_ai: bool = False
    ):
        """
        Initialize the Veo Video Generator

        Args:
            api_key: Google AI API key (for Google AI Studio mode)
            project_id: GCP Project ID (for Vertex AI mode)
            location: GCP region (default: us-central1)
            use_vertex_ai: Whether to use Vertex AI instead of Google AI Studio
        """
        self.use_vertex_ai = use_vertex_ai
        self.project_id = project_id
        self.location = location
        self.api_key = api_key

        # Determine which model to use
        env_model_override = os.getenv("VEO_MODEL_OVERRIDE")
        self.model = env_model_override or (
            self.VEO_MODEL_VERTEX if use_vertex_ai else self.VEO_MODEL_STUDIO
        )

        # Fallback model when the active model does not support image/video
        # references. This can be overridden via env for future upgrades.
        self.image_conditioning_model = os.getenv(
            "VEO_IMAGE_MODEL_OVERRIDE", self.VEO_IMAGE_CONDITIONING_FALLBACK
        )

        # Initialize client based on mode
        if use_vertex_ai:
            if not project_id:
                raise ValueError("project_id is required for Vertex AI mode")

            logger.info(f"Initializing Vertex AI client (Project: {project_id}, Location: {location})")
            self.client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location
            )
            logger.info(f"✓ Vertex AI Mode - Using GCP credits")
            logger.info(f"✓ Model: {self.model}")
            logger.info(f"✓ Project: {project_id}")
            logger.info(f"✓ Location: {location}")
        else:
            if not api_key:
                raise ValueError("api_key is required for Google AI Studio mode")

            logger.info("Initializing Google AI Studio client")
            self.client = genai.Client(api_key=api_key)
            logger.info(f"✓ Google AI Studio Mode")
            logger.info(f"✓ Model: {self.model}")

        logger.info(f"Veo Video Generator initialized successfully")

    def upload_image(self, image_path: str):
        """
        Upload image to Google AI storage

        Args:
            image_path: Path to the image file

        Returns:
            Uploaded file object
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        logger.info(f"Uploading image: {image_path}")

        try:
            # Upload file to Google AI
            uploaded_file = self.client.files.upload(file=image_path)
            logger.info(f"Image uploaded successfully: {uploaded_file.name}")

            # Wait for file to be processed with timeout
            logger.info("Waiting for image to be processed...")
            poll_start = time.time()
            max_wait = 60  # 60 second timeout
            poll_interval = 5  # 5 second polling interval

            while uploaded_file.state == "PROCESSING":
                if time.time() - poll_start > max_wait:
                    raise TimeoutError(f"Image processing timed out after {max_wait} seconds")

                logger.info(f"Image still processing... (polling every {poll_interval}s)")
                time.sleep(poll_interval)
                uploaded_file = self.client.files.get(uploaded_file.name)

            if uploaded_file.state == "FAILED":
                raise ValueError(f"Image processing failed")

            logger.info("Image ready for video generation")
            return uploaded_file

        except Exception as e:
            logger.error(f"Failed to upload image: {e}")
            raise

    def _select_model(self, needs_reference_input: bool) -> str:
        """Return the best model for the current request."""

        if not needs_reference_input:
            return self.model

        # Only Veo 3.0 Fast lacks image/video references; fall back when that
        # model is explicitly selected.
        unsupported_for_images = {"veo-3.0-fast-generate-001"}

        if self.model in unsupported_for_images:
            if self.image_conditioning_model == self.model:
                return self.model

            logger.warning(
                "Model %s does not support image/video references. Falling back to %s",
                self.model,
                self.image_conditioning_model,
            )
            return self.image_conditioning_model

        return self.model

    def generate_video(
        self,
        image_path: Optional[str],
        prompt: str,
        duration: str = "8s",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        generate_audio: bool = False,  # Veo 2.0はオーディオ非対応のためFalseに変更
        previous_video: Any = None,
    ) -> Any:
        """
        Generate video (or extend an existing one) using Google Veo.

        Args:
            image_path: Path to the image file (required for the first segment)
            prompt: Text prompt describing the desired video motion
            duration: Informational string for logging (API uses default length per segment)
            aspect_ratio: Video aspect ratio ("16:9" or "9:16")
            resolution: Video resolution ("720p" or "1080p")
            generate_audio: Whether to generate audio (default: True)
            previous_video: Response video object from a prior generate_videos call for scene extension

        Returns:
            Operation object for video generation
        """
        mode_name = "Vertex AI" if self.use_vertex_ai else "Google AI Studio"
        logger.info(f"Submitting video generation request ({mode_name})")
        logger.info(f"Model: {self.model}")
        logger.info(f"Prompt: {prompt[:100]}...")
        logger.info(
            f"Settings: {duration}, {aspect_ratio}, {resolution}, "
            f"{'extension' if previous_video else 'new video'}"
        )

        try:
            if previous_video is None:
                if not image_path:
                    raise ValueError("image_path is required for the first segment")
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file not found: {image_path}")

            # Generate video using Veo
            logger.info(f"Generating video with {mode_name}...")

            needs_reference = bool(image_path) or previous_video is not None

            request_kwargs = {
                "model": self._select_model(needs_reference_input=needs_reference),
                "prompt": prompt,
            }

            if previous_video is not None:
                request_kwargs["video"] = self._normalize_video_reference(previous_video)
            else:
                logger.info(f"Loading image from: {image_path}")
                request_kwargs["image"] = types.Image.from_file(location=image_path)
                logger.info("Image loaded successfully")

            request_kwargs["config"] = types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio
            )

            operation = self.client.models.generate_videos(**request_kwargs)
            logger.info(f"Video generation started. Operation name: {operation.name}")

            # Poll until video generation completes
            logger.info("Waiting for video generation to complete...")
            poll_count = 0
            max_polls = 10  # 5 minutes with 30 second intervals

            while not operation.done:
                time.sleep(30)
                poll_count += 1

                # Get updated operation status
                operation = self.client.operations.get(operation)

                if poll_count % 2 == 0:  # Log every 60 seconds
                    logger.info(f"Still generating... ({poll_count * 30}s elapsed)")

                if poll_count >= max_polls:
                    raise TimeoutError("Video generation timed out after 5 minutes")

            logger.info("Video generation completed!")
            return operation

        except Exception as e:
            error_str = str(e)
            error_type = type(e).__name__
            
            # 429エラーまたはクォータ超過エラーをチェック
            is_quota_error = (
                isinstance(e, google_exceptions.ResourceExhausted) or
                "429" in error_str or 
                "RESOURCE_EXHAUSTED" in error_str or 
                "quota" in error_str.lower() or
                error_type == "ResourceExhausted"
            )
            
            if is_quota_error:
                # エラーメッセージから詳細を抽出
                error_details = ""
                if hasattr(e, 'message'):
                    error_details = str(e.message)
                elif hasattr(e, 'details'):
                    error_details = str(e.details)
                else:
                    error_details = error_str
                
                error_msg = (
                    "APIクォータ制限に達しました\n\n"
                    "Google AI APIの使用量制限を超えています。\n\n"
                    "対処方法:\n"
                    "1. Google AI Studio (https://ai.dev/usage) で使用量を確認\n"
                    "2. プランと請求情報を確認\n"
                    "3. レート制限の詳細: https://ai.google.dev/gemini-api/docs/rate-limits\n"
                    "4. しばらく待ってから再度お試しください（通常、クォータは時間単位または日単位でリセットされます）\n"
                )
                logger.error(f"API quota exceeded: {error_str}")
                logger.error(f"Error details: {error_details}")
                raise ValueError(error_msg) from e
            
            logger.error(f"Video generation failed: {e}")
            logger.error(f"Error type: {error_type}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def _download_from_uri(self, uri: str, output_path: str) -> None:
        """
        Download file from URI using HTTP requests with Google API authentication

        Args:
            uri: GCS URI or HTTP(S) URL
            output_path: Path to save the downloaded file
        """
        logger.info(f"Downloading from URI: {uri}")

        try:
            # Normalize Google Cloud Storage URIs to standard HTTPS endpoints
            parsed = urlparse(uri)
            if parsed.scheme in {"gs", "gcs"}:
                bucket = parsed.netloc
                object_path = parsed.path.lstrip("/")
                if not bucket or not object_path:
                    raise ValueError(f"Invalid GCS URI: {uri}")
                uri = f"https://storage.googleapis.com/{bucket}/{object_path}"
                logger.info(f"Converted GCS URI to HTTPS endpoint: {uri}")

            # Prepare authentication headers based on mode
            headers = {}

            if self.use_vertex_ai:
                # For Vertex AI, try to use GCP authentication
                logger.info("Using Vertex AI mode - preparing GCP authentication")

                # First, try unauthenticated (pre-signed URLs)
                # If that fails, we'll try with credentials
                if HAS_GOOGLE_AUTH:
                    try:
                        credentials, project = get_default_credentials()
                        if credentials.token is None:
                            credentials.refresh(Request())
                        headers['Authorization'] = f'Bearer {credentials.token}'
                        logger.info("Using GCP OAuth2 credentials for download")
                    except Exception as auth_error:
                        logger.warning(f"Could not get GCP credentials, trying unauthenticated: {auth_error}")
                else:
                    logger.info("google-auth not available, attempting unauthenticated download")
            else:
                # For Google AI Studio, use API key
                if not self.api_key:
                    raise ValueError("API key is required for Google AI Studio mode downloads")
                headers['X-Goog-API-Key'] = self.api_key
                logger.info("Using Google AI Studio mode with API key authentication")

            logger.info("Making request to download video...")

            # Download using requests with authentication
            response = requests.get(uri, headers=headers, timeout=300, stream=True)

            logger.info(f"Response status code: {response.status_code}")
            response.raise_for_status()

            # Write to file in chunks
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"File downloaded successfully from URI")

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error {e.response.status_code}")
            try:
                logger.error(f"Response body: {e.response.text}")
            except:
                pass
            logger.error(f"Failed to download from URI {uri}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to download from URI {uri}: {e}")
            raise

    def download_video(self, operation, output_path: str) -> str:
        """
        Download generated video from completed operation

        Args:
            operation: Completed video generation operation
            output_path: Path to save the video

        Returns:
            Path to the downloaded video
        """
        logger.info(f"Downloading generated video...")

        try:
            # Create directory if it doesn't exist
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            # Check if operation is done
            if not operation.done:
                raise ValueError("Operation is not complete yet")

            # Extract video from operation response
            # The response structure may vary, so we'll handle different cases
            if not hasattr(operation, 'response'):
                raise ValueError("Operation does not have a response")

            response = operation.response
            logger.info(f"Operation response type: {type(response)}")
            logger.info(f"Operation response attributes: {dir(response)}")

            # Try to extract video file information from response
            video_file = self._extract_generated_video(response)

            if not video_file:
                # Log response for debugging
                logger.error(f"Could not find video in response. Response: {response}")
                raise ValueError("No video file found in operation response")

            # Extract URI from video file object
            file_uri = None
            if hasattr(video_file, 'uri'):
                file_uri = video_file.uri
                logger.info(f"Found video URI: {file_uri}")
            elif hasattr(video_file, 'name'):
                file_uri = video_file.name
                logger.info(f"Found video name (will try as URI): {file_uri}")
            elif isinstance(video_file, str):
                file_uri = video_file
                logger.info(f"Video file is string: {file_uri}")
            else:
                raise ValueError(f"Unable to extract file URI from video_file: {type(video_file)}")

            logger.info(f"Downloading video from: {file_uri}")

            # Try to download using SDK native methods first
            sdk_download_successful = False

            # Method 1: Try to use client.files.download if available
            try:
                if hasattr(self.client, 'files') and hasattr(self.client.files, 'download'):
                    logger.info("Attempting download using genai SDK native method...")
                    downloaded_file = self.client.files.download(file_uri)
                    with open(output_path, 'wb') as f:
                        f.write(downloaded_file)
                    sdk_download_successful = True
                    logger.info("Successfully downloaded using SDK native method")
            except Exception as sdk_error:
                logger.warning(f"SDK native download failed: {sdk_error}")

            # Method 2: Check if video_file has video data directly
            if not sdk_download_successful and hasattr(video_file, 'video_data'):
                try:
                    logger.info("Attempting to extract video data from video_file object...")
                    with open(output_path, 'wb') as f:
                        f.write(video_file.video_data)
                    sdk_download_successful = True
                    logger.info("Successfully extracted video data from object")
                except Exception as data_error:
                    logger.warning(f"Failed to extract video data: {data_error}")

            # If SDK download was successful, verify and return
            if sdk_download_successful:
                if os.path.exists(output_path):
                    file_size = os.path.getsize(output_path)
                    logger.info(f"Video downloaded successfully: {output_path} ({file_size} bytes)")
                    return output_path
                else:
                    logger.warning("SDK download reported success but file not found, falling back to HTTP download")
                    sdk_download_successful = False

            # Method 3: Fall back to HTTP download with retry logic
            if not sdk_download_successful:
                logger.info("Falling back to HTTP download method...")
                max_retries = 2
                retry_delay = 2  # seconds
                logger.info(f"Download configured with {max_retries} max retries")

                for attempt in range(max_retries):
                    try:
                        logger.info(f"Download attempt {attempt + 1}/{max_retries}...")

                        # Download from URI
                        self._download_from_uri(file_uri, output_path)

                        # Verify file was written
                        if not os.path.exists(output_path):
                            raise IOError(f"Failed to write file: {output_path}")

                        file_size = os.path.getsize(output_path)
                        if file_size == 0:
                            raise IOError(f"Downloaded file is empty: {output_path}")

                        logger.info(f"Video downloaded successfully: {output_path} ({file_size} bytes)")
                        return output_path

                    except (BrokenPipeError, ConnectionError, IOError, requests.exceptions.RequestException) as e:
                        logger.warning(f"Download attempt {attempt + 1} failed: {type(e).__name__}: {e}")

                        # Clean up partial file if it exists
                        if os.path.exists(output_path):
                            try:
                                os.remove(output_path)
                                logger.info(f"Removed partial file: {output_path}")
                            except Exception as cleanup_error:
                                logger.warning(f"Failed to remove partial file: {cleanup_error}")

                        if attempt < max_retries - 1:
                            logger.info(f"Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            raise RuntimeError(f"Failed to download video after {max_retries} attempts") from e

        except Exception as e:
            logger.error(f"Failed to download video: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def _extract_generated_video(self, response: Any) -> Optional[Any]:
        """
        Extract the generated video object from a response payload.

        The Google GenAI response shape can vary slightly between releases,
        so we normalize the extraction in one place.
        """
        if not response:
            return None

        if hasattr(response, "generated_videos") and response.generated_videos:
            video_data = response.generated_videos[0]
            if hasattr(video_data, "video"):
                return video_data.video

        if hasattr(response, "video"):
            return response.video

        if hasattr(response, "videos") and response.videos:
            return response.videos[0]

        if hasattr(response, "file"):
            return response.file

        return None

    def _normalize_video_reference(self, video_source: Any) -> types.Video:
        """
        Convert a response video payload into a `types.Video` reference that can
        be reused for scene extension requests.
        """
        if isinstance(video_source, types.Video):
            return video_source

        # Some responses wrap the actual video inside a `video` attribute
        if hasattr(video_source, "video") and video_source.video:
            return self._normalize_video_reference(video_source.video)

        uri = None
        mime_type = "video/mp4"

        if isinstance(video_source, str):
            uri = video_source
        elif isinstance(video_source, dict):
            uri = video_source.get("uri") or video_source.get("name")
            mime_type = video_source.get("mime_type", mime_type)
        else:
            uri = getattr(video_source, "uri", None) or getattr(video_source, "name", None)
            mime_type = getattr(video_source, "mime_type", mime_type)

        if not uri:
            raise ValueError("Unable to normalize video reference: missing URI")

        return types.Video(uri=uri, mime_type=mime_type)

    def generate_from_image_file(
        self,
        image_path: str,
        prompt: str,
        output_path: str,
        duration: str = "8s",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        generate_audio: bool = True
    ) -> str:
        """
        Complete workflow: generate (and optionally extend) video from image, then download result.

        Args:
            image_path: Path to input image
            prompt: Video generation prompt
            output_path: Path to save the generated video
            duration: Target duration (e.g. "10s" or 10) - Veo 3.0 fast supports extension up to ~141s
            aspect_ratio: Video aspect ratio ("16:9" or "9:16")
            resolution: Video resolution ("720p" or "1080p")
            generate_audio: Whether to generate audio

        Returns:
            Path to the downloaded video
        """
        logger.info("="*80)
        logger.info("Starting complete video generation workflow")
        logger.info("="*80)

        # Validate image exists
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        def _parse_duration_seconds(value: Any) -> float:
            if value is None:
                return 8.0
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                cleaned = value.strip().lower()
                if cleaned.endswith("s"):
                    cleaned = cleaned[:-1]
                try:
                    return float(cleaned)
                except ValueError:
                    pass
            return 8.0

        target_seconds = _parse_duration_seconds(duration)
        max_supported = 141.0  # Veo 3.0 fast scene extension limit (empirical)
        if target_seconds > max_supported:
            logger.info(f"Requested duration {target_seconds}s exceeds model limit; clamping to {max_supported}s")
            target_seconds = max_supported

        # Scene extension loop: chain generate_videos calls by feeding the previous video back in.
        total_seconds = 0.0
        segment_index = 0
        previous_video = None
        last_operation = None
        default_segment_len = 8.0  # fallback if API doesn't return duration_seconds

        while total_seconds + 0.1 < target_seconds:
            segment_index += 1
            logger.info(f"Starting segment {segment_index} (current total ~{total_seconds:.2f}s, target {target_seconds:.2f}s)")

            last_operation = self.generate_video(
                image_path=image_path if previous_video is None else None,
                prompt=prompt,
                duration=f"{target_seconds - total_seconds:.2f}s",
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                generate_audio=generate_audio,
                previous_video=previous_video,
            )

            response_video = self._extract_generated_video(getattr(last_operation, "response", None))
            if not response_video:
                raise ValueError("No video returned from generation operation")

            segment_seconds = getattr(response_video, "duration_seconds", None)
            if segment_seconds is None:
                segment_seconds = getattr(response_video, "duration", default_segment_len)
            try:
                segment_seconds = float(segment_seconds)
            except Exception:
                segment_seconds = default_segment_len

            total_seconds += segment_seconds
            previous_video = self._normalize_video_reference(response_video)

            logger.info(
                f"Segment {segment_index} finished: {segment_seconds:.2f}s "
                f"(cumulative {total_seconds:.2f}s)"
            )

            if segment_index > 30:  # safety guard to prevent runaway loops
                logger.warning("Aborting extension loop after 30 segments to avoid runaway generation")
                break

        if last_operation is None:
            raise RuntimeError("Video generation did not start; no operation returned")

        # Download the final extended video
        video_path = self.download_video(last_operation, output_path)

        logger.info("="*80)
        logger.info("Workflow completed successfully!")
        logger.info("="*80)

        return video_path


if __name__ == "__main__":
    # Example usage
    import sys

    if len(sys.argv) < 4:
        print("Usage: python veo_generator.py <api_key> <image_path> <output_path>")
        sys.exit(1)

    api_key = sys.argv[1]
    image_path = sys.argv[2]
    output_path = sys.argv[3]

    generator = VeoVideoGenerator(api_key)

    prompt = "Luxurious modern apartment building exterior, cinematic pan showing architectural details"

    try:
        result_path = generator.generate_from_image_file(
            image_path=image_path,
            prompt=prompt,
            output_path=output_path,
            duration="8s",
            resolution="720p"
        )
        print(f"Success! Video saved to: {result_path}")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
