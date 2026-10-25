"""Private, process-owned Linux virtual microphones for persistent browsers."""

import asyncio
import os
import tempfile
from pathlib import Path


class PulseMicrophones:
    def __init__(self, directory):
        self.runtime = tempfile.TemporaryDirectory(prefix="duo-pulse-")
        self.socket = str(Path(self.runtime.name) / "socket")
        self.server = "unix:" + self.socket
        self.env = {**os.environ, "PULSE_SERVER": self.server,
                    "PULSE_RUNTIME_PATH": self.runtime.name, "PULSE_STATE_PATH": self.runtime.name}
        self.log = (directory / "pulse.log").open("w")
        self.process = None

    @staticmethod
    def sink(player):
        return "e2e_" + player.replace("-", "_")

    @staticmethod
    def label(player):
        return "DuoE2E_" + player.replace("-", "_")

    async def run(self, *args):
        process = await asyncio.create_subprocess_exec(*args, env=self.env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(process.communicate(), 60)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise RuntimeError(f"{args[0]} timed out")
        if process.returncode:
            raise RuntimeError(err.decode()[-1000:])
        return out

    async def start(self, players):
        args = ["pulseaudio", "-n", "--daemonize=no", "--use-pid-file=no", "--exit-idle-time=-1",
                "--disable-shm=yes", "--log-level=warning", "-L",
                f"module-native-protocol-unix socket={self.socket} auth-anonymous=1",
                "-L", "module-null-sink sink_name=e2e_output rate=48000 channels=1"]
        for player in players:
            sink = self.sink(player)
            args += ["-L", f"module-null-sink sink_name={sink} rate=48000 channels=1",
                     "-L", f"module-remap-source master={sink}.monitor source_name={sink}_mic source_properties=device.description={self.label(player)}"]
        self.process = await asyncio.create_subprocess_exec(*args, env=self.env, stdout=self.log, stderr=self.log)
        for _ in range(50):
            if self.process.returncode is not None:
                raise RuntimeError("isolated PulseAudio failed; inspect pulse.log")
            if Path(self.socket).exists():
                await self.run("pactl", "set-default-sink", "e2e_output")
                return
            await asyncio.sleep(.1)
        raise RuntimeError("PulseAudio did not start")

    async def play(self, player, wav):
        await self.run("paplay", f"--device={self.sink(player)}", str(wav))

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), 10)
        self.log.close()
        self.runtime.cleanup()
