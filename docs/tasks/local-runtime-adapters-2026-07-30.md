# 本地运行时适配器

- 日期：2026-07-30
- 作者：wwj
- 状态：已完成

## 目标

- 建立 `BlobStore` 和 `JobRunner` 领域端口。
- 为 `local` 模式提供内容寻址文件存储和进程内任务执行器。
- 保持 `server` 模式的 MinIO、Celery 行为与接口兼容。
- 提供无需认证、且不暴露秘密的本地运行时能力握手。
- 推进 ORM 的 SQLite 方言兼容性，验证完整 metadata 可创建。

## TODO

- [x] 审计文件上传、即时任务触发和 ORM 方言耦合。
- [x] 实现并接入 BlobStore。
- [x] 实现并接入 JobRunner。
- [x] 增加运行时能力端点和桌面状态读取。
- [x] 建立 SQLite metadata 兼容测试并处理阻塞类型。
- [x] 完成回归测试和文档更新。

## 边界

- 本轮不实现 Neo4j 的完整本地图替代，也不把向量索引作为本地真相源。
- SQLite schema 在正式迁移器完成前仍是 Alpha；不能静默迁移现有 PostgreSQL 数据。
- 本地文件 key 由内容哈希生成，不接受调用方提供的相对路径。

## 完成结果

- `local` 模式可在无 PostgreSQL、Neo4j、Redis、MinIO 的环境中启动 FastAPI。
- SQLite 首次启动创建 39 张表并写入 `PRAGMA user_version=1`。
- 本地 API 切片覆盖注册、目标、行动、上传和系统组件；关闭后数据文件保留。
- 55 个 JSON 字段在 SQLite 使用 JSON1，在 PostgreSQL 继续编译为 JSONB。
- 向量字段在 SQLite 完成 schema 兼容；本轮新增 `in_process_cosine` 向量搜索适配器
  （`search_event_vectors`），本地语义搜索按 cosine 相似度排序，仅在 embedding
  生成失败时回退文本检索。`/api/v1/runtime/capabilities` 报告 `vectors=ready`。
- 图写入已由后续的 `EmbeddedGraphStore` 接入（见
  `embedded-graph-runtime-2026-07-30.md`），能力握手 `graph=ready`。本轮结束时
  该项仍为 `pending`，桌面壳当时不解锁本地私有入口。

## 验证

- 后端全量：`67 passed`。
- 本地隔离切片：无 PostgreSQL、Neo4j、Redis、MinIO 环境下通过。
- PostgreSQL DDL：Goal JSON 字段继续编译为 `JSONB`。
- 前端：22 个路由生产构建通过。
- 桌面：Vite、Rust 单元测试、Clippy、格式检查和 macOS App 构建通过。
- 基础设施：`docker compose config --quiet` 通过，服务器默认模式未改变。
