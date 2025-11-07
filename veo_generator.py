"""
fal.ai Veo 3.1 Video Generator Module
Handles image-to-video generation using fal.ai API
"""

import requests
import time
import os
from typing import Optional, Dict, Any
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class VeoVideoGenerator:
    """
    Manages video generation using fal.ai Veo 3.1 Image-to-Video API
    """

    BASE_URL = "https://queue.fal.run/fal-ai/veo/image-to-video"
    UPLOAD_URL = "https://queue.fal.run/fal-ai/files/upload"
    POLL_INTERVAL = 5  # seconds
    MAX_RETRIES = 120  # 10 minutes max wait time

    def __init__(self, api_key: str):
        """
        Initialize the Veo Video Generator

        Args:
            api_key: fal.ai API key
        """
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json"
        }

    def upload_image(self, image_path: str) -> str:
        """
        Upload image to fal.ai storage

        Args:
            image_path: Path to the image file

        Returns:
            URL of the uploaded image
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        logger.info(f"Uploading image: {image_path}")

        # Read image file
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Get file extension
        file_ext = Path(image_path).suffix.lower()
        content_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp'
        }
        content_type = content_type_map.get(file_ext, 'image/jpeg')

        # Upload to fal.ai storage
        upload_headers = {
            "Authorization": f"Key {self.api_key}",
            "Content-Type": content_type
        }

        response = requests.post(
            self.UPLOAD_URL,
            headers=upload_headers,
            data=image_data
        )
        response.raise_for_status()

        upload_result = response.json()
        image_url = upload_result.get('url') or upload_result.get('file_url')

        if not image_url:
            raise ValueError(f"Upload failed - no URL returned: {upload_result}")

        logger.info(f"Image uploaded successfully: {image_url}")
        return image_url

    def generate_video(
        self,
        image_url: str,
        prompt: str,
        duration: int = 8,
        aspect_ratio: str = "16:9",
        fps: int = 30
    ) -> str:
        """
        Generate video from image using Veo 3.1

        Args:
            image_url: URL of the uploaded image
            prompt: Text prompt describing the desired video motion
            duration: Video duration in seconds (default: 8)
            aspect_ratio: Video aspect ratio (default: "16:9")
            fps: Frames per second (default: 30)

        Returns:
            Request ID for polling
        """
        logger.info(f"Submitting video generation request")
        logger.info(f"Prompt: {prompt[:100]}...")

        payload = {
            "image_url": image_url,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "fps": fps
        }

        response = requests.post(
            self.BASE_URL,
            headers=self.headers,
            json=payload
        )
        response.raise_for_status()

        result = response.json()
        request_id = result.get('request_id')

        if not request_id:
            raise ValueError(f"No request ID returned: {result}")

        logger.info(f"Video generation started - Request ID: {request_id}")
        return request_id

    def poll_status(self, request_id: str) -> Dict[str, Any]:
        """
        Poll the status of a video generation request

        Args:
            request_id: The request ID to poll

        Returns:
            Result dictionary containing video URL when complete
        """
        status_url = f"{self.BASE_URL}/requests/{request_id}"

        for attempt in range(self.MAX_RETRIES):
            response = requests.get(status_url, headers=self.headers)
            response.raise_for_status()

            result = response.json()
            status = result.get('status')

            logger.info(f"Poll attempt {attempt + 1}/{self.MAX_RETRIES} - Status: {status}")

            if status == 'COMPLETED':
                logger.info("Video generation completed!")
                return result
            elif status == 'FAILED':
                error_msg = result.get('error', 'Unknown error')
                raise RuntimeError(f"Video generation failed: {error_msg}")

            # Wait before next poll
            time.sleep(self.POLL_INTERVAL)

        raise TimeoutError(f"Video generation timed out after {self.MAX_RETRIES * self.POLL_INTERVAL} seconds")

    def download_video(self, video_url: str, output_path: str) -> str:
        """
        Download generated video

        Args:
            video_url: URL of the generated video
            output_path: Path to save the video

        Returns:
            Path to the downloaded video
        """
        logger.info(f"Downloading video from: {video_url}")

        response = requests.get(video_url, stream=True)
        response.raise_for_status()

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Download with progress
        total_size = int(response.headers.get('content-length', 0))

        with open(output_path, 'wb') as f:
            if total_size == 0:
                f.write(response.content)
            else:
                downloaded = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress = (downloaded / total_size) * 100
                        logger.debug(f"Download progress: {progress:.1f}%")

        logger.info(f"Video downloaded successfully: {output_path}")
        return output_path

    def generate_from_image_file(
        self,
        image_path: str,
        prompt: str,
        output_path: str,
        duration: int = 8
    ) -> str:
        """
        Complete workflow: upload image, generate video, download result

        Args:
            image_path: Path to input image
            prompt: Video generation prompt
            output_path: Path to save the generated video
            duration: Video duration in seconds

        Returns:
            Path to the downloaded video
        """
        # Upload image
        image_url = self.upload_image(image_path)

        # Generate video
        request_id = self.generate_video(
            image_url=image_url,
            prompt=prompt,
            duration=duration
        )

        # Poll for completion
        result = self.poll_status(request_id)

        # Extract video URL
        video_url = result.get('video', {}).get('url')
        if not video_url:
            raise ValueError(f"No video URL in result: {result}")

        # Download video
        return self.download_video(video_url, output_path)


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
            output_path=output_path
        )
        print(f"Success! Video saved to: {result_path}")
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
