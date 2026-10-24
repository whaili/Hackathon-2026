"""Small server-side Lingxi WebSocket client.

The browser must never receive the OTA token or Lingxi custom headers. This
module accepts browser-independent raw Opus frames and keeps those details on
the game backend.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, AsyncIterator
from urllib.request import Request, urlopen

import websockets


OTA_URL = "https://xrobo.qiniuapi.com/v1/ota/"
DEFAULT_WS_URL = "wss://xrobo-io.qiniuapi.com/v1/ws/"


def _ota_payload(device_id: str, client_id: str) -> dict[str, Any]:
    return {
        "version": 0,
        "uuid": client_id,
        "application": {"name": "dont-let-it-hear", "version": "0.1.0"},
        "ota": {"label": "dont-let-it-hear"},
        "board": {"type": "server", "ssid": "", "rssi": 0, "channel": 0, "ip": "", "mac": device_id},
        "flash_size": 0,
        "minimum_free_heap_size": 0,
        "mac_address": device_id,
        "chip_model_name": "server",
        "chip_info": {"model": 0, "cores": 0, "revision": 0, "features": 0},
        "partition_table": [],
    }


def request_ota(device_id: str, client_id: str) -> tuple[str, str]:
    headers = {
        "Activation-Version": "1",
        "Device-Id": device_id,
        "Client-Id": client_id,
        "User-Agent": "dont-let-it-hear/0.1.0",
        "Accept-Language": "zh-CN",
        "Content-Type": "application/json",
    }
    request = Request(OTA_URL, data=json.dumps(_ota_payload(device_id, client_id)).encode(), headers=headers)
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
    websocket_info = result.get("websocket", {})
    token = websocket_info.get("token")
    ws_url = websocket_info.get("url") or DEFAULT_WS_URL
    if not token:
        raise RuntimeError(f"OTA returned no WebSocket token: {result}")
    return token, ws_url


class LingxiSession:
    def __init__(self, device_id: str, client_id: str | None = None) -> None:
        self.device_id = device_id
        self.client_id = client_id or str(uuid.uuid4())
        self.socket: Any = None

    async def connect(self) -> dict[str, Any]:
        token, ws_url = await asyncio.to_thread(request_ota, self.device_id, self.client_id)
        self.socket = await websockets.connect(
            ws_url,
            additional_headers={
                "Authorization": f"Bearer {token}",
                "Device-Id": self.device_id,
                "Client-Id": self.client_id,
                "Protocol-Version": "1",
            },
            max_size=None,
        )
        await self.socket.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket"}))
        while True:
            message = await self.socket.recv()
            if isinstance(message, str):
                data = json.loads(message)
                if data.get("type") == "hello":
                    return data

    async def start_listening(self, mode: str = "manual") -> None:
        if mode not in {"manual", "auto", "realtime"}:
            raise ValueError(f"Unsupported listen mode: {mode}")
        await self.socket.send(json.dumps({"type": "listen", "state": "start", "mode": mode}))

    async def send_opus(self, frame: bytes) -> None:
        await self.socket.send(frame)

    async def stop_listening(self) -> None:
        await self.socket.send(json.dumps({"type": "listen", "state": "stop"}))

    async def receive(self) -> AsyncIterator[str | bytes]:
        while self.socket is not None:
            yield await self.socket.recv()

    async def close(self) -> None:
        if self.socket is not None:
            await self.socket.close()
            self.socket = None


def configured_device_id() -> str:
    device_id = os.environ.get("LINX_DEVICE_ID", "").strip()
    if not device_id:
        raise RuntimeError("LINX_DEVICE_ID is required")
    return device_id
