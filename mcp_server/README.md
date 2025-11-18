# Real Estate Video Pipeline MCP Server

Model Context Protocol (MCP) server that exposes the video pipeline APIs as tools for ChatGPT orchestration.

## Overview

This MCP server acts as a bridge between ChatGPT (MCP client) and the Flask backend, allowing natural language orchestration of the video generation pipeline:

```
generate → extend → extract → edit → stitch
```

## Installation

```bash
cd mcp_server
pip install -r requirements.txt
```

## Configuration

Set the backend URL (defaults to http://localhost:5000):

```bash
export BACKEND_URL=http://localhost:5000
```

## Running the Server

```bash
python server.py
```

The server runs in stdio mode and communicates with the MCP client via stdin/stdout.

## Available Tools

### 1. generate_video
Generate a new video from a text prompt.

**Arguments:**
- `prompt` (string, required): Text description of the video
- `video_id` (string, optional): Video ID to use

**Returns:** `task_id` for status tracking

### 2. extend_video
Extend an existing video with additional duration.

**Arguments:**
- `video_id` (string, required): ID of the video to extend
- `extra_duration` (integer, required): Additional seconds (4-20)

**Returns:** `task_id`

### 3. extract_frames
Extract frames from a video at specified FPS.

**Arguments:**
- `video_id` (string, required): ID of the video
- `fps` (integer, optional): Frames per second (1-30, default: 1)

**Returns:** `task_id`

### 4. edit_frame
Edit a specific frame using AI instructions.

**Arguments:**
- `video_id` (string, required): ID of the video
- `frame_index` (integer, required): Frame index (0-based)
- `instruction` (string, required): Natural language editing instruction

**Returns:** `task_id`

### 5. stitch_videos
Stitch multiple videos together.

**Arguments:**
- `video_ids` (array, required): Array of video IDs to stitch
- `transition_type` (string, optional): "cut" or "fade" (default: "fade")

**Returns:** `task_id`

### 6. get_status
Check the status of an async task.

**Arguments:**
- `task_id` (string, required): Task ID from a previous operation

**Returns:** Task status with output_url when completed
