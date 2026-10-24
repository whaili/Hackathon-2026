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
