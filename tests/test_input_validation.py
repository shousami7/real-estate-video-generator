"""
Tests for input validation module
"""

import pytest
import tempfile
import os
from pathlib import Path

from utils.input_validator import (
    ValidationError,
    ImageValidator,
    VideoValidator,
    validate_image_for_veo
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class TestImageValidator:
    """Test suite for image validation"""
    
    @pytest.fixture
    def temp_image(self):
        """Create a temporary valid image for testing"""
        if not HAS_PIL:
            pytest.skip("PIL not available")
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (1920, 1080), color='red')
            img.save(f.name, 'JPEG')
            temp_path = f.name
        
        yield temp_path
        
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    def test_valid_image(self, temp_image):
        """Test validation passes for valid image"""
        metadata = ImageValidator.validate_image(temp_image)
        
        assert metadata['width'] == 1920
        assert metadata['height'] == 1080
        assert metadata['format'] in {'JPEG', 'JPG'}
        assert metadata['size_mb'] > 0
    
    def test_nonexistent_file(self):
        """Test validation fails for non-existent file"""
        with pytest.raises(ValidationError) as exc_info:
            ImageValidator.validate_image('/nonexistent/file.jpg')
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_oversized_image(self, temp_image):
        """Test validation fails for oversized image"""
        # Temporarily set max size to tiny value
        original_max = ImageValidator.MAX_FILE_SIZE_MB
        ImageValidator.MAX_FILE_SIZE_MB = 0.001  # 1KB
        
        try:
            with pytest.raises(ValidationError) as exc_info:
                ImageValidator.validate_image(temp_image)
            
            assert "too large" in str(exc_info.value).lower()
            assert "mb" in str(exc_info.value).lower()
        finally:
            ImageValidator.MAX_FILE_SIZE_MB = original_max
    
    def test_invalid_extension(self):
        """Test validation fails for invalid file extension"""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b"not an image")
            temp_path = f.name
        
        try:
            with pytest.raises(ValidationError) as exc_info:
                ImageValidator.validate_image(temp_path)
            
            assert "unsupported" in str(exc_info.value).lower()
            assert "extension" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)
    
    @pytest.mark.skipif(not HAS_PIL, reason="PIL not available")
    def test_aspect_ratio_validation(self, temp_image):
        """Test aspect ratio validation"""
        # Valid aspect ratio (1920x1080 is 16:9)
        metadata = ImageValidator.validate_image(temp_image, required_aspect_ratio="16:9")
        assert metadata is not None
        
        # Invalid aspect ratio
        with pytest.raises(ValidationError) as exc_info:
            ImageValidator.validate_image(temp_image, required_aspect_ratio="1:1")
        
        assert "aspect ratio" in str(exc_info.value).lower()

    @pytest.mark.skipif(not HAS_PIL, reason="PIL not available")
    def test_aspect_ratio_auto_fix(self, tmp_path):
        """Test auto-cropping when aspect ratio mismatches"""
        square_path = tmp_path / "square.jpg"
        img = Image.new('RGB', (1000, 1000), color='green')
        img.save(square_path, 'JPEG')

        metadata = ImageValidator.validate_image(
            str(square_path),
            required_aspect_ratio="16:9",
            auto_fix_aspect_ratio=True
        )

        assert metadata["auto_fixed"] is True
        assert metadata["original_path"] == str(square_path)
        assert metadata["path"] != str(square_path)
        ratio = metadata["width"] / metadata["height"]
        assert ratio == pytest.approx(
            ImageValidator.ASPECT_RATIOS["16:9"],
            rel=0,
            abs=ImageValidator.ASPECT_RATIO_TOLERANCE
        )
    
    @pytest.mark.skipif(not HAS_PIL, reason="PIL not available")
    def test_too_small_image(self):
        """Test validation fails for too small images"""
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            img = Image.new('RGB', (100, 100), color='blue')
            img.save(f.name, 'JPEG')
            temp_path = f.name
        
        try:
            with pytest.raises(ValidationError) as exc_info:
                ImageValidator.validate_image(temp_path)
            
            assert "too small" in str(exc_info.value).lower()
            assert "256" in str(exc_info.value)
        finally:
            os.unlink(temp_path)


class TestVideoValidator:
    """Test suite for video validation"""
    
    def test_nonexistent_video(self):
        """Test validation fails for non-existent video"""
        with pytest.raises(ValidationError) as exc_info:
            VideoValidator.validate_video('/nonexistent/video.mp4')
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_invalid_extension(self):
        """Test validation fails for invalid video extension"""
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            f.write(b"not a video")
            temp_path = f.name
        
        try:
            with pytest.raises(ValidationError) as exc_info:
                VideoValidator.validate_video(temp_path)
            
            assert "unsupported" in str(exc_info.value).lower()
            assert "extension" in str(exc_info.value).lower()
        finally:
            os.unlink(temp_path)
    
    def test_valid_extension(self):
        """Test validation passes for valid extensions"""
        # Create empty files with valid extensions
        for ext in ['.mp4', '.mov', '.webm']:
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                f.write(b"fake video data")
                temp_path = f.name
            
            try:
                # Should not raise for extension check
                metadata = VideoValidator.validate_video(temp_path, check_codec=False)
                assert metadata['extension'] == ext
            finally:
                os.unlink(temp_path)


class TestValidationError:
    """Test ValidationError custom exception"""
    
    def test_error_message(self):
        """Test error message formatting"""
        error = ValidationError("File too large", "Try compressing")
        
        assert "File too large" in str(error)
        assert "Try compressing" in str(error)
    
    def test_error_without_suggestion(self):
        """Test error without suggestion"""
        error = ValidationError("Invalid format")
        
        assert "Invalid format" in str(error)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
