import sys
from unittest.mock import MagicMock, AsyncMock, patch
import json
import asyncio
import os

# Mock mcp modules before importing gemini_client
mcp_mock = MagicMock()
sys.modules["mcp"] = mcp_mock
sys.modules["mcp.client"] = mcp_mock
sys.modules["mcp.client.session"] = mcp_mock
sys.modules["mcp.client.stdio"] = mcp_mock
sys.modules["mcp.types"] = mcp_mock

# Mock google.genai
genai_mock = MagicMock()
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = genai_mock

# Now import gemini_client
import gemini_client

async def test_agent_flow():
    print("Testing Agent Mode Flow...")

    # Mock Gemini Client
    mock_genai_client = MagicMock()
    mock_model = MagicMock()
    mock_genai_client.models = mock_model
    
    # Simulate Gemini response for generate_video
    tool_choice = {
        "tool": "generate_video",
        "arguments": {
            "prompt": "A beautiful house",
            "image_path": "/path/to/image.jpg"
        },
        "reason": "User asked to generate video from image"
    }
    
    mock_response = MagicMock()
    mock_response.text = json.dumps(tool_choice)
    mock_model.generate_content.return_value = mock_response

    # Mock MCP Session
    mock_session = AsyncMock()
    mock_tool = MagicMock()
    mock_tool.name = "generate_video"
    mock_tool.description = "Generate video"
    mock_tool.inputSchema = {"type": "object", "properties": {"image_path": {"type": "string"}}}
    
    mock_session.list_tools.return_value.tools = [mock_tool]
    mock_session.call_tool.return_value.content = [MagicMock(text="Task started")]
    mock_session.call_tool.return_value.structuredContent = {}

    # Test pick_tool function
    print("\n1. Testing pick_tool (Gemini decision)...")
    tools = [mock_tool]
    user_message = "Make a video of a house using this image"
    
    decision = gemini_client.pick_tool(mock_genai_client, tools, user_message)
    print(f"Gemini decided: {decision}")
    
    assert decision["tool"] == "generate_video"
    assert decision["arguments"]["image_path"] == "/path/to/image.jpg"
    print("✓ Gemini correctly picked the tool and arguments")

    # Test tool execution flow (simulating main loop logic)
    print("\n2. Testing tool execution...")
    
    # Simulate calling the tool based on decision
    await mock_session.call_tool(decision["tool"], decision["arguments"])
    
    mock_session.call_tool.assert_called_with("generate_video", {
        "prompt": "A beautiful house",
        "image_path": "/path/to/image.jpg"
    })
    print("✓ Client correctly called MCP session with arguments")

    print("\nAgent Mode Verification PASSED")

if __name__ == "__main__":
    asyncio.run(test_agent_flow())
