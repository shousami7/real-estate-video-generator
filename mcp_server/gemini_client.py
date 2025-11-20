"""
Example Gemini-backed MCP client for the real-estate video pipeline.

This script:
- Starts the local MCP server over stdio (spawns `python server.py`)
- Uses Gemini to decide which MCP tool to call based on your prompt
- Calls the tool via MCP and prints the result

Prereqs (run from repo root or this directory):
  pip install -r requirements.txt google-genai anyio

Env vars:
- GOOGLE_API_KEY: required for Gemini (unless using Vertex AI)
- GOOGLE_CLOUD_PROJECT: required for Vertex AI
- GOOGLE_CLOUD_LOCATION: required for Vertex AI (e.g. us-central1)
- BACKEND_URL: backend Flask URL for the MCP server (default: http://localhost:5000)
- GEMINI_MODEL: optional, defaults to gemini-2.0-flash-exp
- MCP_SERVER_CMD: optional override for the server command (default: python server.py)
"""

import json
import os
import shlex
from pathlib import Path

import anyio
from google import genai
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Implementation

BASE_DIR = Path(__file__).parent
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")


def _clean_json(text: str) -> str:
    """Strip code fences and whitespace from a model response."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()


def build_prompt(tools: list, user_message: str) -> str:
    tool_specs = [
        {"name": t.name, "description": t.description, "schema": t.inputSchema}
        for t in tools
    ]
    tools_json = json.dumps(tool_specs, indent=2)
    return (
        "You are an orchestrator that chooses exactly one MCP tool and arguments.\n"
        "Available tools:\n"
        f"{tools_json}\n\n"
        "User message:\n"
        f"{user_message}\n\n"
        "Respond with compact JSON only:\n"
        '{"tool": "<tool_name>", "arguments": { ... }, "reason": "<brief>"}'
    )


def pick_tool(gemini_client: genai.Client, tools: list, user_message: str) -> dict:
    prompt = build_prompt(tools, user_message)
    response = gemini_client.models.generate_content(
        model=DEFAULT_MODEL,
        contents=prompt,
    )
    cleaned = _clean_json(response.text or "")
    try:
        parsed = json.loads(cleaned)
        if not parsed.get("tool"):
            raise ValueError("No tool in response")
        return parsed
    except Exception as exc:
        raise RuntimeError(f"Failed to parse Gemini output: {exc}\nRaw: {cleaned}") from exc


def render_content(result) -> str:
    pieces = []
    for block in result.content:
        text = getattr(block, "text", None) or getattr(block, "data", None)
        if text:
            pieces.append(text)
    if result.structuredContent:
        pieces.append(json.dumps(result.structuredContent, indent=2))
    if not pieces:
        pieces.append(f"(empty response, isError={result.isError})")
    return "\n".join(pieces)


async def main() -> None:
    api_key = os.getenv("GOOGLE_API_KEY")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION")

    if project and location:
        print(f"Using Vertex AI (Project: {project}, Location: {location})")
        gemini_client = genai.Client(vertexai=True, project=project, location=location)
    elif api_key:
        print("Using Google AI Studio (API Key)")
        gemini_client = genai.Client(api_key=api_key)
    else:
        raise SystemExit("Missing credentials. Set GOOGLE_API_KEY or (GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION).")
    server_params = StdioServerParameters(
        command=cmd_parts[0],
        args=cmd_parts[1:],
        env={"BACKEND_URL": backend_url},
        cwd=str(BASE_DIR),
    )

    print(f"Starting MCP server via: {server_cmd} (cwd={BASE_DIR})")
    async with stdio_client(server_params) as (read_stream, write_stream):
        session = ClientSession(
            read_stream,
            write_stream,
            client_info=Implementation(name="gemini-mcp-client", version="0.1.0"),
        )
        await session.initialize()
        tools = (await session.list_tools()).tools
        print("Connected. Available tools:")
        for t in tools:
            print(f"- {t.name}: {t.description}")

        while True:
            user_message = await anyio.to_thread.run_sync(lambda: input("\nYou> ").strip())
            if not user_message:
                continue
            if user_message.lower() in {"exit", "quit"}:
                print("Exiting.")
                break

            try:
                plan = pick_tool(gemini_client, tools, user_message)
                print(f"Gemini picked: {plan.get('tool')} args={plan.get('arguments')}")
            except Exception as exc:
                print(f"[Gemini parsing error] {exc}")
                continue

            try:
                result = await session.call_tool(plan["tool"], plan.get("arguments", {}))
                print(render_content(result))
            except Exception as exc:
                print(f"[Tool call error] {exc}")


if __name__ == "__main__":
    anyio.run(main)
