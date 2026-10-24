from __future__ import annotations

import asyncio
import base64
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .audio_codec import OpusPcm16Decoder, Pcm16OpusEncoder
from .linx_client import LingxiSession, configured_device_id


ROOT = Path(__file__).parent
app = FastAPI(title="Don't Let It Hear - Link Probe")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@dataclass
class Room:
    room_id: str
    created_at: float = field(default_factory=time.time)
    players: dict[str, str] = field(default_factory=dict)
    alert_level: int = 0
    remaining_time: int = 90
    action_history: list[dict[str, Any]] = field(default_factory=list)
    sockets: dict[str, WebSocket] = field(default_factory=dict, repr=False)

    def public_state(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "players": self.players,
            "alert_level": self.alert_level,
            "remaining_time": self.remaining_time,
            "action_history": self.action_history[-20:],
        }


rooms: dict[str, Room] = {}
rooms_lock = asyncio.Lock()
# Lingxi invokes MCP with this session ID. It is registered after the browser
# session completes the Lingxi hello handshake.
lingxi_sessions: dict[str, tuple[str, str]] = {}


async def relay_lingxi(session: LingxiSession, browser: WebSocket) -> None:
    """Forward only safe upstream results; credentials remain server-side."""
    tts_packets: list[bytes] = []
    decoder = OpusPcm16Decoder()
    try:
        async for message in session.receive():
            if isinstance(message, str):
                data = json.loads(message)
                await browser.send_json({"type": "linx_event", "event": data})
                if data.get("type") == "tts" and data.get("state") == "stop":
                    if tts_packets:
                        wav = decoder.wav(tts_packets)
                        tts_packets.clear()
                        await browser.send_json({
                            "type": "linx_tts_wav",
                            "audio": base64.b64encode(wav).decode("ascii"),
                        })
                    await browser.send_json({"type": "linx_turn_complete"})
                    await session.close()
                    return
            else:
                tts_packets.append(message)
    except Exception as error:
        await browser.send_json({"type": "linx_error", "message": str(error)})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


def mcp_result(request_id: Any, content: str, structured: dict[str, Any]) -> JSONResponse:
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [{"type": "text", "text": content}],
            "structuredContent": structured,
            "isError": False,
        },
    })


def mcp_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


@app.get("/mcp")
async def mcp_info() -> JSONResponse:
    """A health/readiness response for tunnel and operator checks."""
    return JSONResponse({"name": "dont-let-it-hear-mcp", "transport": "streamable-http"})


@app.post("/mcp")
@app.post("/mcp/message")
async def mcp_message(request: Request) -> Response:
    """Minimal Streamable HTTP JSON-RPC MCP server for the game state machine."""
    message = await request.json()
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": message.get("params", {}).get("protocolVersion", "2025-03-26"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dont-let-it-hear-mcp", "version": "0.1.0"},
            },
        })
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": [
                {
                    "name": "game.get_state",
                    "description": "Read the current game state for this player's room.",
                    "inputSchema": {"type": "object", "properties": {}},
                },
                {
                    "name": "game.apply_action",
                    "description": "Apply one validated in-game action for this player.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"action": {"type": "string", "description": "Short game action"}},
                        "required": ["action"],
                    },
                },
            ]},
        })
    if method != "tools/call":
        return mcp_error(request_id, -32601, f"Unsupported MCP method: {method}")

    session_id = request.headers.get("X-Linx-Session-Id", "")
    binding = lingxi_sessions.get(session_id)
    if binding is None:
        return mcp_error(request_id, -32001, "No active browser game session for this Lingxi session")
    room_id, player_id = binding
    room = rooms.get(room_id)
    if room is None:
        return mcp_error(request_id, -32002, "Game room no longer exists")

    params = message.get("params", {})
    tool_name = params.get("name")
    if tool_name == "game.get_state":
        state = room.public_state()
        return mcp_result(request_id, json.dumps(state, ensure_ascii=False), state)
    if tool_name == "game.apply_action":
        action = str(params.get("arguments", {}).get("action", "")).strip()[:40]
        if not action:
            return mcp_error(request_id, -32602, "action is required")
        forbidden = any(word in action for word in ("安静", "声音", "说话"))
        room.alert_level = min(5, room.alert_level + int(forbidden))
        event = {"type": "mcp_action", "player_id": player_id, "action": action, "forbidden": forbidden, "at": time.time()}
        room.action_history.append(event)
        await broadcast(room, {"type": "event", "event": event, "state": room.public_state()})
        state = room.public_state()
        return mcp_result(request_id, json.dumps(state, ensure_ascii=False), state)
    return mcp_error(request_id, -32602, f"Unknown game tool: {tool_name}")


@app.post("/api/rooms")
async def create_room() -> dict[str, Any]:
    room_id = secrets.token_urlsafe(4).upper()
    async with rooms_lock:
        rooms[room_id] = Room(room_id=room_id)
    return {"room_id": room_id, "state": rooms[room_id].public_state()}


