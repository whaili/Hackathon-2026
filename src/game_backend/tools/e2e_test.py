"""Replay the browser's exact Lingxi voice protocol against a deployed game backend.

Creates a room, opens a WebSocket connection the same way the browser page
does, starts a Lingxi session (`linx_start`), streams a 16kHz mono PCM16
audio file as the simulated microphone input, ends the turn (`linx_end`),
and prints every event relayed back until the turn completes.

This exercises the identical server code path a real browser session would
use -- the backend has no branch that distinguishes a real microphone from a
replayed PCM stream. Useful when you don't have a real microphone or can't
get past the deployment's self-signed TLS certificate in an automated
browser.

Usage:
    python3 e2e_test.py <path-to-16khz-mono-pcm16-file>

Generate a test phrase first with say.py (see README in this directory).

Environment variables:
    GAME_BASE_URL  Base HTTPS URL of the deployed game backend.
                   Default: https://10.210.34.33:18081
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
PLAYER_ID = "e2e-tester"

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE


def create_room() -> str:
    req = urllib.request.Request(f"{BASE_HTTP}/api/rooms", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as resp:
        data = json.loads(resp.read().decode())
        print(f"[http] room created: {data}")
        return data["room_id"]


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    pcm_file = sys.argv[1]

    room_id = create_room()
    url = f"{BASE_WS}/ws/{room_id}?player_id={PLAYER_ID}"
    print(f"[ws] connecting {url}")
    async with websockets.connect(url, ssl=ssl_ctx, open_timeout=15) as ws:
        print(f"[ws] << {await ws.recv()}")
        print(f"[ws] << {await ws.recv()}")

        await ws.send(json.dumps({"type": "linx_start", "sample_rate": 16000}))
        print("[ws] >> linx_start")

        ready = json.loads(await ws.recv())
        print(f"[ws] << {ready}")
        if ready.get("type") != "linx_ready":
            print("FAILED: did not receive linx_ready")
            return
        print(f"[ws] Lingxi session established: {ready.get('session_id')}")

        with open(pcm_file, "rb") as fh:
            pcm = fh.read()
        print(f"[audio] streaming {len(pcm)} bytes of 16kHz PCM16 from {pcm_file}")

        chunk = 1920  # 60ms at 16kHz / 16-bit mono
        for i in range(0, len(pcm), chunk):
            await ws.send(pcm[i : i + chunk])
            await asyncio.sleep(0.06)

        await ws.send(json.dumps({"type": "linx_end"}))
        print("[ws] >> linx_end")

        async for raw in ws:
            msg = json.loads(raw)
            msg_type = msg.get("type")
            if msg_type == "linx_tts_wav":
                print(f"[ws] << linx_tts_wav ({len(msg.get('audio', ''))} base64 chars, omitted)")
            else:
                print(f"[ws] << {msg}")
            if msg_type == "linx_turn_complete":
                print("[ws] turn complete, closing")
                break
            if msg_type == "linx_error":
                print("FAILED: linx_error received")
                break


if __name__ == "__main__":
    asyncio.run(main())
