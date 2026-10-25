"""Two real Chromium players, fake WAV microphones, real Lingxi ASR.

Run with --serve-local to test the current checkout without deploying it.
Uses paid/external Lingxi sessions. Requires playwright, edge-tts and ffmpeg.
The script never sends say/action messages or mocks getUserMedia/WebSocket.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright

try:
    from .pulse_microphones import PulseMicrophones
except ImportError:
    from pulse_microphones import PulseMicrophones


ROOT = Path(__file__).resolve().parents[3]


async def command(*args):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(process.communicate(), 60)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError(f"command timed out: {args[0]}")
    if process.returncode:
        raise RuntimeError(f"{args[0]} failed: {err.decode()[-1500:]}")
    return out


async def wait_until(check, description, timeout=40):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        await asyncio.sleep(.1)
    raise AssertionError(f"timed out: {description}")


class Player:
    def __init__(self, name, options, playwright):
        self.name, self.options, self.playwright = name, options, playwright
        self.browser = self.page = None
        self.received = []
        self.archived_messages = []
        self.sent_types = []
        self.binary_frames = 0
        self.errors = []

    def watch_socket(self, socket):
        if "/ws/" not in socket.url:
            return
        self.room = urlparse(socket.url).path.rsplit("/", 1)[-1]

        def sent(payload):
            if isinstance(payload, bytes):
                self.binary_frames += 1
            else:
                self.sent_types.append(json.loads(payload).get("type"))

        def received(payload):
            if isinstance(payload, str):
                message = json.loads(payload)
                if message.get("type") == "linx_tts_wav":
                    message = {"type": "linx_tts_wav", "audio": "[omitted]"}
                self.received.append(message)

        socket.on("framesent", sent)
        socket.on("framereceived", received)

    @property
    def state(self):
        return next((msg["state"] for msg in reversed(self.received) if "state" in msg), {})

    @property
    def briefing(self):
        return next((msg for msg in reversed(self.received) if msg.get("type") == "private_briefing"), None)

    async def launch(self, wav, room=None):
        args = ["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
        if not self.options.continuous:
            args += ["--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={wav}%noloop"]
        kwargs = {"headless": True, "args": args}
        if self.options.continuous:
            kwargs["env"] = {**os.environ, "PULSE_SERVER": self.options.pulse.server,
                             "PULSE_SOURCE": self.options.pulse.sink(self.name) + "_mic", "PULSE_SINK": "e2e_output"}
        if self.options.chromium:
            kwargs["executable_path"] = self.options.chromium
        self.browser = await self.playwright.chromium.launch(**kwargs)
        context = await self.browser.new_context(
            permissions=["microphone", "clipboard-read", "clipboard-write"],
            ignore_https_errors=self.options.insecure, viewport={"width": 1280, "height": 960},
        )
        self.page = await context.new_page()
        self.page.on("websocket", self.watch_socket)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        url = self.options.base_url + (f"?room={room}" if room else "")
        await self.page.goto(url)
        await self.page.locator("#player").fill(self.name)
        await self.page.locator("#join" if room else "#create").click()
        await self.page.locator("#lobby").wait_for(state="hidden")
        await wait_until(lambda: self.state, f"{self.name}: room connection")
        if room and self.state.get("phase") != "lobby":
            await self.page.locator("#privateClue").wait_for()

    async def listen(self):
        begin = len(self.received)
        if self.options.continuous:
            await self.page.locator("#microphone").wait_for()
            await self.page.wait_for_function("label => Array.from(document.querySelector('#microphone').options).some(o => o.textContent === label)", arg=self.options.pulse.label(self.name))
            await self.page.locator("#microphone").select_option(label=self.options.pulse.label(self.name))
        await self.page.locator("#listen").click()
        ready = await wait_until(
            lambda: next((m for m in self.received[begin:] if m.get("type") in {"linx_ready", "linx_error"}), None),
            f"{self.name}: Lingxi connection", self.options.timeout,
        )
        if ready["type"] == "linx_error":
            raise AssertionError(f"{self.name}: {ready['message']}")
        return ready["session_id"]

    async def close(self):
        if self.page and not self.page.is_closed():
            # Stop through the real UI to clean up the upstream session.
            if await self.page.locator("#listen").evaluate("e => e.classList.contains('live')"):
                await self.page.locator("#listen").click()
        if self.browser:
            await self.browser.close()
        self.browser = self.page = None


async def synthesize(text, directory):
    mp3 = directory / f"{text}.mp3"
    wav = directory / f"{text}.wav"
    await command(sys.executable, "-m", "edge_tts", "--voice", "zh-CN-XiaoxiaoNeural",
                  "--text", text, "--write-media", str(mp3))
    # Warmup silence lets the browser open its real upstream connection first.
    await command("ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                  "-af", "adelay=8000:all=1,apad=pad_dur=8", "-ar", "48000", "-ac", "1", str(wav))
    return wav


async def run(options, report):
    directory = options.output.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    silence = directory / "silence.wav"
    with wave.open(str(silence), "wb") as output:
        output.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        output.writeframes(b"\0\0" * 48000 * 2)
    if options.continuous:
        options.pulse = PulseMicrophones(directory)
        await options.pulse.start(("alice-voice", "bob-voice"))
    async with async_playwright() as playwright:
        alice, bob = [Player(name, options, playwright) for name in ("alice-voice", "bob-voice")]
        players = (alice, bob)
        try:
            await alice.launch(silence)
            room = alice.room
            # Exercise the actual invitation control and use its clipboard URL.
            await alice.page.get_by_role("button", name="复制同伴邀请链接").click()
            invite = await alice.page.evaluate("navigator.clipboard.readText()")
            assert parse_qs(urlparse(invite).query)["room"] == [room]
            report.update(room_id=room, invitation_verified=True)
            await bob.launch(silence, room)
            await alice.page.locator("#start").click()
            for player in players:
                await player.page.locator("#privateClue").wait_for()
                await wait_until(lambda: player.briefing, "private clues")
            assert alice.briefing["role"] != bob.briefing["role"]
            report["sessions"] = [await alice.listen(), await bob.listen()]
            assert len(set(report["sessions"])) == 2, "Lingxi reused one session for both players"

            for stage in range(3):
                target = re.search(r"安全符号是(.*?)。", bob.briefing["text"]).group(1)
                signals = re.search(re.escape(target) + r"对应(.*?)，也可以描述为(.*?)(?:；|。)", alice.briefing["text"]).groups()
                phrase = next(s for s in signals if not any(w in s for w in alice.state["forbidden_words"]))
                for actor, text, expected in ((bob, f"授权{target}", "authorization_granted"),
                                              (alice, f"校准{phrase}", "game_won" if stage == 2 else "stage_completed")):
                    wav = await synthesize(text, directory)
                    # Chromium selects its fake WAV at process launch. Rejoin
                    # with the same role for every new phrase; the peer stays
                    # connected and listening. No browser API is monkeypatched.
                    if not options.continuous:
                        await actor.close()
                        observer = alice if actor is bob else bob
                        await wait_until(lambda: actor.name not in observer.state.get("players", {}), "disconnect broadcast")
                        actor.archived_messages.extend(actor.received)
                        actor.received = []
                        await actor.launch(wav, room)
                    starts = {p.name: len(p.received) for p in players}
                    if options.continuous:
                        await options.pulse.play(actor.name, wav)
                    else:
                        session = await actor.listen()
                        report["sessions"].append(session)
                    for player in players:
                        await wait_until(
                            lambda p=player: any(m.get("event", {}).get("type") == expected for m in p.received[starts[p.name]:]),
                            f"{player.name}: {text} -> {expected}", options.timeout,
                        )
                    recognized = [m["event"]["text"] for m in actor.received[starts[actor.name]:]
                                  if m.get("type") == "linx_event" and m.get("event", {}).get("type") == "stt"]
                    if not recognized:
                        raise AssertionError("game progressed without observed real STT")
                    for player in players:
                        await wait_until(lambda p=player: p.briefing and p.briefing["stage"] == stage + (2 if actor is alice else 1), "updated private clues")
                    snapshots = [next(m["state"] for m in reversed(p.received[starts[p.name]:])
                                      if m.get("event", {}).get("type") == expected) for p in players]
                    assert snapshots[0] == snapshots[1], "public transition states diverged"
                    for player in players:
                        upstream_errors = [m["message"] for m in player.archived_messages + player.received if m.get("type") == "linx_error"]
                        assert not upstream_errors, upstream_errors
                    report["turns"].append({"player": actor.name, "text": text, "stt": recognized, "expected": expected})
                    await actor.page.screenshot(path=str(directory / f"stage-{stage + 1}-{actor.name}.png"))
                    print(f"PASS {actor.name}: {text} -> {expected}; STT={recognized}", flush=True)

            for player in players:
                assert player.state["phase"] == "won"
                await player.page.locator("#chapterEnding").wait_for()
                assert player.binary_frames > 0
                assert not set(player.sent_types) & {"say", "action", "siren_metrics"}
                assert not player.errors, player.errors
                if options.continuous:
                    assert sum(m.get("type") == "connected" for m in player.received) == 1
                    assert sum(m.get("type") == "linx_ready" for m in player.received) == 1
            report.update(ok=True, final_state=alice.state,
                          checks={"real_microphone_frames": True, "real_lingxi_stt": True,
                                  "no_text_action_injection": True, "both_pages_show_ending": True,
                                  "continuous_without_reconnect": options.continuous})
        finally:
            report["players"] = [{"name": p.name, "binary_frames": p.binary_frames,
                                  "sent_types": p.sent_types, "page_errors": p.errors,
                                  "messages": p.archived_messages + p.received} for p in players]
            for player in players:
                if player.page and not player.page.is_closed():
                    await player.page.screenshot(path=str(directory / f"final-{player.name}.png"))
            await asyncio.gather(*(p.close() for p in players), return_exceptions=True)
            if options.continuous:
                await options.pulse.close()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18084")
    parser.add_argument("--serve-local", action="store_true", help="start this checkout; loads only LINX_DEVICE_ID from deploy/.env")
    parser.add_argument("--chromium", help="installed Chromium executable (otherwise Playwright's installed browser)")
    parser.add_argument("--insecure", action="store_true", help="allow self-signed HTTPS in this test only")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--continuous", action="store_true", help="Linux PulseAudio virtual microphones; keep both sessions open for the whole game")
    parser.add_argument("--output", type=Path, default=Path("src/game_backend/tools/artifacts/browser-voice"))
    options = parser.parse_args()
    options.base_url = options.base_url.rstrip("/")
    options.output.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "turns": [], "base_url": options.base_url, "started_at": time.time()}
    server = None
    try:
        if options.serve_local:
            url = urlparse(options.base_url)
            if url.hostname not in {"127.0.0.1", "localhost"} or url.scheme != "http":
                raise ValueError("--serve-local requires an HTTP loopback base URL")
            env = dict(os.environ)
            if not env.get("LINX_DEVICE_IDS"):
                for line in (ROOT / "deploy/.env").read_text().splitlines():
                    if line.startswith("LINX_DEVICE_IDS="):
                        env["LINX_DEVICE_IDS"] = line.split("=", 1)[1].strip().strip("\"'")
            devices = [device.strip().upper() for device in env.get("LINX_DEVICE_IDS", "").split(",") if device.strip()]
            if len(set(devices)) < 2 or len(devices) != len(set(devices)):
                raise ValueError("two distinct pre-registered LINX_DEVICE_IDS required for concurrent voice E2E")
            if not env.get("LINX_DEVICE_ID"):
                for line in (ROOT / "deploy/.env").read_text().splitlines():
                    if line.startswith("LINX_DEVICE_ID="):
                        env["LINX_DEVICE_ID"] = line.split("=", 1)[1].strip().strip("\"'")
            if not env.get("LINX_DEVICE_ID"):
                raise ValueError("LINX_DEVICE_ID required")
            log = (options.output / "server.log").open("w")
            server = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "uvicorn", "game_backend.server:app", "--app-dir", str(ROOT / "src"),
                "--host", "127.0.0.1", "--port", str(url.port or 80), env=env, stdout=log, stderr=log,
            )
            import urllib.request
            for _ in range(50):
                if server.returncode is not None:
                    raise RuntimeError("local server exited; inspect server.log")
                try:
                    await asyncio.to_thread(urllib.request.urlopen, options.base_url + "/mcp", timeout=1)
                    break
                except OSError:
                    await asyncio.sleep(.1)
            else:
                raise RuntimeError("local server not ready")
        await run(options, report)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        print(report["error"], file=sys.stderr)
    finally:
        if server:
            server.terminate()
            await asyncio.wait_for(server.wait(), 10)
        report["finished_at"] = time.time()
        (options.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"{'PASS' if report['ok'] else 'FAIL'}: {options.output / 'report.json'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
