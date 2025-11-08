# Luxury Real Estate AI Video Generation System

Complete automation system for generating high-end property videos using **Google Veo** and **FFmpeg**.

## Features

- **Automated Video Generation**: Upload 3 property images and generate professional marketing videos
- **AI-Powered**: Uses Google's Veo Image-to-Video model
- **Professional Transitions**: Smooth fade effects between clips using FFmpeg
- **High-End Prompts**: Pre-configured cinematic prompts for luxury real estate
- **Complete Workflow**: From image upload to final video output
- **Progress Tracking**: Real-time progress bars and detailed logging

## System Architecture

```
┌─────────────────┐
│  3 Property     │
│  Images         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  veo_generator  │  ← Upload images to Google AI
│  .py            │  ← Generate 8s videos via Google Veo
└────────┬────────┘
         │
         ▼
    3 Video Clips
    (8 seconds each)
         │
         ▼
┌─────────────────┐
│  video_composer │  ← Compose with FFmpeg
│  .py            │  ← Add fade transitions
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Final Video    │  ← 24 seconds total
│  (720p HD)      │  ← Professional quality
└─────────────────┘
```

## Requirements

### Software Dependencies

1. **Python 3.8+**
2. **FFmpeg** (with libx264 support)
   - macOS: `brew install ffmpeg`
   - Ubuntu: `sudo apt install ffmpeg`
   - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

### Python Dependencies

Install via pip:

```bash
pip install -r requirements.txt
```

Dependencies:
- `google-genai>=1.0.0` - Google AI SDK for Veo video generation
- `requests>=2.31.0` - HTTP requests for downloading videos
- `python-dotenv>=1.0.0` - Environment variable management
- `Pillow>=10.0.0` - Image processing
- `tqdm>=4.66.0` - Progress bars
- `Flask>=2.3.0` - Web application framework (for web UI)

## Installation

```bash
# Clone or download the project
cd /path/to/project

# Install Python dependencies
pip install -r requirements.txt

# Verify FFmpeg installation
ffmpeg -version

# Set up environment variables (.env file)
cat > .env << EOF
GOOGLE_API_KEY=your_google_api_key_here
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
EOF

# Or manually create .env file with:
# GOOGLE_API_KEY=your_google_api_key_here
# SECRET_KEY=your_random_secret_key_here
```

## Getting Google AI API Key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Select or create a Google Cloud project
5. Copy and save your API key securely

**Note**: Ensure you have access to the Veo model in your Google AI account.

## Usage

### Web UI (Recommended)

The easiest way to use the system is through the web interface:

```bash
# Start the Flask web server using the startup script (recommended)
./start.sh

# Or start directly with Python
python3 app.py
```

Then open your browser and navigate to:
```
http://localhost:5001
```

Features:
- User-friendly interface with drag-and-drop image upload
- Real-time progress tracking
- Automatic video preview and download
- No command-line knowledge required

**Note**: The web UI currently uses synchronous processing. For production use with multiple users, consider implementing a task queue like Celery or RQ.

### Command-Line Interface

### Basic Usage

Generate a luxury property video from 3 images:

```bash
python generate_property_video.py \
  --api-key YOUR_GOOGLE_API_KEY \
  --images exterior.jpg interior.jpg lobby.jpg \
  --output luxury_apartment.mp4
```

### Using Environment Variable

```bash
export GOOGLE_API_KEY=your_api_key_here

python generate_property_video.py \
  --images photo1.jpg photo2.jpg photo3.jpg
```

### Advanced Usage

Custom transitions and settings:

```bash
python generate_property_video.py \
  --api-key YOUR_GOOGLE_API_KEY \
  --images exterior.jpg interior.jpg common_area.jpg \
  --output penthouse_showcase.mp4 \
  --transition wipeleft \
  --transition-duration 0.8 \
  --clip-duration 10 \
  --resolution 1920x1080 \
  --output-dir /path/to/output
```

### Custom Prompts

Provide your own video generation prompts:

```bash
python generate_property_video.py \
  --api-key YOUR_GOOGLE_API_KEY \
  --images img1.jpg img2.jpg img3.jpg \
  --prompts \
    "Modern skyscraper exterior with sunset lighting" \
    "Luxurious penthouse living room with city views" \
    "Elegant lobby with marble and gold accents"
```

## Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--api-key` | Google AI API key | `$GOOGLE_API_KEY` |
| `--images` | 3 property images (required) | - |
| `--output` | Output video filename | `final_property_video.mp4` |
| `--output-dir` | Base output directory | `output/` |
| `--session-name` | Session folder name | Timestamp |
| `--transition` | Transition type | `fade` |
| `--transition-duration` | Transition length (seconds) | `0.5` |
| `--clip-duration` | Each clip duration (seconds) | `8` |
| `--resolution` | Output resolution | `1280x720` |
| `--prompts` | Custom prompts for each clip | Built-in prompts |
| `--verbose` | Enable verbose logging | `false` |

### Available Transitions

- `fade` - Smooth fade transition (recommended)
- `wipeleft` - Wipe from right to left
- `wiperight` - Wipe from left to right
- `wipeup` - Wipe from bottom to top
- `wipedown` - Wipe from top to bottom
- `slideleft` - Slide transition left
- `slideright` - Slide transition right

## Output Structure

