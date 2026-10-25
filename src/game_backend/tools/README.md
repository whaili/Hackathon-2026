# 测试工具

这些脚本绕开浏览器，直接跟游戏后端、灵矽语音链路和 MCP 端点打交道，用于在没有真实浏览器/麦克风的环境
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

## 双人文字端到端回归

`multiplayer_text_e2e.py` 使用两条独立 WebSocket 连接模拟 Alice 和 Bob，并通过 `say` 消息
发送文字。它走真实的创建房间、加入房间、启动游戏、广播状态和结算路径，不依赖浏览器、麦克风或
灵矽额度。

```bash
GAME_BASE_URL=http://127.0.0.1:8080 \
  python3 multiplayer_text_e2e.py --json
```

部署环境也可以直接测：

```bash
GAME_BASE_URL=https://10.210.34.33:18081 \
  python3 multiplayer_text_e2e.py --json
```

脚本的程序断言包括：两个客户端每一步收到相同公共状态、两名玩家收到不同私有线索、根据当局线索完成三次授权和校准、最终事件为
`game_won`。输出 JSON 中的 `event_types`、`final_state` 和 `action_history` 可以交给 AI
评审器，评价协作是否自然、信息差是否有意义、是否出现重复操作或异常事件。AI 评审只负责体验
层面的判断，状态转换、胜负和一致性必须由脚本断言。

当前玩家是确定性线索解析器；runner 为验证规则会组合两方信息，并不证明 AI 能自主协作或体验有趣。
脚本不会调用灵矽或外部模型。自主 AI 玩家与自动 AI 评审尚未接入；真实浏览器语音测试见下一节。

## 双人真实浏览器语音全链路测试

`browser_voice_e2e.py` 用两个独立 Chromium 进程扮演玩家，通过页面按钮建房、邀请、加入、启动和开启监听。
测试文字由 Edge TTS 合成为 WAV，输入 Chromium 原生虚拟麦克风；页面仍调用真实 `getUserMedia`、AudioWorklet，
后端仍编码 Opus 并连接真实灵矽。测试不会 mock 浏览器 API，也不会发送 `say` 或 `action` 来推进游戏。

安装测试依赖（需系统安装 `ffmpeg`）：

```bash
python3 -m pip install -r src/game_backend/tools/requirements-test.txt
python3 -m playwright install chromium
```

以下命令从仓库根目录执行。两个设备必须已经在灵矽平台注册并绑定相同的游戏智能体；
`LINX_DEVICE_IDS` 是逗号分隔的设备池，每个活跃连接独占一个设备。不要把同一个设备写两次。

```bash
LINX_DEVICE_IDS='<设备 A 的 MAC>,<设备 B 的 MAC>' \
  python3 src/game_backend/tools/browser_voice_e2e.py --serve-local
```

`--serve-local` 启动当前工作区代码的临时服务，默认地址为 `http://127.0.0.1:18084`；
如果环境变量没有设置，则从本地 `deploy/.env` 读取设备配置。测试结束会停止临时服务。
localhost 是浏览器安全上下文，可以使用麦克风，无需临时部署线上版本。

验证已部署的新版本：先在服务端配置设备池并重启，再执行：

```bash
python3 src/game_backend/tools/browser_voice_e2e.py \
  --base-url https://10.210.34.33:18081 --insecure
```

已有 Chromium 时可使用 `--chromium /absolute/path/to/chrome`。`--insecure` 仅为开发环境自签名证书使用。
默认每步超时 45 秒，可通过 `--timeout` 调整。该测试使用真实灵矽会话和外部 TTS 服务，会产生额度消耗并依赖网络。

测试检查实际麦克风二进制帧、两个独立灵矽会话、真实 STT 文本、三阶段推进、双方公共状态一致和页面结局。
同一 MAC 并发会触发平台的 `device replaced by new connection`，单设备配置不满足双人验收。
测试也会拒绝出现 `linx_error` 或前端脚本错误的对局，失败退出码为 1，不把收到握手当作通关。

产物默认写入 `tools/artifacts/browser-voice/`（已忽略提交）：

- `report.json`：逐轮台词、实际 STT、游戏结果、音频帧数及浏览器消息记录。
- `stage-*.png`、`final-*.png`：实际页面截图。
- WAV/MP3：可复现的合成音频；`server.log`：本地服务日志。

Chromium 在启动时选择虚拟麦克风文件，因此当前 runner 每换一句台词会重启该玩家浏览器，
用原代号重新加入房间并建立监听；另一名玩家保持连接。这验证真实语音输入和角色恢复，
不代表已验证整局无重连持续监听、自然抢话、真实扬声器回声或真人趣味性。
动作由确定性线索解析器选择，尚未使用自主 AI 玩家。

### 整局持续会话模式（Linux）

安装 `pulseaudio`、`pulseaudio-utils` 后，给上述命令增加 `--continuous`：

```bash
LINX_DEVICE_IDS='<设备 A>,<设备 B>' \
python3 src/game_backend/tools/browser_voice_e2e.py --serve-local --continuous
```

该模式启动一个私有临时 PulseAudio 实例，为两位玩家各建立独立的虚拟麦克风，通过页面的“麦克风”选择器选中它们。
合成 WAV 经系统音频设备实时播放给浏览器，保持真实 `getUserMedia`、AudioWorklet、WebSocket 和灵矽连接。
整局不重启浏览器、不更换麦克风流、不停止监听，并断言每人只出现一次 `connected` 和一次 `linx_ready`。
不使用 Chromium 假设备、浏览器 API 覆盖或文字动作注入。两名玩家的扬声器输出与麦克风隔离，因此仍不覆盖真实声学回声。
测试结束自动停止私有 PulseAudio 实例，不修改现有系统音频服务。故障日志保存在 `pulse.log`。

## 新功能的测试约定

以后新增一个游戏模式、动作或多人规则时，按下面顺序补测试：

1. 在 `tests/test_game_engine.py` 增加确定性状态机测试，覆盖成功、错误输入和失败条件。
2. 在 `tests/test_server.py` 增加 WebSocket 或 HTTP 协议测试，确认真实消息格式和广播行为。
3. 如果功能涉及多人协作，扩展 `multiplayer_text_e2e.py` 的剧本，让两个客户端分别执行角色动作，
   并为每一步增加预期事件或最终状态断言。
4. 运行单元测试和文字端到端脚本；最后再用音频回放脚本验证 ASR/灵矽适配层。这样可以把状态机
   bug、协议 bug 和语音识别问题分别定位。

推荐的验证命令：

```bash
PYTHONPATH=src python3 -m unittest discover -s src/game_backend/tests -v
GAME_BASE_URL=https://10.210.34.33:18081 \
  python3 multiplayer_text_e2e.py --json
```
