#!/usr/bin/env python3
"""
MCP Server for Real Estate Video Pipeline

Exposes all 5 video APIs as MCP tools for ChatGPT orchestration:
- generate_video
- extend_video
- extract_frames
- edit_frame
- stitch_videos
- get_status
"""

import os
import sys
import json
import logging
from typing import Any, Optional

import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('mcp_server.log'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Backend configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

# Initialize MCP server
app = Server("real-estate-video-pipeline")


def make_request(method: str, endpoint: str, **kwargs) -> dict:
    """
    Make HTTP request to Flask backend.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint path
        **kwargs: Additional arguments for requests

    Returns:
        JSON response from backend
    """
    url = f"{BACKEND_URL}{endpoint}"
    logger.info(f"Making {method} request to {url}")

    try:
        response = requests.request(method, url, **kwargs, timeout=300)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Request successful: {endpoint}")
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"Request failed: {endpoint} - {str(e)}")
        return {
            "error": str(e),
            "status": "error"
        }


@app.list_tools()
async def list_tools() -> list[Tool]:
    """
    List all available MCP tools.
    """
    return [
        Tool(
            name="generate_video",
            description="Generate a new video from a text prompt. Returns a task_id for status tracking.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Text description of the video to generate"
                    },
                    "video_id": {
                        "type": "string",
                        "description": "Optional video ID (session ID) to use. Auto-generated if not provided."
                    }
                },
                "required": ["prompt"]
            }
        ),
        Tool(
            name="extend_video",
            description="Extend an existing video with additional duration. Returns a task_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "ID of the video to extend"
                    },
                    "extra_duration": {
                        "type": "integer",
                        "description": "Additional seconds to add (4-20)",
                        "minimum": 4,
                        "maximum": 20
                    }
                },
                "required": ["video_id", "extra_duration"]
            }
        ),
        Tool(
            name="extract_frames",
            description="Extract frames from a video at specified FPS. Returns a task_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "ID of the video to extract frames from"
                    },
                    "fps": {
                        "type": "integer",
                        "description": "Frames per second to extract (1-30)",
                        "minimum": 1,
                        "maximum": 30,
                        "default": 1
                    }
                },
                "required": ["video_id"]
            }
        ),
        Tool(
            name="edit_frame",
            description="Edit a specific frame using AI with natural language instructions. Returns a task_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {
                        "type": "string",
                        "description": "ID of the video containing the frame"
                    },
                    "frame_index": {
                        "type": "integer",
                        "description": "Index of the frame to edit (0-based)",
                        "minimum": 0
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Natural language instruction for how to edit the frame"
                    }
                },
                "required": ["video_id", "frame_index", "instruction"]
            }
        ),
        Tool(
            name="stitch_videos",
            description="Stitch multiple videos together into a single video. Returns a task_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_ids": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "Array of video IDs to stitch together in order",
                        "minItems": 2
                    },
                    "transition_type": {
                        "type": "string",
                        "description": "Type of transition between videos (cut, fade, etc.)",
                        "enum": ["cut", "fade"],
                        "default": "fade"
                    }
                },
                "required": ["video_ids"]
            }
        ),
        Tool(
            name="get_status",
            description="Check the status of an async video processing task.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task ID returned from a previous operation"
                    }
                },
                "required": ["task_id"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """
    Execute an MCP tool by proxying to Flask backend.
    """
    logger.info(f"Tool called: {name} with arguments: {arguments}")

    try:
        if name == "generate_video":
            result = make_request(
                "POST",
                "/api/generate",
                json={
                    "prompt": arguments["prompt"],
                    "video_id": arguments.get("video_id")
                }
            )

        elif name == "extend_video":
            result = make_request(
                "POST",
                "/api/extend",
                json={
                    "video_id": arguments["video_id"],
                    "extra_duration": arguments["extra_duration"]
                }
            )

        elif name == "extract_frames":
            result = make_request(
                "POST",
                "/api/extract",
                json={
                    "video_id": arguments["video_id"],
                    "fps": arguments.get("fps", 1)
                }
            )

        elif name == "edit_frame":
            result = make_request(
                "POST",
                "/api/edit",
                json={
                    "video_id": arguments["video_id"],
                    "frame_index": arguments["frame_index"],
                    "instruction": arguments["instruction"]
                }
            )

        elif name == "stitch_videos":
            result = make_request(
                "POST",
                "/api/stitch",
                json={
                    "video_ids": arguments["video_ids"],
                    "transition_type": arguments.get("transition_type", "fade")
                }
            )

        elif name == "get_status":
            result = make_request(
                "GET",
                f"/api/task/{arguments['task_id']}/status"
            )

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.error(f"Tool execution failed: {name} - {str(e)}")
        error_result = {"error": str(e), "status": "error"}
        return [TextContent(type="text", text=json.dumps(error_result, indent=2))]


async def main():
    """Run the MCP server."""
    logger.info("Starting Real Estate Video Pipeline MCP Server")
    logger.info(f"Backend URL: {BACKEND_URL}")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
