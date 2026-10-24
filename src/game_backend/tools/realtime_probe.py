"""Probe Lingxi listen modes with correctly encoded live-paced audio.

Unlike ``e2e_test.py``, this connects directly to Lingxi so it can select a
listen mode and observe messages *before* it sends ``listen/stop``.  It uses
the same PCM16 -> Opus encoder as the game backend; sending PCM bytes directly
to Lingxi is invalid and produces misleading silent failures.

Run from the repository root:

    set -a; . deploy/.env; set +a
    PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
      src/game_backend/tools/audio/query_state.pcm --mode realtime

The output labels every inbound event as PRE_STOP or POST_STOP.  A realtime
mode suitable for the game's continuous listener must produce usable ASR
events during PRE_STOP; merely replying after stop is a turn-based flow.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_backend.audio_codec import FRAME_SAMPLES, Pcm16OpusEncoder, SAMPLE_RATE
from game_backend.linx_client import LingxiSession, configured_device_id


@dataclass
class Observation:
    started_at: float
    stopped_at: float | None = None
    text_events_before_stop: list[dict[str, Any]] = field(default_factory=list)
    text_events_after_stop: list[dict[str, Any]] = field(default_factory=list)
    binary_before_stop: int = 0
    binary_after_stop: int = 0
    tts_finished: asyncio.Event = field(default_factory=asyncio.Event)
    tts_started: asyncio.Event = field(default_factory=asyncio.Event)

    def phase(self) -> str:
        return "PRE_STOP" if self.stopped_at is None else "POST_STOP"

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pcm_files",
        type=Path,
        nargs="+",
        help="one or more 16 kHz, mono, signed PCM16 utterances",
    )
    parser.add_argument("--mode", choices=("manual", "auto", "realtime"), default="realtime")
    parser.add_argument(
        "--observe-before-stop",
        type=float,
        default=2.0,
        help="seconds to leave the stream open after audio ends (default: 2)",
    )
    parser.add_argument(
        "--silence-between",
        type=float,
        default=1.2,
        help="seconds of actual silent microphone frames between utterances (default: 1.2)",
    )
    parser.add_argument(
        "--wait-for-tts-before-next",
        type=float,
        default=0,
        metavar="SECONDS",
        help="before utterance 2, wait up to SECONDS for TTS start to test barge-in",
    )
    parser.add_argument(
        "--observe-after-stop",
        type=float,
        default=12.0,
        help="maximum seconds to wait after stop (default: 12)",
    )
    return parser.parse_args()


async def receive_events(session: LingxiSession, observation: Observation) -> None:
    try:
        async for raw in session.receive():
            phase = observation.phase()
            elapsed = observation.elapsed_ms()
            if isinstance(raw, bytes):
                if observation.stopped_at is None:
                    observation.binary_before_stop += 1
                else:
                    observation.binary_after_stop += 1
                continue

            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                print(f"[{phase} {elapsed:8.1f} ms] non-JSON text: {raw!r}")
                continue
            compact = {
                key: event[key]
                for key in ("type", "state", "text", "error_code", "is_aborted")
                if key in event
            }
            print(f"[{phase} {elapsed:8.1f} ms] {json.dumps(compact, ensure_ascii=False)}")
            if observation.stopped_at is None:
                observation.text_events_before_stop.append(event)
            else:
                observation.text_events_after_stop.append(event)
            if event.get("type") == "tts" and event.get("state") == "stop":
                observation.tts_finished.set()
            if event.get("type") == "tts" and event.get("state") == "start":
                observation.tts_started.set()
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"[RECEIVER] closed: {type(error).__name__}: {error}")


async def send_pcm(session: LingxiSession, encoder: Pcm16OpusEncoder, pcm: bytes) -> int:
    pcm_per_frame = FRAME_SAMPLES * 2
    packets = 0
    for offset in range(0, len(pcm), pcm_per_frame):
        for packet in encoder.feed(pcm[offset : offset + pcm_per_frame]):
            await session.send_opus(packet)
            packets += 1
        # Preserve microphone pacing. A burst upload can change server VAD and
        # cannot demonstrate whether it recognizes speech while it is ongoing.
        await asyncio.sleep(FRAME_SAMPLES / SAMPLE_RATE)
    return packets


async def send_silence(session: LingxiSession, encoder: Pcm16OpusEncoder, seconds: float) -> int:
    packets = 0
    frames = round(seconds / (FRAME_SAMPLES / SAMPLE_RATE))
    silence = bytes(FRAME_SAMPLES * 2)
    for _ in range(frames):
        for packet in encoder.feed(silence):
            await session.send_opus(packet)
            packets += 1
        await asyncio.sleep(FRAME_SAMPLES / SAMPLE_RATE)
    return packets


async def main() -> None:
    args = parse_args()
    utterances = [path.read_bytes() for path in args.pcm_files]
    if any(not pcm or len(pcm) % 2 for pcm in utterances):
        raise SystemExit("Each input must be a non-empty whole-number PCM16 stream")

    duration = sum(len(pcm) for pcm in utterances) / (SAMPLE_RATE * 2)
    session = LingxiSession(configured_device_id())
    observation = Observation(started_at=time.perf_counter())
    receiver: asyncio.Task[None] | None = None
    try:
        hello = await session.connect()
        print(f"[HELLO] session established; mode={args.mode}, {len(utterances)} utterance(s), audio={duration:.2f}s")
        await session.socket.send(json.dumps({"type": "listen", "state": "start", "mode": args.mode}))
        receiver = asyncio.create_task(receive_events(session, observation))
        encoder = Pcm16OpusEncoder()
        packets = 0
        for index, pcm in enumerate(utterances, start=1):
            print(f"[SEND] utterance {index}/{len(utterances)}")
            packets += await send_pcm(session, encoder, pcm)
            if index < len(utterances):
                print(f"[SEND] {args.silence_between:.1f}s silence")
                packets += await send_silence(session, encoder, args.silence_between)
                if index == 1 and args.wait_for_tts_before_next:
                    print(f"[SEND] waiting up to {args.wait_for_tts_before_next:.1f}s for TTS before utterance 2")
                    try:
                        await asyncio.wait_for(observation.tts_started.wait(), args.wait_for_tts_before_next)
                    except TimeoutError:
                        print("[SEND] TTS did not start; continuing without a barge-in target")
        for packet in encoder.flush():
            await session.send_opus(packet)
            packets += 1
        print(f"[SEND] sent {packets} correctly encoded Opus packets; observing before stop for {args.observe_before_stop:.1f}s")
        await asyncio.sleep(args.observe_before_stop)

        observation.stopped_at = time.perf_counter()
        await session.stop_listening()
        print("[SEND] listen/stop")
        try:
            await asyncio.wait_for(observation.tts_finished.wait(), timeout=args.observe_after_stop)
        except TimeoutError:
            print(f"[RESULT] no tts/stop within {args.observe_after_stop:.1f}s after listen/stop")

        pre_stt = [event for event in observation.text_events_before_stop if event.get("type") == "stt"]
        post_stt = [event for event in observation.text_events_after_stop if event.get("type") == "stt"]
        pre_tts_started = any(
            event.get("type") == "tts" and event.get("state") == "start"
            for event in observation.text_events_before_stop
        )
        print("[RESULT] " + json.dumps({
            "mode": args.mode,
            "pre_stop_stt_count": len(pre_stt),
            "post_stop_stt_count": len(post_stt),
            "pre_stop_audio_packets": observation.binary_before_stop,
            "post_stop_audio_packets": observation.binary_after_stop,
            "continuous_listener_supported": bool(pre_stt),
            "tts_started_before_stop": pre_tts_started,
        }, ensure_ascii=False))
    finally:
        if receiver is not None:
            receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
