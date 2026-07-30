# 本地存储基础与内置工具契约加固

日期：2026-07-30
作者：wwj

## TODO

- [x] 复核工作台整合后的 Pathway、Scenario 与审核契约。
- [x] 修正 Agent 系统提示中的旧 Scenario 关系和上下文缺失 ID。
- [x] 统一内置 Scenario 创建工具与 REST API 的 Pathway 绑定规则。
- [x] 将 Agent 工具执行限制为串行，并增加全量工具注册与 Schema 烟雾测试。
- [x] 增加本地运行的跨平台目录、初始化锁和系统密钥存储基础。
- [x] 增加本地环境示例、准备脚本和分阶段存储设计。
- [x] 完成后端、前端、Docker 与差异检查。

提交、GitHub Actions 与 `spark` 部署属于代码完成后的交付流程，以 Git 历史、
Actions 运行记录和服务器容器状态为准，不通过后续文档提交补写，以免重复触发镜像构建。

## 非目标

- 本轮不创建 Tauri 桌面壳。
- 本轮不把 PostgreSQL 直接替换为 SQLite。
- 本轮不改变现有服务器部署的默认存储和服务拓扑。
