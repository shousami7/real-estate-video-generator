"""
Google Veo Video Generator Module
Handles image-to-video generation using Google Generative AI (Veo) API
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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VeoVideoGenerator:
    """
    Manages video generation using Google Generative AI Veo Image-to-Video API
    """

    # Available Veo models
    VEO_MODEL = "veo-3.0-fast-generate-001"  # Veo 3 Fast

    def __init__(self, api_key: str):
        """
        Initialize the Veo Video Generator

        Args:
            api_key: Google AI API key
        """
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        logger.info(f"Initialized Veo Video Generator with model: {self.VEO_MODEL}")

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

            # Wait for file to be processed
            logger.info("Waiting for image to be processed...")
            while uploaded_file.state == "PROCESSING":
                time.sleep(2)
                uploaded_file = self.client.files.get(uploaded_file.name)

            if uploaded_file.state == "FAILED":
                raise ValueError(f"Image processing failed")

            logger.info("Image ready for video generation")
            return uploaded_file

        except Exception as e:
            logger.error(f"Failed to upload image: {e}")
            raise

    def generate_video(
        self,
        image_path: str,
        prompt: str,
        duration: str = "8s",
        aspect_ratio: str = "16:9",
        resolution: str = "720p",
        generate_audio: bool = False  # Veo 2.0はオーディオ非対応のためFalseに変更
    ) -> Any:
        """
        Generate video from image file using Google Veo

        Args:
            image_path: Path to the image file
            prompt: Text prompt describing the desired video motion
            duration: Video duration ("4s", "6s", or "8s") - Note: Veo 3.1 generates 8s videos
            aspect_ratio: Video aspect ratio ("16:9" or "9:16")
            resolution: Video resolution ("720p" or "1080p")
            generate_audio: Whether to generate audio (default: True)

        Returns:
            Operation object for video generation
        """
        logger.info(f"Submitting video generation request")
        logger.info(f"Model: {self.VEO_MODEL}")
        logger.info(f"Prompt: {prompt[:100]}...")
        logger.info(f"Settings: {duration}, {aspect_ratio}, {resolution}")

        try:
            # Validate image file exists
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")

            # Generate video using Veo 3.1
            logger.info("Generating video with Google Veo 3.1...")

            # Load image using types.Image.from_file() - automatically handles encoding and mime type
            logger.info(f"Loading image from: {image_path}")
            image = types.Image.from_file(location=image_path)
            logger.info(f"Image loaded successfully")

            # Start video generation operation
            operation = self.client.models.generate_videos(
                model=self.VEO_MODEL,
                prompt=prompt,
                image=image
            )

            logger.info(f"Video generation started. Operation name: {operation.name}")

            # Poll until video generation completes
            logger.info("Waiting for video generation to complete...")
            poll_count = 0
            max_polls = 120  # 10 minutes with 5 second intervals

            while not operation.done:
                time.sleep(5)
                poll_count += 1

                # Get updated operation status
                operation = self.client.operations.get(operation)

                if poll_count % 6 == 0:  # Log every 30 seconds
                    logger.info(f"Still generating... ({poll_count * 5}s elapsed)")

                if poll_count >= max_polls:
                    raise TimeoutError("Video generation timed out after 10 minutes")

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
            # Prepare authentication headers
            headers = {
                'X-Goog-API-Key': self.api_key
            }

            logger.info("Making authenticated request to download video...")

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
            video_file = None

            # Method 1: Check for generated_videos attribute
            if hasattr(response, 'generated_videos') and response.generated_videos:
                video_data = response.generated_videos[0]
                if hasattr(video_data, 'video'):
                    video_file = video_data.video
                    logger.info("Found video in generated_videos[0].video")

            # Method 2: Check if response itself is a video file
            elif hasattr(response, 'video'):
                video_file = response.video
                logger.info("Found video in response.video")

            # Method 3: Check if response has file information
            elif hasattr(response, 'file'):
                video_file = response.file
                logger.info("Found video in response.file")

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

            # Download with retry logic
            max_retries = 3
            retry_delay = 2  # seconds

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
        Complete workflow: generate video from image, download result

        Args:
            image_path: Path to input image
            prompt: Video generation prompt
            output_path: Path to save the generated video
            duration: Video duration ("4s", "6s", or "8s") - Note: Veo 3.1 generates 8s videos
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

        # Step 1: Generate video (image is encoded internally)
        operation = self.generate_video(
            image_path=image_path,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            generate_audio=generate_audio
        )

        # Step 2: Download video
        video_path = self.download_video(operation, output_path)

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
