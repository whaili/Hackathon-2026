"""Audio format adapter used at the Lingxi boundary.

The browser-side capture path should provide signed little-endian PCM16 at
16 kHz mono. Lingxi receives the resulting independent Opus packets.
"""

from __future__ import annotations

import io
import wave

import opuslib


SAMPLE_RATE = 16_000
CHANNELS = 1
FRAME_SAMPLES = 960  # 60 ms, matching the validated Lingxi session settings.


class Pcm16OpusEncoder:
    def __init__(self) -> None:
        self.encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_VOIP)
        self.pending = bytearray()

    def feed(self, pcm16: bytes) -> list[bytes]:
        if len(pcm16) % 2:
            pcm16 = pcm16[:-1]
        self.pending.extend(pcm16)
        frame_bytes = FRAME_SAMPLES * 2
        packets: list[bytes] = []
        while len(self.pending) >= frame_bytes:
            frame = bytes(self.pending[:frame_bytes])
            del self.pending[:frame_bytes]
            packets.append(self.encoder.encode(frame, FRAME_SAMPLES))
        return packets

    def flush(self) -> list[bytes]:
        if not self.pending:
            return []
        frame_bytes = FRAME_SAMPLES * 2
        frame = bytes(self.pending).ljust(frame_bytes, b"\0")
        self.pending.clear()
        return [self.encoder.encode(frame, FRAME_SAMPLES)]


class OpusPcm16Decoder:
    """Decode Lingxi 16 kHz mono Opus packets into a browser-playable WAV."""

    def __init__(self) -> None:
        self.decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)

    def wav(self, packets: list[bytes]) -> bytes:
        pcm = bytearray()
        for packet in packets:
            # The upstream uses 60 ms frames; allow packet loss concealment size.
            pcm.extend(self.decoder.decode(packet, FRAME_SAMPLES, False))
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(pcm)
        return buffer.getvalue()
