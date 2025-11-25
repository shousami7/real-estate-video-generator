"""
Input validation for images and videos with user-friendly error messages.

Validates file size, format, dimensions, and other properties before API calls
to fail fast and provide helpful feedback to users.
"""

import os
import json
import subprocess
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ValidationError(Exception):
    """User-friendly validation error with helpful messages"""
    
    def __init__(self, message: str, suggestion: Optional[str] = None):
        self.message = message
        self.suggestion = suggestion
        super().__init__(message)
    
    def __str__(self):
        if self.suggestion:
            return f"{self.message} {self.suggestion}"
        return self.message


class ImageValidator:
    """Validate image inputs before upload/processing"""
    
    # Configuration (can be overridden via environment variables)
    MAX_FILE_SIZE_MB = float(os.getenv("MAX_IMAGE_SIZE_MB", "10"))
    MAX_DIMENSION = int(os.getenv("MAX_IMAGE_DIMENSION", "4096"))
    MIN_DIMENSION = int(os.getenv("MIN_IMAGE_DIMENSION", "256"))
    ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'JPG'}
    ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
    
    # Aspect ratios with tolerance
    ASPECT_RATIOS = {
        '16:9': 16/9,
        '9:16': 9/16,
        '1:1': 1.0,
        '4:3': 4/3,
        '3:4': 3/4,
    }
    ASPECT_RATIO_TOLERANCE = 0.05  # 5% tolerance
    
    @classmethod
    def validate_image(
        cls,
        image_path: str,
        required_aspect_ratio: Optional[str] = None,
        check_dimensions: bool = True
    ) -> Dict[str, Any]:
        """
        Validate image file and return metadata.
        
        Args:
            image_path: Path to image file
            required_aspect_ratio: Optional aspect ratio requirement (e.g., "16:9")
            check_dimensions: Whether to check image dimensions (requires PIL)
            
        Returns:
            Dictionary with image metadata (width, height, format, size_mb)
            
        Raises:
            ValidationError: If validation fails with user-friendly message
        """
        # 1. Check file exists
        if not os.path.exists(image_path):
            raise ValidationError(
                f"Image file not found at path '{image_path}'.",
                "Please check the file path and try again."
            )
        
        # 2. Check file extension
        ext = Path(image_path).suffix.lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file extension '{ext}'.",
                f"Please use one of: {', '.join(cls.ALLOWED_EXTENSIONS)}"
            )
        
        # 3. Check file size
        try:
            file_size_bytes = os.path.getsize(image_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
        except OSError as e:
            raise ValidationError(
                f"Cannot access image file: {e}",
                "Check file permissions and try again."
            )
        
        if file_size_mb > cls.MAX_FILE_SIZE_MB:
            raise ValidationError(
                f"Image too large ({file_size_mb:.1f} MB).",
                f"Maximum size is {cls.MAX_FILE_SIZE_MB:.0f}MB. Try compressing the image."
            )
        
        # 4. Validate image format and dimensions (requires PIL)
        metadata = {
            'size_mb': round(file_size_mb, 2),
            'path': image_path
        }
        
        if check_dimensions and not HAS_PIL:
            # Skip dimension checks if PIL not available
            return metadata
        
        if check_dimensions:
            try:
                with Image.open(image_path) as img:
                    # Check format
                    img_format = img.format.upper() if img.format else 'UNKNOWN'
                    if img_format not in cls.ALLOWED_FORMATS:
                        raise ValidationError(
                            f"Unsupported image format '{img_format}'.",
                            "Please convert to JPEG, PNG, or WEBP."
                        )
                    
                    # Get dimensions
                    width, height = img.size
                    metadata['width'] = width
                    metadata['height'] = height
                    metadata['format'] = img_format
                    
                    # Check minimum dimensions
                    if width < cls.MIN_DIMENSION or height < cls.MIN_DIMENSION:
                        raise ValidationError(
                            f"Image too small ({width}x{height}).",
                            f"Minimum size is {cls.MIN_DIMENSION}x{cls.MIN_DIMENSION} pixels."
                        )
                    
                    # Check maximum dimensions
                    if width > cls.MAX_DIMENSION or height > cls.MAX_DIMENSION:
                        raise ValidationError(
                            f"Image too large ({width}x{height}).",
                            f"Maximum size is {cls.MAX_DIMENSION}x{cls.MAX_DIMENSION} pixels."
                        )
                    
                    # Check aspect ratio if required
                    if required_aspect_ratio:
                        cls._validate_aspect_ratio(width, height, required_aspect_ratio)
                    
            except IOError as e:
                if isinstance(e, ValidationError):
                    raise
                raise ValidationError(
                    f"Cannot read image file: {e}",
                    "The file may be corrupted or in an unsupported format."
                )
        
        return metadata
    
    @classmethod
    def _validate_aspect_ratio(cls, width: int, height: int, required: str) -> None:
        """Validate aspect ratio against requirement"""
        if required not in cls.ASPECT_RATIOS:
            # Unknown aspect ratio, skip validation
            return
        
        actual_ratio = width / height
        expected_ratio = cls.ASPECT_RATIOS[required]
        
        # Allow some tolerance for rounding
        if abs(actual_ratio - expected_ratio) > cls.ASPECT_RATIO_TOLERANCE:
            raise ValidationError(
                f"Image aspect ratio mismatch. Got {width}:{height} ({actual_ratio:.2f}), "
                f"expected {required} ({expected_ratio:.2f}).",
                f"Crop or resize the image to {required} aspect ratio."
            )


class VideoValidator:
    """Validate video inputs before processing"""
    
    # Configuration
    MAX_FILE_SIZE_MB = float(os.getenv("MAX_VIDEO_SIZE_MB", "200"))
    MAX_DURATION_SECONDS = int(os.getenv("MAX_VIDEO_DURATION_S", "60"))
    ALLOWED_EXTENSIONS = {'.mp4', '.mov', '.webm', '.avi'}
    ALLOWED_CODECS = {'h264', 'h265', 'hevc', 'vp9', 'vp8', 'avc1'}
    
    @classmethod
    def validate_video(
        cls,
        video_path: str,
        check_codec: bool = False
    ) -> Dict[str, Any]:
        """
        Validate video file and return metadata.
        
        Args:
            video_path: Path to video file
            check_codec: Whether to check video codec (requires ffprobe)
            
        Returns:
            Dictionary with video metadata (duration, codec, size_mb, etc.)
            
        Raises:
            ValidationError: If validation fails with user-friendly message
        """
        # 1. Check file exists
        if not os.path.exists(video_path):
            raise ValidationError(
                f"Video file not found at path '{video_path}'.",
                "Please check the file path and try again."
            )
        
        # 2. Check file extension
        ext = Path(video_path).suffix.lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported video extension '{ext}'.",
                f"Please use one of: {', '.join(cls.ALLOWED_EXTENSIONS)}"
            )
        
        # 3. Check file size
        try:
            file_size_bytes = os.path.getsize(video_path)
            file_size_mb = file_size_bytes / (1024 * 1024)
        except OSError as e:
            raise ValidationError(
                f"Cannot access video file: {e}",
                "Check file permissions and try again."
            )
        
        if file_size_mb > cls.MAX_FILE_SIZE_MB:
            raise ValidationError(
                f"Video too large ({file_size_mb:.1f} MB).",
                f"Maximum size is {cls.MAX_FILE_SIZE_MB:.0f}MB. Try compressing the video."
            )
        
        metadata = {
            'size_mb': round(file_size_mb, 2),
            'path': video_path,
            'extension': ext
        }
        
        # 4. Check duration and codec using ffprobe (optional)
        if check_codec:
            try:
                probe_data = cls._probe_video(video_path)
                metadata.update(probe_data)
                
                # Check duration
                duration = probe_data.get('duration')
                if duration and duration > cls.MAX_DURATION_SECONDS:
                    raise ValidationError(
                        f"Video too long ({duration:.1f} seconds).",
                        f"Maximum duration is {cls.MAX_DURATION_SECONDS} seconds."
                    )
                
                # Check codec
                codec = probe_data.get('codec', '').lower()
                if codec and codec not in cls.ALLOWED_CODECS:
                    raise ValidationError(
                        f"Unsupported video codec '{codec}'.",
                        f"Please re-encode with H.264, H.265, or VP9."
                    )
                
            except subprocess.CalledProcessError:
                # ffprobe not available or failed, skip codec check
                pass
        
        return metadata
    
    @classmethod
    def _probe_video(cls, video_path: str) -> Dict[str, Any]:
        """Use ffprobe to get video metadata"""
        try:
            result = subprocess.run(
                [
                    'ffprobe',
                    '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_format',
                    '-show_streams',
                    video_path
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            
            data = json.loads(result.stdout)
            
            # Extract video stream info
            video_stream = next(
                (s for s in data.get('streams', []) if s.get('codec_type') == 'video'),
                None
            )
            
            metadata = {}
            
            if video_stream:
                metadata['codec'] = video_stream.get('codec_name', 'unknown')
                metadata['width'] = video_stream.get('width')
                metadata['height'] = video_stream.get('height')
                metadata['fps'] = video_stream.get('r_frame_rate', 'unknown')
            
            # Get duration from format
            format_data = data.get('format', {})
            duration_str = format_data.get('duration')
            if duration_str:
                metadata['duration'] = float(duration_str)
            
            return metadata
            
        except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
            # ffprobe not available or failed
            return {}


# Convenience functions
def validate_image_for_veo(image_path: str, aspect_ratio: Optional[str] = None) -> Dict[str, Any]:
    """
    Validate image for Veo API.
    
    Args:
        image_path: Path to image file
        aspect_ratio: Required aspect ratio (e.g., "16:9")
        
    Returns:
        Image metadata dictionary
        
    Raises:
        ValidationError: If validation fails
    """
    return ImageValidator.validate_image(
        image_path,
        required_aspect_ratio=aspect_ratio,
        check_dimensions=True
    )


def validate_video_for_processing(video_path: str, check_codec: bool = False) -> Dict[str, Any]:
    """
    Validate video for processing.
    
    Args:
        video_path: Path to video file
        check_codec: Whether to check codec compatibility
        
    Returns:
        Video metadata dictionary
        
    Raises:
        ValidationError: If validation fails
    """
    return VideoValidator.validate_video(video_path, check_codec=check_codec)
