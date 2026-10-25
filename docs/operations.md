# 运维与发布

## 本地

```bash
python3 -m pip install -r src/game_backend/requirements.txt
PYTHONPATH=src python3 -m uvicorn game_backend.server:app --app-dir src --reload --port 8080
PYTHONPATH=src python3 -m unittest discover -s src/game_backend/tests -v
```

## 发布

所有变更走功能分支和 PR，合并到 `main` 后由 `.github/workflows/ci-cd.yml` 在自托管 runner 构建、测试并部署 Docker Compose。部署健康检查使用宿主机 `127.0.0.1:18080`；浏览器入口由 Nginx 提供 HTTPS。

```bash
gh run list --repo whaili/Hackathon-2026 --limit 5
ssh jfcs1026 'docker ps --filter name=dont-let-it-hear-game'
ssh jfcs1026 'docker logs --tail 200 dont-let-it-hear-game'
```

## 配置

- `LINX_DEVICE_ID`：单人灵矽会话使用的预注册设备。
- `LINX_DEVICE_IDS`：双人并发会话使用的逗号分隔设备池，不能复用同一 MAC。
- `deploy/.env`：只存在于部署环境，不提交仓库。

灵矽 MCP 服务需要公网可访问的 `/mcp` 地址；当前 Quick Tunnel 仅适合临时演示，正式环境应使用稳定域名和受信任证书。详细控制台配置、MCP 契约和排障见[后端技术手册](../src/game_backend/README.md)。

## 验证顺序

1. 单元和协议测试。
2. 双人文字 E2E，确认私有线索和状态机。
3. 真实浏览器语音 E2E，确认麦克风、灵矽 ASR、双设备会话和页面结局。

测试工具的完整命令见 [`src/game_backend/tools/README.md`](../src/game_backend/tools/README.md)。