```
output/
└── 20250107_143022/              # Session directory (timestamp)
    ├── clips/                     # Individual generated clips
    │   ├── clip_01.mp4           # Exterior video (8s)
    │   ├── clip_02.mp4           # Interior video (8s)
    │   └── clip_03.mp4           # Common area video (8s)
    └── final_property_video.mp4  # Final composed video (~24s)
```

## Default Prompts

The system includes professionally crafted prompts for luxury real estate:

### 1. Exterior Shot
```
Luxurious modern apartment building exterior, cinematic pan showing
architectural details, elegant facade with natural lighting, smooth
camera movement revealing the property's grandeur, professional real
estate photography style, high-end residential building
```

### 2. Interior Shot
```
Spacious luxury apartment interior, elegant living space with modern
furnishings, natural light streaming through large windows, sophisticated
interior design, smooth camera pan showing room details, premium finishes
and decorative elements, 4K quality real estate photography
```

### 3. Common Areas
```
Exclusive luxury building common areas, elegant lobby entrance, premium
architectural design, marble flooring and modern fixtures, sophisticated
lighting design, smooth cinematic camera movement, high-end residential
amenities showcase, professional real estate presentation
```

## Module Documentation

### veo_generator.py

Handles all Google AI API interactions:

```python
from veo_generator import VeoVideoGenerator

# Initialize
generator = VeoVideoGenerator(api_key="your_api_key")

# Complete workflow: upload, generate, download
video_path = generator.generate_from_image_file(
    image_path="photo.jpg",
    prompt="Luxurious apartment exterior...",
    output_path="output.mp4",
    duration="8s",
    resolution="720p"
)
```

### video_composer.py

FFmpeg video composition:

```python
from video_composer import VideoComposer

# Initialize
composer = VideoComposer()

# Compose with transitions
final_video = composer.compose_with_transitions(
    video_paths=["clip1.mp4", "clip2.mp4", "clip3.mp4"],
    output_path="final.mp4",
    transition_type="fade",
    transition_duration=0.5
)

# Simple concatenation (no transitions)
final_video = composer.simple_concatenate(
    video_paths=["clip1.mp4", "clip2.mp4"],
    output_path="concatenated.mp4"
)
```

### generate_property_video.py

Main workflow orchestration:

```python
from generate_property_video import PropertyVideoGenerator

# Initialize
generator = PropertyVideoGenerator(
    api_key="your_api_key",
    output_dir="output"
)

# Complete workflow
final_video = generator.generate_complete_property_video(
    image_paths=["img1.jpg", "img2.jpg", "img3.jpg"],
    output_name="luxury_property.mp4",
    transition_type="fade"
)
```

## Troubleshooting

### FFmpeg Not Found

```
Error: FFmpeg not found
```

**Solution**: Install FFmpeg:
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

### API Key Issues

```
Error: API key not provided
```

**Solution**: Set your API key:
```bash
export GOOGLE_API_KEY=your_api_key_here
```

Or use `--api-key` flag:
```bash
python generate_property_video.py --api-key YOUR_KEY --images ...
```

### Video Generation Timeout

```
TimeoutError: Video generation timed out
```

**Solution**: The system waits up to 10 minutes. If it times out:
- Check your Google AI account status and Veo access
- Verify your API key is valid
- Try again with a smaller image
- Check Google AI service status

### File Not Found

```
FileNotFoundError: Image file not found
```

**Solution**: Verify image paths:
```bash
ls -lh exterior.jpg interior.jpg lobby.jpg
```

Use absolute paths if needed:
```bash
python generate_property_video.py \
  --images /full/path/to/img1.jpg /full/path/to/img2.jpg /full/path/to/img3.jpg
```

## Performance Notes

- **Generation Time**: ~2-5 minutes per 8-second clip
- **Total Time**: ~6-15 minutes for complete workflow
- **API Costs**: Check Google AI pricing for Veo usage
- **Video Quality**: 720p HD by default (configurable)
- **File Sizes**: ~10-30MB per clip, ~50-100MB final video

## Best Practices

1. **Image Quality**: Use high-resolution images (1920x1080 or higher)
2. **Image Composition**: Ensure good lighting and clear subject matter
3. **Image Order**: Exterior → Interior → Common Areas (tells a story)
4. **File Formats**: JPEG or PNG recommended
5. **Prompt Customization**: Adjust prompts for specific property types
6. **Resolution**: Use 1920x1080 for premium presentations

## Example Workflow

```bash
# 1. Prepare your images
ls property_images/
# exterior.jpg  interior.jpg  lobby.jpg

# 2. Set API key
export GOOGLE_API_KEY=your_google_api_key_here

# 3. Generate video
python generate_property_video.py \
  --images property_images/exterior.jpg \
           property_images/interior.jpg \
           property_images/lobby.jpg \
  --output manhattan_penthouse.mp4 \
  --transition fade \
  --transition-duration 0.5

# 4. Output appears in output/TIMESTAMP/
# View your video!
```

## License

This project is provided as-is for real estate marketing automation.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Google AI documentation: https://ai.google.dev/
3. Check FFmpeg documentation: https://ffmpeg.org/documentation.html

## Credits

- **AI Model**: Google Veo 3.1
- **Video Processing**: FFmpeg
- **Python Libraries**: google-genai, requests, Pillow, tqdm, python-dotenv
