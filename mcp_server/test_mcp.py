import sys
from unittest.mock import MagicMock

# Mock mcp modules before importing server
mcp_mock = MagicMock()
sys.modules["mcp"] = mcp_mock
sys.modules["mcp.server"] = mcp_mock
sys.modules["mcp.server.stdio"] = mcp_mock
sys.modules["mcp.types"] = mcp_mock

# Define mock types needed for server.py
class MockTool:
    def __init__(self, name, description, inputSchema):
        self.name = name
        self.description = description
        self.inputSchema = inputSchema

class MockTextContent:
    def __init__(self, type, text):
        self.type = type
        self.text = text

mcp_mock.Tool = MockTool
mcp_mock.TextContent = MockTextContent

# Make Server class return a mock instance that handles decorators correctly
class MockServer:
    def __init__(self, name):
        self.name = name
    
    def list_tools(self):
        def decorator(func):
            return func
        return decorator

    def call_tool(self):
        def decorator(func):
            return func
        return decorator
    
    def run(self, *args, **kwargs):
        pass
    
    def create_initialization_options(self):
        pass

mcp_mock.Server = MockServer

# Now import server
from server import call_tool

import asyncio
import os
import json
from unittest.mock import patch

async def test_generate_video():
    print("Testing generate_video...")
    
    # Create dummy image
    with open("test_image.jpg", "wb") as f:
        f.write(b"dummy image content")
    
    try:
        # Mock requests.request
        with patch('requests.request') as mock_request:
            mock_response = MagicMock()
            mock_response.json.return_value = {"task_id": "test_task_id", "status": "running"}
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response

            # Call tool
            arguments = {
                "prompt": "Test video",
                "image_path": os.path.abspath("test_image.jpg")
            }
            
            result = await call_tool("generate_video", arguments)
            
            # Verify result
            print(f"Result: {result}")
            
            # Verify request args
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            print(f"Call args: {call_args}")
            
            assert call_args[0][0] == "POST"
            assert "/api/generate" in call_args[0][1]
            assert "files" in call_args[1]
            assert "image" in call_args[1]["files"]
            assert call_args[1]["data"]["prompt"] == "Test video"
            
            print("generate_video test PASSED")

    finally:
        if os.path.exists("test_image.jpg"):
            os.remove("test_image.jpg")

async def test_extend_video():
    print("\nTesting extend_video...")
    
    # Create dummy image
    with open("test_image.jpg", "wb") as f:
        f.write(b"dummy image content")
    
    try:
        # Mock requests.request
        with patch('requests.request') as mock_request:
            mock_response = MagicMock()
            mock_response.json.return_value = {"task_id": "test_task_id", "status": "running"}
            mock_response.raise_for_status.return_value = None
            mock_request.return_value = mock_response

            # Call tool
            arguments = {
                "video_id": "test_video_id",
                "extra_duration": 5,
                "image_path": os.path.abspath("test_image.jpg")
            }
            
            result = await call_tool("extend_video", arguments)
            
            # Verify result
            print(f"Result: {result}")
            
            # Verify request args
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            print(f"Call args: {call_args}")
            
            assert call_args[0][0] == "POST"
            assert "/api/extend" in call_args[0][1]
            assert "files" in call_args[1]
            assert "image" in call_args[1]["files"]
            assert call_args[1]["data"]["video_id"] == "test_video_id"
            
            print("extend_video test PASSED")

    finally:
        if os.path.exists("test_image.jpg"):
            os.remove("test_image.jpg")

if __name__ == "__main__":
    asyncio.run(test_generate_video())
    asyncio.run(test_extend_video())
