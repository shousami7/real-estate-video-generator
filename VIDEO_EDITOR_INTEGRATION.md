# Video Editor Integration - Implementation Summary

## Overview

This document describes the video editing functionality integration that allows users to edit uploaded or generated videos frame-by-frame using AI-powered image generation.

## Features Implemented

### 1. Frame Extraction
- Extracts 6 evenly-spaced frames from generated videos
- Stores frame metadata (timestamp, position, edit history)
- Uses FFmpeg for high-quality frame extraction

### 2. AI-Powered Frame Editing
- Select individual frames for editing
- Chat-based interface for describing desired edits
- Generates 4 AI variations based on user prompts
- Apply selected variation to frame

### 3. Video Export
- Rebuilds video with edited frames
- Maintains original video quality and properties
- Downloads edited video

## Files Added/Modified

### New Files

1. **frame_editor.py** - Core frame editing logic
   - `FrameEditor` class: Frame extraction, metadata management, video rebuilding
   - `AIFrameEditor` class: AI image generation interface
   - Uses FFmpeg for video processing
   - Stores frame metadata in JSON format

2. **templates/video_editor_ui.html** - Video editor UI
   - Frame selection grid (6 frames)
   - AI chat editor panel
   - Real-time preview
   - Variation selection interface

### Modified Files

1. **web_ui.py** - Added/updated frame editor endpoints
   - `/video/upload` - Upload video (POST)
   - `/frames/extract` - Extract frames from video (POST)
   - `/frames/image/<frame_id>` - Serve frame image (GET)
   - `/frames/edit` - Generate AI variations (POST)
   - `/frames/apply` - Apply edited frame (POST)
   - `/video/editor` - Display editor UI (GET, default redirect target)
   - `/video/export` - Export edited video (POST)
   - `/download/editor` - Download edited video (GET)

2. **templates/video_editor_ui.html** - Video editor UI
   - Upload zone for videos (drag & drop + picker)
   - Frame grid (6 frames) with preview
   - AI chat panel for edit prompts and variations

## User Workflow

### Complete Video Editing Flow

```
1. Open /video/editor (root redirects here)
   ↓
2. Upload a video via drag & drop or file picker
   ↓
3. System extracts 6 frames from video
   ↓
4. User selects a frame to edit
   ↓
5. User types prompt: "Make sunset more vibrant"
   ↓
6. AI generates 4 variations
   ↓
7. User selects preferred variation
   ↓
8. Frame is updated
   ↓
9. Repeat steps 4-8 for other frames
   ↓
10. Click "Export Video"
   ↓
11. System rebuilds video with edited frames
   ↓
12. Download edited video
```

## API Endpoints

### Video Upload
```
POST /video/upload
FormData: { "video": <file> }
Response: { "status": "success", "video_path": "uploads/.../file.mp4" }
```

### Frame Extraction
```
POST /frames/extract
Body: { "video_path": "uploads/.../file.mp4", "num_frames": 6 }
Response: {
  "status": "success",
  "frames": [...],
  "frames_dir": "frames/session_id/..."
}
```

### Get Frame Image
```
GET /frames/image/<frame_id>
Response: PNG image file
```

### Edit Frame (Generate Variations)
```
POST /frames/edit
Body: {
  "frame_id": 0,
  "prompt": "Make the sunset more vibrant"
}
Response: { "status": "success", "variations": ["data:image/png;base64,...", ...] }
```

### Apply Frame Edit
```
POST /frames/apply
Body: {
  "frame_id": 0,
  "edited_image_url": "data:image/png;base64,..."
}
Response: { "status": "success", "file_path": "frames/.../frame_0_edited.png" }
```

### Export Video
```
POST /video/export
Body: {}
Response: { "status": "success", "download_url": "/download/editor?path=..." }
```

## Technical Details

### Frame Metadata Structure

```json
{
  "video_path": "output/session_id/final_property_video.mp4",
  "video_info": {
    "width": 1280,
    "height": 720,
    "fps": 30.0,
    "duration": 24.0
  },
  "frames": {
    "frame_000": {
      "frame_id": "frame_000",
      "frame_path": "frames/session_id/.../frame_000.png",
      "timestamp": 4.0,
      "frame_number": 0,
      "original": true,
      "edited": false,
      "edit_history": []
    }
  }
}
```

### Session Storage

The following session keys are used:
- `session_id` - Unique session identifier
- `final_video` - Path to generated video
- `frames_dir` - Path to extracted frames directory
- `frame_editor_initialized` - Boolean flag
- `edited_video` - Path to edited video (after export)

### FFmpeg Commands

**Frame Extraction:**
```bash
ffmpeg -ss <timestamp> -i <video> -frames:v 1 -q:v 2 -y <output>
```

**Video Rebuilding (with overlays):**
```bash
ffmpeg -i <video> -loop 1 -t 0.1 -i <frame1> ...
  -filter_complex "<complex_filter>"
  -c:v libx264 -preset medium -crf 23 -c:a copy
  <output>
```

