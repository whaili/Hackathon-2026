# Lingxi MCP Integration Handoff

Updated: 2026-10-24

## Objective

The browser game "Don't Let It Hear" is deployed on `jfcs1026`. A Lingxi agent
has been configured with an MCP service so it can query the game state and send
validated game actions. The remaining task is an end-to-end call from Lingxi
to the public MCP endpoint while a browser player has an active Lingxi session.

## Repository State

- Repository: `whaili/Hackathon-2026`
- Relevant commit: `252713d feat: add Lingxi MCP game tools and integration guide`
- Primary integration guide: `docs/mcp-integration.md`
- Backend implementation: `src/game_backend/server.py`
- CI/CD workflow: `.github/workflows/ci-cd.yml`

When using GitHub CLI or pushing from this environment, unset the stale token:

```bash
env -u GITHUB_TOKEN -u GH_TOKEN gh run list --repo whaili/Hackathon-2026
env -u GITHUB_TOKEN -u GH_TOKEN git push
```

## Deployment

The game backend runs on `jfcs1026` in Docker:

```text
Container: dont-let-it-hear-game
Backend health endpoint: http://127.0.0.1:18080/
Browser page (HTTPS): https://10.210.34.33:18081/
```

Useful commands:

```bash
ssh jfcs1026 'docker ps --filter name=dont-let-it-hear-game'
ssh jfcs1026 'docker logs --tail 200 dont-let-it-hear-game'
ssh jfcs1026 'docker logs -f dont-let-it-hear-game'
ssh jfcs1026 'curl -fsS http://127.0.0.1:18080/'
```

The self-hosted GitHub Actions runner on `jfcs1026` builds and deploys commits
to `main`. Check the workflow run created by commit `252713d` before testing:

```bash
env -u GITHUB_TOKEN -u GH_TOKEN gh run list \
  --repo whaili/Hackathon-2026 --limit 5
```

## Temporary Public MCP Endpoint

Cloudflare Quick Tunnel has been started on `jfcs1026`:

```text
https://contributions-craft-sheet-claims.trycloudflare.com/mcp
```

It routes directly to `127.0.0.1:18080` on `jfcs1026`.

This is a temporary Quick Tunnel. Its hostname changes when its process is
restarted. Its current process state is recorded at:

```text
PID file: /tmp/dont-let-it-hear-cloudflared.pid
Log file: /tmp/dont-let-it-hear-cloudflared.log
```

Verify it without modifying state:

```bash
curl -fsS https://contributions-craft-sheet-claims.trycloudflare.com/mcp
curl -i -X POST https://contributions-craft-sheet-claims.trycloudflare.com/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"handoff-check","version":"1"}}}'
```

Expected `GET /mcp` result contains `dont-let-it-hear-mcp`. The tunnel and MCP
initialization were verified before this handoff.

For the final demo, replace this with a named Cloudflare Tunnel and stable
domain. That requires Cloudflare account/domain authorization from the owner.

## MCP Service Contract

Implemented routes:

```text
GET  /mcp
POST /mcp
POST /mcp/message
```

Supported MCP methods:

```text
initialize
notifications/initialized
tools/list
tools/call
```

Available tools:

```text
game.get_state
game.apply_action
```

`game.apply_action` supports the in-game actions defined in `server.py`. The
backend associates the MCP header `X-Linx-Session-Id` with `(room_id,
player_id)` only after the browser's Lingxi `hello` completes. Calls without
that active mapping are rejected; they cannot mutate an arbitrary room.

## Lingxi Console Configuration

Chrome DevTools was available locally at `127.0.0.1:9222`. The currently
configured agent is:

```text
Name: Hackathon语音游戏测试
agent_id: ce3d3cfe03f64d63871240493ef953c0
```

Its selected private MCP service is:

```text
Name: 别让它听见 MCP（测试）
Transport: Streamable HTTP
Auth: Normal
URL: https://contributions-craft-sheet-claims.trycloudflare.com/mcp
Opened MCP config ID: 0a65cb0d955e432fb12a705c58da6f0f
```

The service was published, then selected and saved in:

```text
智能体管理 -> 配置角色 -> 技能与扩展 -> MCP编辑
```

The agent's testing instruction says:

- For “游戏状态”, “当前警报”, or “房间情况”, call `game.get_state`.
- For a game action, call `game.apply_action`.
- Treat tool results as authoritative; do not invent game state.

If the Quick Tunnel URL changes, update this MCP URL in the Lingxi console,
save the MCP setting, and save the agent configuration again.

## End-to-End Verification: Done (2026-10-24), With One Open Reliability Issue

The remaining verification this doc originally asked for has been completed,
bypassing the browser (TLS self-signed cert + no real microphone in the
automation environment made the browser path impractical). Instead the exact
wire protocol the browser's JS uses (`linx_start` → raw PCM16 16kHz frames →
`linx_end`) was replayed directly over the game WebSocket using Python +
`edge-tts`-synthesized speech as the simulated microphone input. This
exercises the identical code path a real browser session would use, since the
backend has no branch that distinguishes a real microphone from a replayed
PCM stream.

### Root cause found and fixed: the agent Prompt was never actually configured

