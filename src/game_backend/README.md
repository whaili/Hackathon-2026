# 游戏后端

《别让它听见》的浏览器与游戏后端验证实现。

## 本地启动

```bash
python3 -m pip install -r src/game_backend/requirements.txt
python3 -m uvicorn game_backend.server:app --app-dir src --reload --port 8080
```

打开 <http://127.0.0.1:8080/>。页面可以创建房间、通过 WebSocket 同步状态，并提供音频回声与灵矽识别验证。

## 目录

- `server.py`：HTTP/WebSocket 房间服务和灵矽会话编排
- `linx_client.py`：OTA、灵矽 WebSocket 认证与协议客户端
- `audio_codec.py`：PCM16、裸 Opus、WAV 的编解码边界
- `static/`：浏览器页面和 AudioWorklet

## 容器部署

```bash
cp deploy/.env.example deploy/.env
# 在 deploy/.env 中设置 LINX_DEVICE_ID
docker compose -f deploy/compose.yaml up -d --build
```

浏览器客户端不持有灵矽 token；服务端通过 `LINX_DEVICE_ID` 完成 OTA，获取短期会话 token。
