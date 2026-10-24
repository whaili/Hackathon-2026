# 灵矽 MCP 接入

`src/game_backend/server.py` 同时提供浏览器游戏服务和 MCP 服务。MCP 让灵矽智能体调用受控游戏状态机；它不承担浏览器音频转发。

## 服务端点

- `GET /mcp`：部署与 Tunnel 健康检查
- `POST /mcp`：Streamable HTTP MCP JSON-RPC
- `POST /mcp/message`：兼容旧版 SSE 文档的 JSON-RPC 入口

首版工具：

- `game.get_state`：读取当前灵矽会话绑定房间的状态
- `game.apply_action`：执行一个经过后端校验的动作，并同步所有浏览器玩家

灵矽调用 MCP 时会携带 `X-Linx-Session-Id`。浏览器玩家连接灵矽后，后端将该 ID 映射到 `room_id` 和 `player_id`；无活动映射的调用会被拒绝，不能直接操作任意房间。

## 灵矽控制台配置

在 MCP 的“自定义 MCP”中创建服务，传输协议选择 `Streamable HTTP`，MCP URL 为公开 HTTPS 地址加 `/mcp`。随后：

1. 发布服务。
2. 在“已开通 MCP”开通服务。
3. 在“智能体管理 → 配置角色 → 技能与扩展 → MCP 编辑”中勾选服务并保存。
4. 在角色 Prompt 中明确列出何时调用工具；模型不会仅因工具已绑定而必然调用。

## 开发与测试

灵矽云端必须能访问 MCP URL。局域网地址和自签名证书不能用于云端回调。

短期验证可用 Cloudflare Quick Tunnel：

```bash
cloudflared tunnel --url http://127.0.0.1:18080 --no-autoupdate
```

将输出的 `https://<random>.trycloudflare.com/mcp` 配入控制台。Quick Tunnel 重启后 URL 会变，不可用于稳定 Demo。正式测试环境应使用 Cloudflare Named Tunnel + 自有域名，或将 MCP 部署到受信任 HTTPS 的云环境。

端到端验证顺序：

1. 打开游戏 HTTPS 页面，创建并加入房间。
2. 点击“开始灵矽识别测试”，说“查询游戏状态”，再停止录音。
3. 后端建立浏览器与灵矽 session 映射；智能体应调用 `game.get_state`。
4. 用“拿起钥匙”等游戏动作验证 `game.apply_action` 和浏览器状态同步。

## 团队协作

- `main` 推送会通过自托管 GitHub Actions Runner 执行构建并部署到测试环境。
- 本地开发优先调用 `/mcp` 的 JSON-RPC `initialize`、`tools/list`、`tools/call`，不消耗灵矽额度。
- 真实灵矽测试只使用开发智能体与预注册开发设备，避免影响正式智能体。
- 不要把灵矽设备 ID、Cloudflare 凭证或控制台 token 写入仓库；使用 `deploy/.env` 和 GitHub Actions Secret。
