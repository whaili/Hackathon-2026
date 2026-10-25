# 系统架构

```mermaid
flowchart LR
  B[浏览器玩家] -->|HTTP / WebSocket| S[FastAPI 游戏后端]
  B -->|PCM16 麦克风帧| S
  S -->|OTA + Lingxi WebSocket| L[灵矽语音平台]
  L -->|ASR / TTS / 事件| S
  L -->|MCP tools/call| M[/mcp]
  M --> S
  S --> G[确定性游戏状态机]
  S --> B
  N[Nginx HTTPS] --> S
```

核心职责：

- 浏览器只采集麦克风、展示状态和播放反馈，不持有灵矽凭证。
- `server.py` 管理房间、WebSocket、灵矽会话和 MCP 会话绑定。
- `game_engine.py` / `duo_chapter.py` 将转写文本结算为确定性事件；状态机是胜负的唯一事实来源。
- `linx_client.py` 负责 OTA、设备池和灵矽 WebSocket；双人会话必须使用两个不同的预注册设备。
- `static/` 是浏览器页面和 AudioWorklet；`tools/` 保存协议、文字和真实浏览器回归工具。

安全边界：浏览器不接触 token；MCP 请求必须带有已登记的 `X-Linx-Session-Id`，否则不能操作房间。
房间和会话映射当前保存在单进程内存中，生产扩容前需要共享存储和身份认证。