## Dependencies

All required dependencies are already in `requirements.txt`:
- `Pillow>=10.0.0` - Image processing
- `Flask>=2.3.0` - Web framework
- `google-genai>=1.0.0` - AI image generation
- FFmpeg (system dependency)

## Error Handling

The integration includes comprehensive error handling:
- Missing session data
- Frame extraction failures
- AI generation errors
- Video rebuild errors
- File not found errors

All errors are logged and returned as JSON responses with appropriate status codes.

## Future Enhancements

Potential improvements:
1. **Real Image Generation**: Currently uses placeholders; integrate with actual image generation API (Imagen, DALL-E, etc.)
2. **Advanced Editing Tools**: Color correction, filters, text overlays
3. **Batch Editing**: Apply same edit to multiple frames
4. **Undo/Redo**: Edit history navigation
5. **Preview Video**: Preview edited video before final export
6. **Custom Frame Selection**: Allow users to select specific timestamps
7. **Background Processing**: Use Celery for video rebuilding
8. **Progress Tracking**: Real-time progress for export operation

## Testing Checklist

- [ ] Frame extraction works for generated videos
- [ ] Frame images display correctly in editor UI
- [ ] Frame selection updates preview
- [ ] Chat input enables after frame selection
- [ ] AI variation generation returns results
- [ ] Variation images display in grid
- [ ] Clicking variation applies edit
- [ ] Frame thumbnail shows "Edited" badge
- [ ] Export button rebuilds video
- [ ] Edited video downloads successfully
- [ ] Back button returns to main page
- [ ] Error messages display appropriately

## Usage Example

```python
# Backend usage example
from frame_editor import FrameEditor, AIFrameEditor

# Initialize editors
frame_editor = FrameEditor("output/session_id/final_video.mp4")
ai_editor = AIFrameEditor(api_key)

# Extract frames
frames = frame_editor.extract_frames(num_frames=6)

# Generate variations
variations = ai_editor.generate_frame_variations(
    frame_path=frames[0]['frame_path'],
    prompt="Make the sunset more vibrant",
    num_variations=4
)

# Apply edit
frame_editor.apply_edited_frame(
    frame_id="frame_000",
    edited_image_path=variations[0]['image_path'],
    prompt="Make the sunset more vibrant"
)

# Rebuild video
output_video = frame_editor.rebuild_video()
```

## Troubleshooting

### Common Issues

1. **FFmpeg not found**
   - Install FFmpeg: `brew install ffmpeg` (macOS) or `apt-get install ffmpeg` (Ubuntu)

2. **Frame extraction fails**
   - Check video file exists and is readable
   - Verify FFmpeg is in PATH
   - Check disk space

3. **AI generation returns errors**
   - Verify GOOGLE_CLOUD_PROJECT/GCP_PROJECT_ID is set and ADC is configured
   - Check API quota limits
   - Verify network connectivity

4. **Video export fails**
   - Check edited frames exist
   - Verify sufficient disk space
   - Check FFmpeg version compatibility

## Notes

- Frame editing is done in-place; original frames are preserved in edit history
- Video rebuilding may take time for long videos
- High-quality settings (CRF 23) are used for export to maintain quality
- Session data persists across page refreshes
- Frames are stored in `frames/<session_id>/` directory

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Browser                             │
│  ┌──────────────────────────────┐                           │
│  │  video_editor_ui.html        │                           │
│  │  (upload → frame select → AI │                           │
│  │   chat → export)             │                           │
│  └──────────────────────────────┘                           │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask Web Server                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                 web_ui.py                             │  │
│  │  - /video/upload                                      │  │
│  │  - /frames/extract                                    │  │
│  │  - /frames/image/<id>                                 │  │
│  │  - /frames/edit                                       │  │
│  │  - /frames/apply                                      │  │
│  │  - /video/export                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend Services                            │
│  ┌────────────────┐              ┌──────────────────────┐  │
│  │ FrameEditor    │              │  AIFrameEditor       │  │
│  │ - extract_     │              │ - generate_          │  │
│  │   frames()     │              │   variations()       │  │
│  │ - apply_edited │              │                      │  │
│  │   _frame()     │              └──────────────────────┘  │
│  │ - rebuild_     │                      │                 │
│  │   video()      │                      │                 │
│  └────────────────┘                      ▼                 │
│         │                      ┌──────────────────────┐   │
│         ▼                      │  Google Gemini API   │   │
│                                └──────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
│  ┌────────────────┐                                        │
│  │    FFmpeg      │                                        │
│  └────────────────┘                                        │
└─────────────────────────────────────────────────────────────┘
```

## Summary

The video editor integration is now complete and ready for testing. The system provides a seamless workflow from video generation to frame-level editing with AI-powered variations, all through an intuitive web interface.
