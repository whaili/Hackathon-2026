"""Compose a successful continuous browser test into a two-player demo MP4.

Video is actual Playwright browser recording. Audio is the synthetic microphone
input, aligned using the test's playback timestamps, not a speaker recording.
"""

import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if not report.get("ok") or not report.get("checks", {}).get("continuous_without_reconnect"):
        raise SystemExit("A successful continuous test recorded with --record-video is required")
    directory = args.report.resolve().parent
    output = args.output or directory / "duo-demo.mp4"
    command = ["ffmpeg", "-y", "-loglevel", "warning"]
    for player in report["players"]:
        files = list((directory / "videos" / player["name"]).glob("*.webm"))
        if len(files) != 1:
            raise SystemExit(f"Expected one browser recording for {player['name']}; use a fresh --output directory")
        command += ["-i", str(files[0])]
    filters = []
    for index, player in enumerate(report["players"]):
        offset = max(0, player.get("video_offset") or 0)
        role = "FIELD OPERATOR" if index == 0 else "MONITOR"
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS,scale=960:720,tpad=start_duration={offset:.3f}:color=black,"
                       f"drawtext=text='{role} | REAL BROWSER':x=16:y=16:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.7[v{index}]")
    filters.append("[v0][v1]hstack=inputs=2:shortest=1[video]")
    for index, turn in enumerate(report["turns"]):
        if turn.get("audio_offset") is None:
            raise SystemExit("Missing microphone playback timestamp")
        command += ["-i", turn["wav"]]
        delay = max(0, round(turn["audio_offset"] * 1000))
        filters.append(f"[{index + 2}:a]adelay={delay}:all=1[a{index}]")
    audio_inputs = "".join(f"[a{i}]" for i in range(len(report["turns"])))
    filters.append(f"{audio_inputs}amix=inputs={len(report['turns'])}:normalize=0[audio]")
    command += ["-filter_complex", ";".join(filters), "-map", "[video]", "-map", "[audio]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "25", "-threads", "2", "-r", "20",
                "-c:a", "aac", "-movflags", "+faststart", "-shortest", str(output)]
    subprocess.run(command, check=True)
    print(output)


if __name__ == "__main__":
    main()
