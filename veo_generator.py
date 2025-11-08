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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VeoVideoGenerator:
    """
    Manages video generation using Google Generative AI Veo Image-to-Video API
    """

    # Available Veo models
    VEO_MODEL = "veo-3.1-generate-preview"  # Veo 3.1 for high-quality video generation

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
                uploaded_file = self.client.files.get(name=uploaded_file.name)

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
        generate_audio: bool = True
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
                operation = self.client.operations.get(name=operation.name)

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

            # Get file name or URI
            if hasattr(video_file, 'name'):
                file_name = video_file.name
            elif hasattr(video_file, 'uri'):
                # Extract file name from URI if it's a URI
                file_name = video_file.uri.split('/')[-1]
            elif isinstance(video_file, str):
                file_name = video_file
            else:
                raise ValueError(f"Unable to extract file name from video_file: {type(video_file)}")

            logger.info(f"Downloading video file: {file_name}")

            # Download the video file using the client
            # The file should be downloaded as bytes
            downloaded_content = self.client.files.download(name=file_name)

            # Save to the specified path
            with open(output_path, 'wb') as f:
                if isinstance(downloaded_content, bytes):
                    f.write(downloaded_content)
                else:
                    # If it's a file-like object, read it
                    if hasattr(downloaded_content, 'read'):
                        f.write(downloaded_content.read())
                    else:
                        # Try to convert to bytes
                        f.write(bytes(downloaded_content))

            logger.info(f"Video downloaded successfully: {output_path}")
            return output_path

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
