# Frame-Based Extend Feature - Complete Implementation Specification

**Version:** 1.0
**Date:** 2025-11-21
**Status:** Ready for Implementation

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Current vs New Workflow](#current-vs-new-workflow)
3. [Architecture & Data Flow](#architecture--data-flow)
4. [Frontend Implementation](#frontend-implementation)
5. [Backend Implementation](#backend-implementation)
6. [API Specifications](#api-specifications)
7. [Plan Sheet Structure](#plan-sheet-structure)
8. [FFmpeg Integration](#ffmpeg-integration)
9. [Testing Checklist](#testing-checklist)
10. [File Structure](#file-structure)

---

## 🎯 Overview

### Goal
Implement a frame-based extend workflow where users can:
1. Select a specific video frame from existing uploaded videos
2. Extend the video from that selected frame
3. Merge the original video (up to selected frame) + extended video using FFmpeg

### Key Differences from Current Implementation
- **Current:** Scene-to-scene extend (upload new image → generate continuation)
- **New:** Frame-based extend (select frame from existing video → extend from that point)

---

## 🔄 Current vs New Workflow

### Current Workflow (Scene-to-Scene)
```
1. User uploads new image
2. System generates new scene/video
3. Manually manage scenes in SceneManager
```

### New Workflow (Frame-Based)
```
1. User selects "Extend" mode
   ↓ Auto-populates: "extend:v?"

2. User clicks "v?"
   ↓ Opens video frame selector modal

3. User selects a video slot (e.g., v2)
   ↓ Shows extracted frames from that video
   ↓ Updates input: "extend:v2:f?"

4. User selects a specific frame (e.g., f3)
   ↓ Updates input: "extend:v2:f3"

5. User sends message
   ↓ Creates Plan Sheet with frame preview
   ↓ Backend processing starts

6. Backend Processing:
   a. Extract selected frame as image
   b. Trim original video up to selected frame timestamp
   c. Generate extended video from frame image using Veo API
   d. Concatenate: trimmed_original + extended_video
   e. Return merged video
```

---

## 🏗️ Architecture & Data Flow

### Frontend State Management

```javascript
// Located in: templates/video_editor_ui.html (line 975-998)

const state = {
    // Existing
    videoFrames: {
        // frameId: { videoPath, videoUrl, thumbnail, isProcessing }
        0: { videoPath: null, videoUrl: null, thumbnail: null, isProcessing: false },
        1: { ... },
        // ... up to 5 (6 total slots)
    },
    expandedFrameId: null,  // Currently expanded video for frame extraction
    frames: [],             // Extracted frames from expanded video
    selectedFrame: null,    // Selected frame index

    // NEW - Add these
    extendMode: {
        selectedVideoSlot: null,    // 0-5, which video slot
        selectedFrameIndex: null,   // 0-5, which extracted frame
        isSelectingVideo: false,    // Modal state
        isSelectingFrame: false     // Frame selection state
    },

    // Existing
    selectedVideoMode: null,  // 'generate', 'extend', 'stitch', 'adjust', 'agent'
    isAgentMode: false,
    planSheets: [],
    sessionId: null
};
```

### Data Structures

#### Video Frame Structure
```javascript
// Current structure (already exists)
{
    videoPath: "uploads/session-id/video.mp4",
    videoUrl: "/uploads/session-id/video.mp4",
    thumbnail: "data:image/png;base64,...",
    isProcessing: false
}
```

#### Extracted Frame Structure
```javascript
// Current structure (already exists)
{
    frame_id: 0,
    path: "frames/frame_000.png",
    timestamp: "0:08",  // Human-readable
    seconds: 8.0,       // Numeric
    base64: "data:image/png;base64,..."
}
```

#### New Plan Sheet Structure
```javascript
{
    mode: "Extend",
    duration: 8,
    prompt: "Continue the smooth camera movement",
    pic: "yes",
    task_id: "celery-task-id",

    // NEW FIELDS
    source_video: {
        slot_id: 2,                              // Video slot 0-5
        video_path: "uploads/.../video.mp4",
        video_url: "/uploads/.../video.mp4",
        thumbnail: "data:image/png;base64,..."
    },
    selected_frame: {
        frame_id: 3,                             // Frame index 0-5
        timestamp: "0:08",                       // Display format
        seconds: 8.0,                            // For ffmpeg
        thumbnail: "data:image/png;base64,..",   // Frame preview
        frame_path: "frames/frame_003.png"       // Backend path
    }
}
```

---

## 💻 Frontend Implementation

### 1. Modify Mode Selection Handler
**File:** `templates/video_editor_ui.html`
**Location:** Lines 1392-1429

```javascript
// Existing code at line 1392
const modeOptions = document.querySelectorAll('.video-mode-option');
modeOptions.forEach(option => {
    option.addEventListener('click', () => {
        const mode = option.dataset.mode;

        // ... existing code ...

        // MODIFY: Add extend mode auto-population
        if (mode === 'generate') {
            chatInput.value = "Generate: ";
            chatInput.placeholder = "(type what you want to make video of)";
            chatInput.focus();
        } else if (mode === 'extend') {
            // NEW: Auto-populate with video selector
            chatInput.value = "extend:v?";
            chatInput.placeholder = "Click v? to select a video frame";
            chatInput.focus();

            // Initialize extend mode state
            state.extendMode = {
                selectedVideoSlot: null,
                selectedFrameIndex: null,
                isSelectingVideo: false,
                isSelectingFrame: false
            };
        } else if (mode === 'agent') {
            chatInput.placeholder = "Agent mode (MCP): describe what you want the agent to do...";
        } else {
            chatInput.placeholder = defaultChatPlaceholder;
        }

        console.log('Selected video mode:', mode);
    });
});
```

### 2. Add Video/Frame Selector Interaction
**File:** `templates/video_editor_ui.html`
**New Function:** Add after line 1614 (before `function sendMessage()`)

```javascript
// NEW: Make extend:v? and extend:vX:f? clickable
chatInput.addEventListener('click', (e) => {
    if (state.selectedVideoMode !== 'extend') return;

    const cursorPos = chatInput.selectionStart;
    const text = chatInput.value;

    // Check if clicking on "v?"
    const vQuestionMatch = text.match(/extend:v\?/);
    if (vQuestionMatch && cursorPos >= text.indexOf('v?') && cursorPos <= text.indexOf('v?') + 2) {
        openVideoSlotSelector();
        return;
    }

    // Check if clicking on "f?"
    const fQuestionMatch = text.match(/extend:v(\d):f\?/);
    if (fQuestionMatch && cursorPos >= text.indexOf('f?') && cursorPos <= text.indexOf('f?') + 2) {
        const videoSlot = parseInt(fQuestionMatch[1]);
        openFrameSelector(videoSlot);
        return;
    }
});

function openVideoSlotSelector() {
    state.extendMode.isSelectingVideo = true;

    // Create modal overlay
    const modal = document.createElement('div');
    modal.id = 'video-selector-modal';
    modal.className = 'fixed inset-0 bg-black/80 z-50 flex items-center justify-center';
    modal.innerHTML = `
        <div class="bg-[#1a1a1a] rounded-xl p-6 max-w-4xl w-full mx-4">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xl font-bold text-white">Select a Video Frame</h3>
                <button class="close-modal text-gray-400 hover:text-white">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>
            <div class="grid grid-cols-3 gap-4" id="video-slot-grid">
                ${generateVideoSlotHTML()}
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Close modal handlers
    modal.querySelector('.close-modal').addEventListener('click', () => {
        modal.remove();
        state.extendMode.isSelectingVideo = false;
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
            state.extendMode.isSelectingVideo = false;
        }
    });

    // Add click handlers to video slots
    modal.querySelectorAll('.video-slot-item').forEach(slot => {
        slot.addEventListener('click', () => {
            const slotId = parseInt(slot.dataset.slotId);
            selectVideoSlot(slotId);
            modal.remove();
            state.extendMode.isSelectingVideo = false;
        });
    });
}

function generateVideoSlotHTML() {
    let html = '';
    for (let i = 0; i < 6; i++) {
        const frameData = state.videoFrames[i];
        const isEmpty = !frameData.videoPath;
        const isDisabled = isEmpty ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer hover:ring-2 hover:ring-primary';

        html += `
            <div class="video-slot-item relative aspect-video bg-[#2a2a2a] rounded-lg overflow-hidden ${isDisabled}"
                 data-slot-id="${i}"
                 ${isEmpty ? 'style="pointer-events: none;"' : ''}>
                ${isEmpty ? `
                    <div class="absolute inset-0 flex flex-col items-center justify-center">
                        <span class="material-symbols-outlined text-gray-500 !text-3xl">videocam_off</span>
                        <span class="text-gray-500 text-sm mt-2">Empty Slot</span>
                    </div>
                ` : `
                    <img src="${frameData.thumbnail}" class="w-full h-full object-cover" />
                    <div class="absolute bottom-2 left-2 bg-black/70 text-white px-2 py-1 rounded text-xs font-bold">
                        Video ${i + 1}
                    </div>
                `}
            </div>
        `;
    }
    return html;
}

function selectVideoSlot(slotId) {
    state.extendMode.selectedVideoSlot = slotId;

    // Update chat input to show selected video
    chatInput.value = `extend:v${slotId}:f?`;
    chatInput.placeholder = "Click f? to select a specific frame";

    // Auto-open frame selector
    openFrameSelector(slotId);
}

function openFrameSelector(videoSlot) {
    const frameData = state.videoFrames[videoSlot];
    if (!frameData.videoPath) {
        alert('No video in this slot');
        return;
    }

    state.extendMode.isSelectingFrame = true;

    // Extract frames if not already extracted for this video
    if (state.expandedFrameId !== videoSlot) {
        // Extract frames for this video
        extractFramesForVideo(videoSlot);

        // Wait for extraction to complete and then show selector
        // NOTE: In production, use a callback or Promise
        setTimeout(() => {
            showFrameSelectorModal(videoSlot);
        }, 2000);
    } else {
        // Already extracted, show selector immediately
        showFrameSelectorModal(videoSlot);
    }
}

function showFrameSelectorModal(videoSlot) {
    const modal = document.createElement('div');
    modal.id = 'frame-selector-modal';
    modal.className = 'fixed inset-0 bg-black/80 z-50 flex items-center justify-center';
    modal.innerHTML = `
        <div class="bg-[#1a1a1a] rounded-xl p-6 max-w-5xl w-full mx-4">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-xl font-bold text-white">Select Frame from Video ${videoSlot + 1}</h3>
                <button class="close-modal text-gray-400 hover:text-white">
                    <span class="material-symbols-outlined">close</span>
                </button>
            </div>
            <div class="grid grid-cols-3 gap-4" id="frame-grid">
                ${generateFrameGridHTML()}
            </div>
            <div class="mt-4 text-sm text-gray-400 text-center">
                The video will be extended from the selected frame
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    // Close modal handlers
    modal.querySelector('.close-modal').addEventListener('click', () => {
        modal.remove();
        state.extendMode.isSelectingFrame = false;
    });

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
            state.extendMode.isSelectingFrame = false;
        }
    });

    // Add click handlers to frames
    modal.querySelectorAll('.frame-item').forEach(frame => {
        frame.addEventListener('click', () => {
            const frameId = parseInt(frame.dataset.frameId);
            selectFrame(frameId);
            modal.remove();
            state.extendMode.isSelectingFrame = false;
        });
    });
}

function generateFrameGridHTML() {
    return state.frames.map((frame, index) => `
        <div class="frame-item relative aspect-video bg-[#2a2a2a] rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-primary"
             data-frame-id="${index}">
            <img src="${frame.base64}" class="w-full h-full object-cover" />
            <div class="absolute bottom-2 left-2 bg-black/70 text-white px-2 py-1 rounded text-xs font-bold">
                ${frame.timestamp}
            </div>
        </div>
    `).join('');
}

function selectFrame(frameId) {
    state.extendMode.selectedFrameIndex = frameId;
    const frame = state.frames[frameId];

    // Update chat input to show selected frame
    chatInput.value = `extend:v${state.extendMode.selectedVideoSlot}:f${frameId}`;
    chatInput.placeholder = "Press Enter or click Send to extend from this frame";

    console.log(`Selected: Video ${state.extendMode.selectedVideoSlot}, Frame ${frameId} at ${frame.timestamp}`);
}
```

### 3. Modify sendMessage() to Handle Extend Format
**File:** `templates/video_editor_ui.html`
**Location:** Line 1627 (inside `sendRequest` function)

```javascript
// MODIFY the payload construction at line 1627
const sendRequest = (messageText) => {
    const payload = {
        message: messageText,
        session_id: state.sessionId,
        video_mode: state.selectedVideoMode,
        agent_mode: state.isAgentMode
    };

    // NEW: Add extend mode metadata if in extend mode
    if (state.selectedVideoMode === 'extend' && state.extendMode.selectedVideoSlot !== null) {
        const videoSlot = state.extendMode.selectedVideoSlot;
        const frameIndex = state.extendMode.selectedFrameIndex;

        payload.extend_metadata = {
            video_slot_id: videoSlot,
            video_path: state.videoFrames[videoSlot].videoPath,
            video_url: state.videoFrames[videoSlot].videoUrl,
            frame_index: frameIndex,
            frame_data: frameIndex !== null ? state.frames[frameIndex] : null
        };
    }

    fetch('/editor/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    // ... rest of existing code
};
```

### 4. Modify Plan Sheet Generation
**File:** `templates/video_editor_ui.html`
**Location:** Line 1895 (function `createPlanSheet`)

```javascript
// MODIFY to handle new extend plan sheet with frame preview
function createPlanSheet(config) {
    // ... existing code for hiding placeholder ...

    const planSheet = document.createElement('div');
    planSheet.className = 'plan-sheet chat-message';
    planSheet.innerHTML = generatePlanSheetHTML(config);

    // ... rest of existing code
}

function generatePlanSheetHTML(config) {
    const { mode, duration, prompt, pic, source_video, selected_frame } = config;

    let html = `
        <div class="w-full bg-[#1a1a1a] rounded-lg p-4 border border-gray-700">
            <div class="flex items-center gap-2 mb-3">
                <span class="material-symbols-outlined text-primary">description</span>
                <h4 class="font-bold text-white">Plan Sheet - ${mode}</h4>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
    `;

    // Mode
    html += `
        <div class="field">
            <label>Mode:</label>
            <span>${mode}</span>
        </div>
    `;

    // Duration
    html += `
        <div class="field">
            <label>Duration:</label>
            <span>${duration}s</span>
        </div>
    `;

    // NEW: Source video and frame preview for Extend mode
    if (mode === "Extend" && source_video && selected_frame) {
        html += `
            <div class="col-span-2 field" style="flex-direction: column; align-items: flex-start;">
                <label class="mb-2">Source Video:</label>
                <div class="flex items-center gap-3">
                    <img src="${source_video.thumbnail}"
                         class="w-24 h-14 object-cover rounded border border-gray-600" />
                    <span class="text-gray-300">Video Slot ${source_video.slot_id + 1}</span>
                </div>
            </div>

            <div class="col-span-2 field" style="flex-direction: column; align-items: flex-start;">
                <label class="mb-2">Extend from Frame:</label>
                <div class="flex items-center gap-3">
                    <img src="${selected_frame.thumbnail}"
                         class="w-24 h-14 object-cover rounded border border-primary" />
                    <div class="flex flex-col">
                        <span class="text-gray-300">Frame ${selected_frame.frame_id + 1}</span>
                        <span class="text-xs text-gray-500">at ${selected_frame.timestamp}</span>
                    </div>
                </div>
            </div>
        `;
    }

    // Prompt
    html += `
        <div class="col-span-2 field" style="flex-direction: column; align-items: flex-start;">
            <label>Prompt:</label>
            <p class="text-gray-300 mt-1">${prompt}</p>
        </div>
    `;

    // ... rest of existing plan sheet HTML (progress, buttons, etc.)

    return html;
}
```

---

## 🔧 Backend Implementation

### 1. Update Chat Endpoint Handler
**File:** `web_ui.py`
**Location:** Lines 884-1053 (`editor_chat()` function)

```python
# MODIFY at line 914-921 to capture extend_metadata
if request.content_type and 'multipart/form-data' in request.content_type:
    # ... existing code ...
    extend_metadata = None  # NEW
else:
    data = request.get_json()
    user_input = data.get('message', '').strip()
    provided_session_id = data.get('session_id')
    is_agent_mode = bool(data.get('agent_mode'))
    video_mode = data.get('video_mode')
    image_file = None
    extend_metadata = data.get('extend_metadata')  # NEW: Capture extend metadata
```

### 2. Modify _handle_extend_scene Handler
**File:** `web_ui.py`
**Location:** Lines 2424-2528 (`_handle_extend_scene()` function)

```python
def _handle_extend_scene(
    params: Dict[str, Any],
    scene_manager: SceneManager,
    session_id: str,
    extend_metadata: Optional[Dict[str, Any]] = None  # NEW parameter
) -> Dict[str, Any]:
    """
    ② シーン拡張処理 - Frame-based extend

    Args:
        params: コマンドパラメータ
        scene_manager: SceneManagerインスタンス
        session_id: セッションID
        extend_metadata: Frame selection metadata from frontend (NEW)

    Returns:
        結果辞書 with plan_sheet data
    """
    logger.info(f"Handling EXTEND command: {params}")
    logger.info(f"Extend metadata: {extend_metadata}")

    # NEW: Check if frame-based extend
    if extend_metadata and extend_metadata.get('frame_data'):
        # Frame-based extend
        video_slot_id = extend_metadata.get('video_slot_id')
        video_path = extend_metadata.get('video_path')
        frame_index = extend_metadata.get('frame_index')
        frame_data = extend_metadata.get('frame_data')

        logger.info(f"Frame-based extend: video_slot={video_slot_id}, frame={frame_index}")

        # Generate scene_id
        scene_id = scene_manager.generate_next_scene_id()

        # Launch frame-based extend task
        from tasks import frame_based_extend_task  # NEW task

        task = frame_based_extend_task.delay(
            session_id=session_id,
            scene_id=scene_id,
            source_video_path=video_path,
            frame_timestamp=frame_data['seconds'],  # Use numeric timestamp
            frame_path=frame_data.get('path'),  # Local frame path if available
            prompt=params.get('prompt', 'Continue the smooth camera movement'),
            duration=params.get('duration', '8s'),
            aspect_ratio=params.get('aspect_ratio', '16:9'),
            resolution=params.get('resolution', '720p')
        )

        logger.info(f"Frame-based extend task started: task_id={task.id}, scene_id={scene_id}")

        # Build plan sheet data
        duration_str = params.get('duration', '8s')
        duration_value = int(duration_str.rstrip('s')) if isinstance(duration_str, str) else int(duration_str)

        plan_sheet = {
            "mode": "Extend",
            "duration": duration_value,
            "prompt": params.get('prompt', 'Continue the smooth camera movement'),
            "pic": "yes",
            "task_id": task.id,
            "source_video": {
                "slot_id": video_slot_id,
                "video_path": video_path,
                "video_url": extend_metadata.get('video_url'),
                "thumbnail": extend_metadata.get('video_url')  # Can fetch thumbnail if needed
            },
            "selected_frame": {
                "frame_id": frame_index,
                "timestamp": frame_data.get('timestamp'),
                "seconds": frame_data.get('seconds'),
                "thumbnail": frame_data.get('base64'),
                "frame_path": frame_data.get('path')
            }
        }

        return {
            "status": "processing",
            "task_id": task.id,
            "scene_id": scene_id,
            "message": f"Extending video from frame {frame_index + 1} at {frame_data['timestamp']}...",
            "intent": "extend",
            "data": {
                "task_id": task.id,
                "video_id": session_id,
                "plan_sheet": plan_sheet
            }
        }

    # ELSE: Fall back to OLD scene-to-scene extend logic
    # ... existing code from lines 2438-2528 ...
```

### 3. Pass extend_metadata to Handler
**File:** `web_ui.py`
**Location:** Line 1006

```python
# MODIFY line 1006
elif intent == CommandIntent.EXTEND:
    result = _handle_extend_scene(params, scene_manager, session_id, extend_metadata)  # ADD extend_metadata
```

---

## 🚀 API Specifications

### New Endpoint: Frame-Based Extend Task

**File:** `tasks.py`
**Location:** Add after `extend_scene_task` (after line 636)

```python
@celery.task(bind=True, name="tasks.frame_based_extend_task")
def frame_based_extend_task(
    self,
    session_id: str,
    scene_id: str,
    source_video_path: str,
    frame_timestamp: float,
    frame_path: Optional[str],
    prompt: str,
    duration: str = "8s",
    aspect_ratio: str = "16:9",
    resolution: str = "720p"
) -> Dict[str, Any]:
    """
    Frame-based video extension task

    Workflow:
    1. Trim source video up to frame_timestamp
    2. Extract frame as image (if frame_path not provided)
    3. Generate extended video from frame using Veo API
    4. Concatenate: trimmed_video + extended_video
    5. Return merged video

    Args:
        session_id: Session ID
        scene_id: New scene ID
        source_video_path: Path to source video
        frame_timestamp: Timestamp in seconds where to trim/extend
        frame_path: Path to extracted frame image (optional)
        prompt: Video generation prompt
        duration: Extension duration
        aspect_ratio: Aspect ratio
        resolution: Resolution

    Returns:
        {
            "status": "completed",
            "scene_id": str,
            "video_path": str,
            "video_url": str,
            "duration": float
        }
    """
    logger.info(
        f"Starting frame-based extend: session_id={session_id}, "
        f"scene_id={scene_id}, frame_timestamp={frame_timestamp}s"
    )

    try:
        # === STEP 1: Trim source video up to frame timestamp ===
        self.update_state(
            state="TRIMMING",
            meta={
                "progress": 10,
                "message": f"Trimming video at {frame_timestamp}s...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "TRIMMING",
            }
        )

        # Normalize source video path
        if not source_video_path.startswith('/'):
            source_video_path = os.path.join(LOCAL_UPLOAD_ROOT, source_video_path)

        if not os.path.exists(source_video_path):
            raise FileNotFoundError(f"Source video not found: {source_video_path}")

        # Create temp directory for processing
        temp_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "temp", scene_id)
        os.makedirs(temp_dir, exist_ok=True)

        trimmed_video_path = os.path.join(temp_dir, "trimmed_original.mp4")

        # Trim video using FFmpeg
        trim_cmd = [
            "ffmpeg", "-y",
            "-i", source_video_path,
            "-ss", "0",
            "-to", str(frame_timestamp),
            "-c:v", "libx264",
            "-c:a", "copy",
            "-preset", "fast",
            trimmed_video_path
        ]

        logger.info(f"Trimming command: {' '.join(trim_cmd)}")
        result = subprocess.run(trim_cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            raise RuntimeError(f"Video trimming failed: {result.stderr}")

        if not os.path.exists(trimmed_video_path) or os.path.getsize(trimmed_video_path) == 0:
            raise RuntimeError("Trimmed video file is empty or not created")

        logger.info(f"Video trimmed successfully: {trimmed_video_path}")

        # === STEP 2: Extract frame as image (if not provided) ===
        self.update_state(
            state="EXTRACTING",
            meta={
                "progress": 20,
                "message": "Extracting frame as image...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "EXTRACTING",
            }
        )

        if frame_path and os.path.exists(frame_path):
            extracted_frame_path = frame_path
            logger.info(f"Using provided frame: {frame_path}")
        else:
            # Extract frame at timestamp
            extracted_frame_path = os.path.join(temp_dir, "extend_frame.png")

            extract_cmd = [
                "ffmpeg", "-y",
                "-ss", str(frame_timestamp),
                "-i", source_video_path,
                "-vframes", "1",
                "-q:v", "2",
                extracted_frame_path
            ]

            logger.info(f"Extracting frame: {' '.join(extract_cmd)}")
            result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                raise RuntimeError(f"Frame extraction failed: {result.stderr}")

            if not os.path.exists(extracted_frame_path):
                raise RuntimeError("Frame extraction failed - no output file")

        logger.info(f"Frame extracted: {extracted_frame_path}")

        # === STEP 3: Generate extended video using Veo API ===
        self.update_state(
            state="GENERATING",
            meta={
                "progress": 30,
                "message": "Generating extended video with Veo API...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "GENERATING",
            }
        )

        # Configure Veo
        veo_config = _configure_veo_auth()
        veo = VeoVideoGenerator(**veo_config)

        # Generate video from frame
        operation = veo.generate_video(
            image_path=extracted_frame_path,
            prompt=f"{prompt} (extension from selected frame)",
            duration=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            generate_audio=False
        )

        self.update_state(
            state="GENERATING",
            meta={
                "progress": 60,
                "message": "Waiting for video generation completion...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "WAITING",
            }
        )

        # Download extended video
        self.update_state(
            state="DOWNLOADING",
            meta={
                "progress": 70,
                "message": "Downloading extended video...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "DOWNLOADING",
            }
        )

        extended_video_path = os.path.join(temp_dir, "extended.mp4")
        downloaded_path = veo.download_video(operation, extended_video_path)

        logger.info(f"Extended video downloaded: {downloaded_path}")

        # === STEP 4: Concatenate trimmed + extended ===
        self.update_state(
            state="MERGING",
            meta={
                "progress": 80,
                "message": "Merging original and extended videos...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "MERGING",
            }
        )

        # Use VideoComposer to concatenate
        from video_composer import VideoComposer

        composer = VideoComposer()

        # Output path for merged video
        output_dir = os.path.join(LOCAL_UPLOAD_ROOT, session_id, "scenes")
        os.makedirs(output_dir, exist_ok=True)
        merged_video_path = os.path.join(output_dir, f"{scene_id}_merged.mp4")

        # Concatenate without transitions (simple concat)
        composer.simple_concatenate(
            video_paths=[trimmed_video_path, downloaded_path],
            output_path=merged_video_path,
            resolution="1280x720"
        )

        logger.info(f"Videos merged successfully: {merged_video_path}")

        # Get final video duration
        final_duration = get_video_duration(merged_video_path)

        # === STEP 5: Upload to Supabase ===
        self.update_state(
            state="UPLOADING",
            meta={
                "progress": 90,
                "message": "Uploading merged video...",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "UPLOADING",
            }
        )

        # Standardize path
        timestamp = int(final_duration * 1000)
        output_filename = f"extended_{scene_id}_{timestamp}.mp4"
        storage_path = build_storage_path(session_id, "output", output_filename)
        standardized_local_path = os.path.join(LOCAL_UPLOAD_ROOT, storage_path)

        os.makedirs(os.path.dirname(standardized_local_path), exist_ok=True)

        if os.path.abspath(merged_video_path) != os.path.abspath(standardized_local_path):
            shutil.move(merged_video_path, standardized_local_path)
            merged_video_path = standardized_local_path

        # Upload to Supabase
        if is_supabase_configured():
            video_url_result, upload_error = upload_video_file(
                local_path=merged_video_path,
                storage_path=storage_path,
                is_final_output=True
            )

            if upload_error:
                logger.warning(f"Supabase upload failed: {upload_error}")
                video_url = f"/{storage_path}"
            else:
                video_url = video_url_result
                logger.info(f"Video uploaded to Supabase: {video_url}")
        else:
            video_url = f"/{storage_path}"
            logger.info("Supabase not configured, using local path")

        # === STEP 6: Save to SceneManager ===
        scene_manager = SceneManager(session_id)
        scene_manager.add_scene(
            scene_id=scene_id,
            image_path=extracted_frame_path,
            video_path=storage_path,
            video_url=video_url,
            prompt=prompt,
            duration_seconds=final_duration,
            metadata={
                "type": "frame_based_extend",
                "source_video": source_video_path,
                "frame_timestamp": frame_timestamp,
                "trimmed_duration": frame_timestamp,
                "extended_duration": final_duration - frame_timestamp
            }
        )

        logger.info(f"Frame-based extend completed: scene_id={scene_id}, duration={final_duration}s")

        # Cleanup temp files
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp directory: {e}")

        return {
            "status": "completed",
            "scene_id": scene_id,
            "video_path": storage_path,
            "video_url": video_url,
            "duration": final_duration,
            "metadata": {
                "type": "frame_based_extend",
                "trimmed_at": frame_timestamp,
                "final_duration": final_duration
            }
        }

    except Exception as e:
        logger.error(f"Frame-based extend task failed: {e}", exc_info=True)
        self.update_state(
            state="FAILURE",
            meta={
                "progress": 0,
                "message": f"Error: {str(e)}",
                "scene_id": scene_id,
                "video_id": session_id,
                "stage": "extend",
                "step": "ERROR",
                "error": str(e)
            }
        )
        raise
```

### Required Imports
Add to top of `tasks.py`:

```python
import subprocess
import shutil
from video_composer import VideoComposer
```

---

## 📊 Plan Sheet Structure

### Extended Plan Sheet JSON

```json
{
  "mode": "Extend",
  "duration": 8,
  "prompt": "Continue the smooth camera movement with cinematic motion",
  "pic": "yes",
  "task_id": "abc-123-def-456",

  "source_video": {
    "slot_id": 2,
    "video_path": "uploads/session-uuid/video_slot_2.mp4",
    "video_url": "/uploads/session-uuid/video_slot_2.mp4",
    "thumbnail": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg..."
  },

  "selected_frame": {
    "frame_id": 3,
    "timestamp": "0:08",
    "seconds": 8.0,
    "thumbnail": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg...",
    "frame_path": "frames/frame_003.png"
  }
}
```

---

## 🎬 FFmpeg Integration

### Video Trimming
```bash
ffmpeg -y -i input.mp4 -ss 0 -to 8.0 -c:v libx264 -c:a copy -preset fast trimmed.mp4
```

### Frame Extraction
```bash
ffmpeg -y -ss 8.0 -i input.mp4 -vframes 1 -q:v 2 frame.png
```

### Video Concatenation (Simple)
```bash
# Using VideoComposer.simple_concatenate()
# Internally builds filter_complex with scale and concat filters
ffmpeg -y -i trimmed.mp4 -i extended.mp4 \
  -filter_complex "[0:v]scale=1280:720[v0];[1:v]scale=1280:720[v1];[v0][v1]concat=n=2:v=1:a=0[outv]" \
  -map "[outv]" -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p output.mp4
```

### Video Concatenation (With Transitions)
```bash
# Using VideoComposer.compose_with_transitions()
# Adds xfade filters between videos
```

---

## ✅ Testing Checklist

### Frontend Tests

- [ ] Extend mode auto-populates "extend:v?" in chat input
- [ ] Clicking "v?" opens video slot selector modal
- [ ] Modal shows all 6 video slots (empty slots disabled)
- [ ] Selecting video updates input to "extend:vX:f?"
- [ ] Clicking "f?" extracts frames and opens frame selector modal
- [ ] Selecting frame updates input to "extend:vX:fY"
- [ ] Send button creates plan sheet with correct structure
- [ ] Plan sheet displays:
  - Source video thumbnail
  - Selected frame thumbnail
  - Frame timestamp
  - Duration and prompt
- [ ] Plan sheet shows progress during task execution
- [ ] Plan sheet shows download button on completion
- [ ] Error handling displays correctly

### Backend Tests

- [ ] `/editor/chat` endpoint receives extend_metadata
- [ ] `_handle_extend_scene` correctly parses extend_metadata
- [ ] `frame_based_extend_task` is dispatched with correct parameters
- [ ] Task Step 1: Video trimming works (ffmpeg)
- [ ] Task Step 2: Frame extraction works (or uses provided frame)
- [ ] Task Step 3: Veo API generates extended video
- [ ] Task Step 4: Video concatenation works (VideoComposer)
- [ ] Task Step 5: Supabase upload works
- [ ] Task Step 6: SceneManager saves scene
- [ ] Task progress updates correctly (10%, 20%, 30%, ..., 100%)
- [ ] Error handling for:
  - Missing source video
  - FFmpeg failures
  - Veo API failures
  - Concatenation failures
  - Upload failures
- [ ] Temp directory cleanup works

### Integration Tests

- [ ] End-to-end: Select video → select frame → extend → receive merged video
- [ ] Multiple extends in sequence
- [ ] Extend with different durations (4s, 8s, 12s, 20s)
- [ ] Extend from different frame positions (start, middle, end)
- [ ] Agent mode compatibility
- [ ] Session persistence across page refresh

---

## 📁 File Structure

```
real-estate-video-generator/
├── web_ui.py                      # MODIFY: editor_chat(), _handle_extend_scene()
├── tasks.py                       # ADD: frame_based_extend_task()
├── video_composer.py              # USE: simple_concatenate(), compose_with_transitions()
├── frame_editor.py                # USE: extract_frames()
├── templates/
│   └── video_editor_ui.html       # MODIFY: Multiple sections
│       ├── CSS (video-mode-popup styles)
│       ├── State management (add extendMode)
│       ├── Mode selection handler (line 1392)
│       ├── Add: openVideoSlotSelector()
│       ├── Add: openFrameSelector()
│       ├── Add: selectVideoSlot()
│       ├── Add: selectFrame()
│       ├── Modify: sendMessage() payload
│       └── Modify: generatePlanSheetHTML()
└── SPEC_FRAME_BASED_EXTEND.md     # THIS FILE
```

---

## 🔄 Implementation Order

1. **Frontend Foundation (Day 1)**
   - Add extendMode to state
   - Auto-populate "extend:v?" on mode selection
   - Create openVideoSlotSelector() and modal HTML

2. **Frontend Frame Selection (Day 1-2)**
   - Create openFrameSelector()
   - Integrate with extractFramesForVideo()
   - Update chatInput with selected video/frame

3. **Frontend-Backend Integration (Day 2)**
   - Modify sendMessage() to include extend_metadata
   - Update plan sheet generation for frame preview

4. **Backend Task (Day 3-4)**
   - Create frame_based_extend_task in tasks.py
   - Implement video trimming (FFmpeg)
   - Implement frame extraction (FFmpeg)
   - Integrate Veo API generation
   - Implement video concatenation (VideoComposer)

5. **Backend Routing (Day 4)**
   - Modify _handle_extend_scene() to handle extend_metadata
   - Pass metadata to frame_based_extend_task
   - Return plan sheet with frame data

6. **Testing & Polish (Day 5)**
   - End-to-end testing
   - Error handling
   - UI polish
   - Performance optimization

---

## 📝 Notes

### Design Decisions

1. **Why "v?" and "f?" format?**
   - Clear indication that user needs to make a selection
   - Easy to parse and validate
   - Familiar pattern (similar to command-line arguments)

2. **Why extract frames on demand?**
   - Avoid pre-loading all frames for all videos
   - Reduce initial load time
   - Only extract when user shows intent to extend

3. **Why simple_concatenate instead of transitions?**
   - Frame-based extend should be seamless
   - Transition might create visible discontinuity
   - Can add transition option later as enhancement

4. **Why trim original video?**
   - User wants to extend FROM a specific point
   - Merging full original + extension doesn't make sense
   - Trimming gives clean starting point

### Future Enhancements

- [ ] Support multiple frame selections (extend multiple points)
- [ ] Add transition options (fade, wipe, etc.)
- [ ] Preview trimmed portion before extending
- [ ] Allow editing frame before extending (brightness, contrast, etc.)
- [ ] Batch extend (extend all videos in sequence)
- [ ] Custom duration per extend
- [ ] Voice-over generation for extended portions

---

## 🎉 Success Criteria

The implementation is complete when:

1. ✅ User can select Extend mode → see "extend:v?"
2. ✅ User can click "v?" → see video slot selector
3. ✅ User can select video slot → see frame selector
4. ✅ User can select frame → see "extend:v2:f3" format
5. ✅ User can send → see plan sheet with frame preview
6. ✅ Plan sheet shows progress through all stages
7. ✅ Final merged video is downloadable
8. ✅ Merged video = original (up to frame) + extended video
9. ✅ All error cases handled gracefully
10. ✅ Performance is acceptable (< 5min for typical extend)

---

**End of Specification**

Ready for CLI implementation! 🚀
