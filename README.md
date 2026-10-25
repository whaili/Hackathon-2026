# Hackathon-2026

七牛云第五届 1024 Hackathon 参赛项目：基于"灵矽"（Lingxi/Xrobot）语音 AI 平台做一款持续监听的语音协作游戏《别让它听见》。

当前 `main` 已有可部署试玩版本：浏览器麦克风经灵矽 ASR 驱动确定性游戏状态机。产品主线已收敛为面向异地朋友和情侣的双人语音密室；单人挑战和海妖安抚保留为引擎实验能力，后续开发以一条 10–15 分钟双人章节为中心。

## 开发者快速入口

**开发、部署、灵矽控制台配置和端到端测试，请直接阅读
[游戏后端技术手册](src/game_backend/README.md)。** 这是这些操作的唯一详细说明和命令来源。

最短工作路径：

1. 按手册的“本地开发”安装依赖，设置 `LINX_DEVICE_ID`，启动本地服务。
2. 执行 `PYTHONPATH=src python3 -m unittest discover -s src/game_backend/tests -v` 验证状态机和 WebSocket 逻辑。
3. 修改在功能分支完成，提交 PR 并合并到 `main`；GitHub Actions 会自动构建并部署。
4. 按手册的“人工浏览器端到端测试”、 “双人文字端到端回归”和“脚本化端到端测试”验证多人状态机、真实 HTTPS 麦克风链路与灵矽 ASR。

当前演示入口为 <https://10.210.34.33:18081/>。该地址使用自签名证书，首次访问需要在浏览器中手动继续访问；正式演示前仍应替换为受信任的稳定 HTTPS 域名。

最终演示视频集中在 [demos/README.md](demos/README.md)：[单人](demo.mp4) 和 [双人](demos/duo.mp4)。

新增功能先跑文字回归，再按 [双人真实浏览器语音测试](src/game_backend/tools/README.md#双人真实浏览器语音全链路测试)
验证麦克风、灵矽 ASR 与页面结局；双人并发需配置两个不同预注册设备的 `LINX_DEVICE_IDS`。

## 文档导航

接手此项目的人或 Code Agent，建议按顺序阅读：

1. [docs/README.md](docs/README.md) — 文档总入口
2. [docs/project-overview.md](docs/project-overview.md) — 产品定位、交付要求和当前状态
3. [docs/game-design.md](docs/game-design.md) — 游戏规则和双人章节设计
4. [docs/architecture.md](docs/architecture.md) — 技术架构与安全边界
5. [docs/operations.md](docs/operations.md) — 本地运行、发布、配置和排障
6. [src/game_backend/README.md](src/game_backend/README.md) — 后端接口和测试工具详细手册
7. [docs/demo-walkthrough.md](docs/demo-walkthrough.md) — 演示顺序、自动录制和验证边界

早期候选方案和选型记录已归档到 [docs/archive/](docs/archive/)。

方向、调研结论或约束发生变化时，请持续更新对应文档，保持同步。
