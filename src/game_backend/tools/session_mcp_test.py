"""Call the MCP endpoint directly with a real session id, bypassing Lingxi.

Opens a real browser-protocol WebSocket session against the game backend
(same as e2e_test.py) to obtain a genuine, actively-mapped Lingxi session id,
then calls `tools/call` for both `game.get_state` and `game.apply_action`
directly against the public MCP endpoint using that session id.

This isolates the backend's MCP implementation and session-mapping security
model from Lingxi's own tool-dispatch behavior -- useful for telling apart
"our server is broken" from "Lingxi isn't calling our tools correctly".

Usage:
    python3 session_mcp_test.py

Environment variables:
    GAME_BASE_URL  Base HTTPS URL of the deployed game backend.
                   Default: https://10.210.34.33:18081
    MCP_URL        Public MCP endpoint URL (e.g. the Cloudflare Tunnel
                   currently configured in the Lingxi console). Required.
"""

import asyncio
import json
import os
import ssl
import sys
import urllib.request

import websockets

BASE_HTTP = os.environ.get("GAME_BASE_URL", "https://10.210.34.33:18081")
BASE_WS = BASE_HTTP.replace("https://", "wss://").replace("http://", "ws://")
MCP_URL = os.environ.get("MCP_URL", "")
PLAYER_ID = "mcp-direct-tester"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def create_room() -> str:
    req = urllib.request.Request(f"{BASE_HTTP}/api/rooms", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
        data = json.loads(resp.read().decode())
        print(f"[http] room created: {data}")
        return data["room_id"]


def call_mcp_tool(session_id: str, name: str, arguments: dict) -> dict:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    ).encode()
    req = urllib.request.Request(
        MCP_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-Linx-Session-Id": session_id,
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


async def main() -> None:
    if not MCP_URL:
        print("Set MCP_URL to the current Cloudflare Tunnel / MCP endpoint first.")
        raise SystemExit(1)

    room_id = create_room()
    url = f"{BASE_WS}/ws/{room_id}?player_id={PLAYER_ID}"
    async with websockets.connect(url, ssl=ssl_ctx, open_timeout=15) as ws:
        print(await ws.recv())
        print(await ws.recv())

        await ws.send(json.dumps({"type": "linx_start", "sample_rate": 16000}))
        ready = json.loads(await ws.recv())
        session_id = ready.get("session_id")
        print(f"[test] active Lingxi session_id = {session_id}, room = {room_id}")

        print("\n=== tools/call game.get_state ===")
        print(json.dumps(call_mcp_tool(session_id, "game.get_state", {}), ensure_ascii=False, indent=2))

        print("\n=== tools/call game.apply_action: 拿起钥匙 ===")
        print(
            json.dumps(
                call_mcp_tool(session_id, "game.apply_action", {"action": "拿起钥匙"}),
                ensure_ascii=False,
                indent=2,
            )
        )

        await ws.send(json.dumps({"type": "linx_end"}))
        try:
            async with asyncio.timeout(5):
                async for raw in ws:
                    print(f"[ws] << {raw[:200]}")
        except (asyncio.TimeoutError, TimeoutError):
            pass


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        print("Note: asyncio.timeout requires Python 3.11+; drain loop at the end may raise on older versions.")
    asyncio.run(main())
