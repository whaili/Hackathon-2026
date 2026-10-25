"""Run a two-player, text-driven end-to-end game session.

The two clients use the same HTTP and WebSocket protocol as the browser, but
send ``say`` messages instead of microphone frames.  This makes multiplayer
regression tests fast, repeatable, and safe to run in CI.

Examples::

    # against a local server
    GAME_BASE_URL=http://127.0.0.1:8080 python3 \
      src/game_backend/tools/multiplayer_text_e2e.py

    # against the deployed HTTPS endpoint (self-signed certificate is OK)
    GAME_BASE_URL=https://10.210.34.33:18081 python3 \
      src/game_backend/tools/multiplayer_text_e2e.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import websockets


BASE_HTTP = os.environ.get("GAME_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
BASE_WS = BASE_HTTP.replace("https://", "wss://").replace("http://", "ws://")


def tls_context() -> ssl.SSLContext | None:
    if not BASE_WS.startswith("wss://"):
        return None
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def create_room() -> str:
    body = json.dumps({"mode": "duo"}).encode()
    request = urllib.request.Request(
        f"{BASE_HTTP}/api/rooms", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10, context=tls_context()) as response:
        payload = json.loads(response.read().decode())
    if payload.get("state", {}).get("mode") != "duo":
        raise AssertionError(f"server created the wrong mode: {payload}")
    return payload["room_id"]


@dataclass
class ClientTrace:
    player_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def events(self) -> list[dict[str, Any]]:
        return [message["event"] for message in self.messages if message.get("type") == "event"]


async def receive_until_event(ws: Any, trace: ClientTrace, event_type: str) -> dict[str, Any]:
    """Drain state broadcasts until the requested event arrives."""
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.01, deadline - asyncio.get_running_loop().time())))
        trace.messages.append(message)
        if message.get("type") == "event" and message.get("event", {}).get("type") == event_type:
            return message
        if message.get("event", {}).get("type") in {"game_lost", "alert_raised", "clarification_needed"}:
            raise AssertionError(f"unexpected event waiting for {event_type}: {message}")


async def receive_until_type(ws: Any, trace: ClientTrace, message_type: str) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=max(0.01, deadline - asyncio.get_running_loop().time())))
        trace.messages.append(message)
        if message.get("type") == message_type:
            return message


async def drain_same_event(
    sockets: dict[str, Any], traces: dict[str, ClientTrace], event_type: str,
) -> dict[str, Any]:
    results = await asyncio.gather(*(
        receive_until_event(sockets[player], traces[player], event_type)
        for player in sockets
    ))
    states = [result["state"] for result in results]
    if states[0] != states[1]:
        raise AssertionError(f"players received different states after {event_type}: {states}")
    if traces["alice"].events != traces["bob"].events:
        raise AssertionError("players received different event histories")
    return results[0]


async def send_say(
    sockets: dict[str, Any], traces: dict[str, ClientTrace], player: str, text: str,
    expected: str = "action_applied",
) -> dict[str, Any]:
    await sockets[player].send(json.dumps({"type": "say", "text": text}))
    # Every action produces a transcript followed by the resulting event.
    return await drain_same_event(sockets, traces, expected)


async def run() -> dict[str, Any]:
    room_id = create_room()
    socket_options = {"ssl": tls_context()} if BASE_WS.startswith("wss://") else {}
    players = ("alice", "bob")
    sockets: dict[str, Any] = {}
    traces = {player: ClientTrace(player) for player in players}
    try:
        for player in players:
            sockets[player] = await websockets.connect(
                f"{BASE_WS}/ws/{room_id}?player_id={player}",
                open_timeout=15, **socket_options,
            )
            # connected + initial state
            for _ in range(2):
                traces[player].messages.append(json.loads(await sockets[player].recv()))

        await sockets["alice"].send(json.dumps({"type": "game_start"}))
        started = await drain_same_event(sockets, traces, "game_started")
        briefings = await asyncio.gather(*(
            receive_until_type(sockets[player], traces[player], "private_briefing")
            for player in players
        ))
        if briefings[0]["role"] == briefings[1]["role"]:
            raise AssertionError("players received the same private role briefing")

        for stage in range(3):
            # The harness combines two independent observations. A production
            # AI player adapter must exchange them through dialogue, not peek
            # at the other player's trace.
            if stage == 2:
                await send_say(sockets, traces, "bob", "确认撤离", "choice_recorded")
                await asyncio.gather(*(receive_until_type(sockets[p], traces[p], "private_briefing") for p in players))
                await send_say(sockets, traces, "alice", "确认撤离", "game_won")
                briefings = await asyncio.gather(*(receive_until_type(sockets[p], traces[p], "private_briefing") for p in players))
                continue
            scene = briefings[0]["text"]
            target = re.search(r"安全符号是(.*?)。", briefings[1]["text"]).group(1)
            signals = re.search(re.escape(target) + r"对应(.*?)，也可以描述为(.*?)(?:；|。)", scene).groups()
            await send_say(sockets, traces, "bob", f"{'识破' if stage else '授权'}{target}", "authorization_granted")
            # Authorization also refreshes the private briefing.
            await asyncio.gather(*(receive_until_type(sockets[p], traces[p], "private_briefing") for p in players))
            forbidden = traces["alice"].messages[-2]["state"]["forbidden_words"]
            phrase = next(signal for signal in signals if not any(word in signal for word in forbidden))
            await send_say(sockets, traces, "alice", f"校准{phrase}", "game_won" if stage == 2 else "stage_completed")
            briefings = await asyncio.gather(*(receive_until_type(sockets[p], traces[p], "private_briefing") for p in players))

        final_state = next(message["state"] for message in reversed(traces["alice"].messages) if "state" in message)
        if final_state.get("phase") != "won":
            raise AssertionError(f"expected a win, got {final_state}")
        if final_state.get("completed_items") != ["接通能源", "辨认伪装", "共同抉择"]:
            raise AssertionError(f"unexpected item order: {final_state.get('completed_items')}")

        all_events = traces["alice"].events
        return {
            "ok": True,
            "room_id": room_id,
            "players": list(players),
            "event_count": len(all_events),
            "player_driver": "deterministic clue parser (not an AI player)",
            "event_types": [event["type"] for event in all_events],
            "final_state": final_state,
            "assertions": {
                "both_clients_observed_every_transition": True,
                "shared_state_after_each_transition": True,
                "players_completed_duo_challenge": True,
                "private_role_briefings_are_distinct": True,
                "listener_learned_from_spoken_phrase": any(event["type"] == "listener_learned" for event in all_events),
            },
        }
    finally:
        await asyncio.gather(*(socket.close() for socket in sockets.values()), return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit only the machine-readable report")
    args = parser.parse_args()
    try:
        report = asyncio.run(run())
    except Exception as error:
        report = {"ok": False, "error": str(error), "base_url": BASE_HTTP}
        print(json.dumps(report, ensure_ascii=False, indent=None if args.json else 2))
        raise SystemExit(1)
    print(json.dumps(report, ensure_ascii=False, indent=None if args.json else 2))


if __name__ == "__main__":
    main()
