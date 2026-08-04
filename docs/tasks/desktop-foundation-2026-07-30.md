# 桌面端第一阶段基础

- 日期：2026-07-30
- 作者：wwj
- 状态：已完成

## 目标

- 将 AI 单轮工具调用预算调整为 64，同时保留相同调用防重保护。
- 建立 Tauri 2 桌面工程及 Windows/macOS 开发、检查入口。
- 支持选择 `local_private`、`self_hosted`、`cloud_multi_tenant` 运行模式。
- 建立前端运行时 API 地址解析，为本地 sidecar 随机端口和远程服务复用同一 UI 做准备。

## TODO

- [x] 核对桌面架构、当前本地运行时基础和前端 API 调用方式。
- [x] 调整 Advisor 工具预算和 LangGraph 配套递归上限。
- [x] 实现运行时 API URL 解析并覆盖 JSON、SSE、上传与下载请求。
- [x] 实现 Tauri 启动器、配置持久化、安全 URL 校验和最小权限 capability。
- [x] 增加桌面端 CI 检查和开发文档。
- [x] 完成后端、前端、Rust 与桌面 UI 验证。

## 边界

- 本轮不宣称 `local_private` 已可用；SQLite、文件 BlobStore、嵌入式图和进程内任务运行器完成前，启动器必须保持该选项不可进入。
- 本轮不打包 PostgreSQL、Neo4j、Redis、MinIO 或 Docker 到桌面客户端。
- 远程页面不获得 Tauri 宿主命令权限；服务地址仅允许 HTTPS，或开发用途的本机回环 HTTP。

## 验证

- 后端：`58 passed`。
- 前端：TypeScript 检查和 22 个路由生产构建通过。
- 桌面：Vite 生产构建、Rust 单元测试、`cargo fmt`、Clippy 和 Tauri release 无安装包构建通过。
- 视觉：`1280x820` 启动器截图检查通过，窄窗口使用明确的视口宽度和最小轨道约束。
- 依赖：npm 审计 0 个漏洞；本机已安装 Rust stable、rustfmt 和 Clippy。