@app.get("/api/rooms/{room_id}")
async def get_room(room_id: str) -> dict[str, Any]:
    room = rooms.get(room_id.upper())
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return room.public_state()


async def broadcast(room: Room, message: dict[str, Any]) -> None:
    stale: list[str] = []
    for player_id, socket in list(room.sockets.items()):
        try:
            await socket.send_json(message)
        except Exception:
            stale.append(player_id)
    for player_id in stale:
        room.sockets.pop(player_id, None)


@app.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str, player_id: str = "") -> None:
    room = rooms.get(room_id.upper())
    if room is None:
        await websocket.close(code=4404, reason="room not found")
        return
    await websocket.accept()
    player_id = player_id.strip() or f"player-{secrets.token_hex(2)}"
    room.sockets[player_id] = websocket
    room.players[player_id] = player_id
    await websocket.send_json({"type": "connected", "player_id": player_id, "state": room.public_state()})
    await broadcast(room, {"type": "state", "state": room.public_state()})
    lingxi: LingxiSession | None = None
    lingxi_task: asyncio.Task[None] | None = None
    encoder: Pcm16OpusEncoder | None = None
    try:
        while True:
            frame = await websocket.receive()
            if frame.get("bytes") is not None:
                if encoder is not None and lingxi is not None:
                    for opus in encoder.feed(frame["bytes"]):
                        await lingxi.send_opus(opus)
                else:
                    # Phase-one audio probe: echo browser MediaRecorder bytes back.
                    await websocket.send_bytes(frame["bytes"])
                continue
            if frame.get("text") is None:
                continue
            import json
            message = json.loads(frame["text"])
            kind = message.get("type")
            if kind == "say":
                text = str(message.get("text", "")).strip()[:200]
                if not text:
                    continue
                event = {"type": "say", "player_id": player_id, "text": text, "at": time.time()}
                room.action_history.append(event)
                await broadcast(room, {"type": "event", "event": event, "state": room.public_state()})
            elif kind == "action":
                action = str(message.get("action", "")).strip()[:40]
                if not action:
                    continue
                # Placeholder rule: every forbidden-word hit raises the alert by one.
                forbidden = any(word in action for word in ("安静", "声音", "说话"))
                room.alert_level = min(5, room.alert_level + int(forbidden))
                event = {"type": "action", "player_id": player_id, "action": action, "forbidden": forbidden, "at": time.time()}
                room.action_history.append(event)
                await broadcast(room, {"type": "event", "event": event, "state": room.public_state()})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "audio_start":
                await websocket.send_json({"type": "audio_ready", "mime": message.get("mime", "unknown")})
            elif kind == "audio_end":
                await websocket.send_json({"type": "audio_complete"})
            elif kind == "linx_start":
                # A completed relay closes the upstream socket. Retain no stale
                # per-turn state so the next browser recording starts fresh.
                if lingxi is not None and lingxi.socket is None:
                    lingxi = None
                    encoder = None
                    lingxi_task = None
                if lingxi is not None:
                    await websocket.send_json({"type": "linx_error", "message": "上一轮仍在生成回复，请等播放完成后再开始"})
                    continue
                sample_rate = int(message.get("sample_rate", 0))
                if sample_rate != 16000:
                    await websocket.send_json({"type": "linx_error", "message": "Expected 16 kHz PCM16 from browser"})
                    continue
                try:
                    lingxi = LingxiSession(configured_device_id())
                    hello = await lingxi.connect()
                    session_id = hello.get("session_id")
                    if session_id:
                        lingxi_sessions[session_id] = (room.room_id, player_id)
                    encoder = Pcm16OpusEncoder()
                    await lingxi.start_listening()
                    lingxi_task = asyncio.create_task(relay_lingxi(lingxi, websocket))
                    await websocket.send_json({"type": "linx_ready", "session_id": hello.get("session_id")})
                except Exception as error:
                    if lingxi is not None:
                        await lingxi.close()
                    lingxi = None
                    encoder = None
                    await websocket.send_json({"type": "linx_error", "message": str(error)})
            elif kind == "linx_end":
                if lingxi is not None:
                    for opus in (encoder.flush() if encoder else []):
                        await lingxi.send_opus(opus)
                    await lingxi.stop_listening()
                    await websocket.send_json({"type": "linx_input_complete"})
    except (WebSocketDisconnect, RuntimeError):
        # Starlette 1.x raises WebSocketDisconnected (a RuntimeError subclass)
        # if the peer disconnects between loop iterations.
        pass
    finally:
        if lingxi_task is not None:
            lingxi_task.cancel()
        if lingxi is not None:
            if lingxi.socket is not None:
                # The Lingxi session ID is only useful while this socket lives.
                stale_ids = [key for key, value in lingxi_sessions.items() if value == (room.room_id, player_id)]
                for stale_id in stale_ids:
                    lingxi_sessions.pop(stale_id, None)
            await lingxi.close()
        if room.sockets.get(player_id) is websocket:
            room.sockets.pop(player_id, None)
        room.players.pop(player_id, None)
        await broadcast(room, {"type": "state", "state": room.public_state()})
