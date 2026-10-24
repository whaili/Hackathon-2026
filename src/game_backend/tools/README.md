# 测试工具

这三个脚本绕开浏览器，直接跟灵矽语音链路和 MCP 端点打交道，用于在没有真实浏览器/麦克风的环境
（CI、服务器、自动化脚本）里验证端到端链路。完整背景和用法见上级 [README.md](../README.md) 的
"测试"一节，这里只列用法速查。

## 准备音频

```bash
pip install --user edge-tts   # 微软免费 TTS，不需要 API key
bash gen_audio.sh             # 生成 audio/query_state.pcm 和 audio/pick_key.pcm
```

`audio/` 目录和 `batch_results.tsv` 不提交到仓库（见 `.gitignore`），需要换测试短语时改
`gen_audio.sh` 里的文字重新生成即可。

## 单次端到端测试

按浏览器实际走的协议（创建房间 → WebSocket → `linx_start` → 推流 PCM → `linx_end`）回放一句话：

```bash
python3 e2e_test.py audio/query_state.pcm
```

默认打到 `https://10.210.34.33:18081`，换部署地址用 `GAME_BASE_URL` 环境变量覆盖。

验证持续 ASR 是否实际触发后端状态机（使用动作样本）：

```bash
GAME_BASE_URL=http://127.0.0.1:8082 \
  python3 e2e_test.py audio/solo_explore.pcm --continuous --mode solo
```

这会创建默认单人房，并验证“探索能源区”的 ASR 最终文本实际进入单人状态机。第一阶段必须先探索，
再说“选择最尖锐的脉冲”；这样避免单句固定口令直接通关。旧双人原型仍可用：

```bash
GAME_BASE_URL=http://127.0.0.1:8082 \
  python3 e2e_test.py audio/pick_key.pcm --continuous --mode duo
```

## 验证 `realtime` 持续监听

`realtime_probe.py` 直连灵矽并复用后端的 Opus 编码器。它会在音频传输结束后**先不发**
`listen/stop`，记录期间收到的事件；再发送 `stop` 继续记录。输出中的 `PRE_STOP` / `POST_STOP`
标签是判据：只有前者出现实际 `stt` 识别文本，才能说明该模式能用于持续监听，而不是一次一按的回合制输入。

```bash
cd <repo-root>
set -a; . deploy/.env; set +a
PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
  src/game_backend/tools/audio/query_state.pcm --mode realtime
```

同一开放监听会话能否按自然停顿切出多段 ASR，可传入两条音频。结果中应在 `PRE_STOP` 看见两条 `stt`：

```bash
PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
  src/game_backend/tools/audio/query_state.pcm \
  src/game_backend/tools/audio/pick_key.pcm --mode realtime
```

验证 AI 正在播报时能否被第二段玩家语音打断：

```bash
PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
  src/game_backend/tools/audio/query_state.pcm \
  src/game_backend/tools/audio/pick_key.pcm --mode realtime \
  --wait-for-tts-before-next 8
```

对照 `manual` 与 `auto`：

```bash
PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
  src/game_backend/tools/audio/query_state.pcm --mode manual
PYTHONPATH=src python3 -m game_backend.tools.realtime_probe \
  src/game_backend/tools/audio/query_state.pcm --mode auto
```

## 直接测 MCP 服务端（绕开灵矽）

用一个真实建立的会话 ID 直接调 `tools/call`，用来区分"是我们后端的问题"还是"是灵矽没真正发起调用"：

```bash
MCP_URL="https://<当前 Cloudflare Tunnel 域名>/mcp" python3 session_mcp_test.py
```

## 批量可靠性测试

跑 N 次交替测试，通过部署主机上 `POST /mcp` 日志行数的前后差值判定每次是不是真的触发了
`tools/call`（4 次 = 成功，3 次 = 卡在 `tools/list`），不依赖主观读回复文本：

```bash
bash batch_test.sh 20          # 默认连 jfcs1026 的 dont-let-it-hear-game 容器
bash batch_test.sh 20 <ssh主机> <容器名>   # 换了部署目标时用
```

结果写到 `batch_results.tsv`，终端也会打印汇总统计。
