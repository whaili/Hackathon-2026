#!/bin/bash
# Generates the 16kHz mono PCM16 test audio files used by e2e_test.py and
# batch_test.sh, via edge-tts (Microsoft's free TTS, no API key needed) and
# ffmpeg. Output is not committed to the repo -- regenerate locally.
set -eu
cd "$(dirname "$0")"
mkdir -p audio

gen() {
  local phrase="$1" name="$2"
  edge-tts --voice zh-CN-XiaoxiaoNeural --text "$phrase" --write-media "audio/${name}.mp3"
  ffmpeg -y -loglevel error -i "audio/${name}.mp3" -ar 16000 -ac 1 -f s16le "audio/${name}.pcm"
  rm "audio/${name}.mp3"
  echo "audio/${name}.pcm  <-  \"${phrase}\""
}

gen "查询游戏状态" query_state
gen "拿起钥匙" pick_key
