# 本地存储运行时基础设计

日期：2026-07-30
作者：wwj

## 决策

现在开始准备本地存储模式是合适的，但当前不能把 `DATABASE_URL` 简单替换为
SQLite，也不能宣称离线模式已经可用。现有模型直接使用 PostgreSQL `JSONB`、
pgvector，并依赖 Neo4j、Redis/Celery 和 MinIO；直接切换会产生静默降级和两套
行为不一致的业务逻辑。

Phase 0 首轮建立了不改变服务器默认行为的目录与密钥基础：

- `LIFETREE_STORAGE_MODE=server|local` 明确运行时意图，默认仍为 `server`。
- `platformdirs` 解析 Windows/macOS 原生数据、配置和缓存目录。
- `filelock` 为本地初始化、迁移和单实例启动提供跨进程锁基础。
- `keyring` 作为 `local` 可选依赖，通过 macOS Keychain 或 Windows Credential
  Manager 保存模型密钥；密钥不得写入普通配置文件或数据库导出。
- `prepare_local_runtime.py` 只创建目录并报告尚未完成的适配器，不启动桌面端，
  也不伪装成本地数据库已经可用。

## 数据目录

不指定 `LIFETREE_DATA_DIR` 时使用操作系统标准目录；指定后使用便携式目录树：

```text
<data>/
  config/
  cache/
  objects/
  plugins/
  backups/
  runtime.lock
```

仓库内的 `.lifetree-local/` 被忽略，避免测试数据和私密文件进入 Git。

## 后续阶段

1. 定义 `BlobStore`、`GraphStore`、`JobRunner` 和搜索端口，移除 API 对具体基础设施
   客户端的直接依赖。
2. 先实现本地文件 BlobStore 与进程内 JobRunner，分别替代 MinIO 和 Redis/Celery。
3. 清理 SQLAlchemy 模型中的 PostgreSQL 方言直绑，建立 SQLite JSON1/FTS5 与迁移
   测试；向量索引作为可重建派生数据。
4. 用关系边表和 NetworkX 实现嵌入式图谱分析，Neo4j 继续作为服务器增强后端。
5. 完成加密、备份恢复、版本化 `.lifetree` 迁移包和本地到云端的显式迁移流程后，
   才将 `local` 标记为可用运行模式。

## 2026-07-30 实现进展

- 已实现 SQLite Alpha 引擎、JSON1 方言类型和首次 schema 创建。
- 已实现 SQLite schema 迁移机制（`app/db/sqlite_migrations.py`）：按
  `PRAGMA user_version` 顺序应用迁移，每步独立事务、失败回滚、降级拒绝启动，
  全新库与现有 v1 库均可正确升级。schema 已可版本化演进。
- 已实现本地数据库加密（`app/core/local_encryption.py`）：Fernet 对称加密
  保护敏感字段（LLM API Key 等），主密钥存 OS Keychain / Credential Manager
  或 `LIFETREE_LOCAL_ENCRYPTION_KEY` env var。`EncryptedText` TypeDecorator
  在 `local` 模式透明加解密，`server` 模式透传。`database` 适配器状态升为
  `ready`。
- 已实现 SHA-256 内容寻址的本地文件 BlobStore，并接入上传链路。
- 已实现串行进程内 JobRunner，并接入即时信源刷新。
- 已增加 `/api/v1/runtime/capabilities` 桌面握手。
- 已通过“注册 -> 创建目标 -> 创建行动 -> 上传文件 -> 重启后保留数据库文件”的隔离测试。
- 已实现嵌入式 GraphStore（SQLite 节点/边表 + NetworkX 风格的邻域与风险传播），
  并接入 GraphService；`/api/v1/runtime/capabilities` 与 `/api/v1/system/components`
  在 `local` 模式下均报告 `graph` 为 `ready`/`available`。

向量索引的搜索侧已由 `in_process_cosine` 适配器覆盖，但本地 embedding 生成链路
（依赖外部 LLM 服务）仍未完成。sidecar 打包端到端验证已完成，所有适配器均
`ready`，`local_private_ready` 返回 `true`。本地 embedding 生成不影响
`local_private_ready`（降级为文本检索，不阻塞本地隐私模式启动）。

## 边界

- 本地隐私模式仅支持单用户，不与 `multi` 组合。
- 云端模式以远程服务器为权威，本地缓存不是第二个可独立写入的数据库。
- 任何从本地到云端的转换都必须经过可预检、可校验、可回滚的数据迁移，不允许
  通过切换环境变量隐式改变数据权威。
