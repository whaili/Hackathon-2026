# Hackathon-2026

七牛云第五届 1024 Hackathon 参赛项目：基于"灵矽"（Lingxi/Xrobot）语音 AI 平台做一款持续监听的语音协作游戏《别让它听见》。

当前 `main` 已有可部署试玩版本：浏览器麦克风持续采集语音，后端转发到灵矽做 ASR，并用确定性游戏状态机结算禁语、警报、倒计时和任务进度。

## 开发者快速入口

**开发、部署、灵矽控制台配置和端到端测试，请直接阅读
[游戏后端技术手册](src/game_backend/README.md)。** 这是这些操作的唯一详细说明和命令来源。

最短工作路径：

1. 按手册的“本地开发”安装依赖，设置 `LINX_DEVICE_ID`，启动本地服务。
2. 执行 `PYTHONPATH=src python3 -m unittest discover -s src/game_backend/tests -v` 验证状态机和 WebSocket 逻辑。
3. 修改在功能分支完成，提交 PR 并合并到 `main`；GitHub Actions 会自动构建并部署。
4. 按手册的“人工浏览器端到端测试”和“脚本化端到端测试”验证真实 HTTPS 麦克风链路、灵矽 ASR 与状态机。

当前演示入口为 <https://10.210.34.33:18081/>。该地址使用自签名证书，首次访问需要在浏览器中手动继续访问；正式演示前仍应替换为受信任的稳定 HTTPS 域名。

## 文档导航

接手此项目的人或 Code Agent，建议按顺序阅读：

1. [docs/project-overview.md](docs/project-overview.md) — 项目介绍：活动信息、硬性约束、候选方向、当前进度
2. [docs/tech-research.md](docs/tech-research.md) — 技术预研究：灵矽平台能力边界、客户端选型、已验证的免硬件开发方案
3. [ideas/README.md](ideas/README.md) — 团队成员提交的候选游戏方案
   - [ideas/evaluation.md](ideas/evaluation.md) — 统一评分标准、评估结果和团队竞价表
4. [src/game_backend/README.md](src/game_backend/README.md) — 游戏后端技术手册：架构、开发、部署、灵矽/MCP 控制台配置、测试、端到端验证和已知问题

方向、调研结论或约束发生变化时，请持续更新对应文档，保持同步。