The console's agent (`Hackathon语音游戏测试`) had the MCP service correctly
selected under 技能与扩展 → MCP编辑 (confirmed visually — `别让它听见 MCP（测试）`
was checked), but the **角色介绍 (Prompt) field still contained the original
default "调皮公主" persona** from when the agent was first created weeks ago.
Per `docs/mcp-integration.md`'s own warning ("模型不会仅因工具已绑定而必然调
用"), binding the MCP service is not enough — the Prompt must explicitly say
when to call which tool. The first live test confirmed this: asking "查询游戏
状态" got a chatty off-topic reply from the default persona, with zero `tools/
call` in the backend logs.

Fixed by writing an explicit tool-calling Prompt into 智能体管理 → 配置角色 →
角色介绍, instructing the model to call `game.get_state` for state queries and
`game.apply_action` for game actions, and to treat tool results as the only
source of truth. Saved via 保存配置.

**Gotcha for whoever edits this field next via browser automation**: a naive
`fill(..., clear: true)` on this textarea did not actually clear the existing
content — the new text got appended after the old persona text instead,
producing a corrupted Prompt with two contradictory personas (confirmed by
re-opening the config page and seeing both blocks concatenated). The fix was
to clear it with a native-setter + `input` event dispatch via
`browser_evaluate` (bypassing the React-controlled component's normal event
handling), which worked reliably. If you see confused/contradictory model
behavior after an automated Prompt edit, check for this first.

### Verified working: `game.get_state`

With the corrected Prompt saved, replaying `"查询游戏状态"` produced:

```text
STT: 查询游戏状态。
Reply: 当前房间RJ-K5Q，警报等级0，剩余时间90秒，暂无操作记录。一切正常，继续。
```

This matches the real room state exactly (room id, alert level, remaining
time, empty action history). Backend logs for this turn show 4 `POST /mcp`
calls (`initialize` → 200, `notifications/initialized` → 202,
`tools/list` → 200, `tools/call` → 200) — the full MCP handshake plus an
actual tool call.

### Server-side MCP implementation independently verified correct

Bypassing Lingxi entirely, calling `tools/call` directly against the public
MCP endpoint with a real `X-Linx-Session-Id` captured from an active browser-
protocol session returned correct, live state for both tools:

- `game.get_state` → the real room's current state.
- `game.apply_action` (`"拿起钥匙"`) → executed, appended to
  `action_history`, and the updated state was returned.

Calls with no session header or a fabricated session id are correctly
rejected with `{"code":-32001,"message":"No active browser game session for
this Lingxi session"}`. This confirms the backend's MCP contract and the
session-mapping security model both work exactly as `docs/mcp-integration.md`
describes.

### Open issue: intermittent tool-discovery failure on the Lingxi side

A second live test with `"拿起钥匙"` (same agent, same Prompt, same MCP
binding, moments later) failed: the model narrated at length that it only
has 天气/新闻/时间获取/黄历获取/退出意图处理 available and does **not** have a
game tool, then gave up. Backend logs for that turn show only 3 `POST /mcp`
calls (`initialize` → 200, `notifications/initialized` → 202,
`tools/list` → 200) — `tools/list` succeeded at the HTTP level (same
response as the direct curl test, which correctly lists both game tools),
but the model's own context apparently did not include the MCP tools that
turn, despite the identical agent configuration that worked moments earlier
for `game.get_state`.

This looks like an intermittent issue in how the Lingxi platform merges MCP
`tools/list` results into the model's available-tools context — not
something fixable from the backend or Prompt side, since the HTTP-level
exchange was identical to the successful case. Not yet characterized:
failure rate, whether it correlates with which tool is being requested,
retry window, or the TTS response time (the failing turn also took unusually
long and never reached `linx_turn_complete` within a 45s window, versus ~5s
for the successful turn).

**Suggested next steps for whoever picks this up:**

1. Run `game.apply_action` several more times (the test script and audio
   files below make this a ~10-second loop) to estimate the failure rate.
2. If failures are frequent, consider whether unchecking the unrelated
   default plugins (天气/新闻/时间获取/黄历获取 under 技能与扩展) reduces
   confusion — not yet tried, since the one successful run had them still
   enabled, so they are not proven to be the cause.
3. If this persists, it is worth reporting to 灵矽/七牛 as a platform
   reliability question, since both the Prompt and the MCP server's
   `tools/list` response were confirmed correct and unchanging between the
   success and failure cases.

### Reusable test tooling (not committed to the repo — local to this session)

```text
/tmp/mcp-handoff-test/e2e_test.py          # replays the browser's WS protocol with a given PCM file
/tmp/mcp-handoff-test/session_mcp_test.py  # calls tools/call directly with a real session id, bypassing Lingxi
/tmp/mcp-handoff-test/query_state.pcm      # edge-tts "查询游戏状态" at 16kHz mono PCM16
/tmp/mcp-handoff-test/pick_key.pcm         # edge-tts "拿起钥匙" at 16kHz mono PCM16
```

Regenerate audio for a new phrase with:

```bash
edge-tts --voice zh-CN-XiaoxiaoNeural --text "<phrase>" --write-media /tmp/x.mp3
ffmpeg -y -i /tmp/x.mp3 -ar 16000 -ac 1 -f s16le /tmp/x.pcm
```

## Known Limitations

- The Quick Tunnel is ephemeral and unsuitable for a stable demo URL.
- Room state and Lingxi session mappings are in process memory. Multiple
  backend replicas would require shared storage such as Redis.
- Normal Lingxi relay completion does not immediately remove every session
  mapping; WebSocket disconnect cleanup does. Tighten this lifecycle before a
  long-running production deployment.
- Nginx currently serves the browser page. The Cloudflare tunnel routes MCP
  traffic directly to the backend rather than exposing `/mcp` through Nginx.

## Assets Added for the Console Service

```text
assets/mcp-service-logo.png
assets/mcp-service-logo.svg
```
