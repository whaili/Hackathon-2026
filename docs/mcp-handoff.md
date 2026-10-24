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

## Remaining End-to-End Verification

1. Confirm the latest CI/CD workflow completed and the container is healthy.
2. Open `https://10.210.34.33:18081/` from a browser that can access it.
3. Create or join a room.
4. Click `开始灵矽识别测试` so the browser opens the Lingxi session. This is
   required before an MCP tool call can be authorized for that player.
5. In Lingxi, say or send: `查询游戏状态`.
6. Watch backend logs:

```bash
ssh jfcs1026 'docker logs -f dont-let-it-hear-game'
```

Expected requests include `POST /mcp` for initialization/tool discovery, then
`tools/call` for `game.get_state`. Test a supported action afterward, such as
`拿起钥匙`, and ensure the returned tool content and browser game state agree.

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
