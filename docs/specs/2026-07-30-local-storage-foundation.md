# 本地存储运行时基础设计

日期：2026-07-30
作者：wwj

## 决策

现在开始准备本地存储模式是合适的，但当前不能把 `DATABASE_URL` 简单替换为
SQLite，也不能宣称离线模式已经可用。现有模型直接使用 PostgreSQL `JSONB`、
pgvector，并依赖 Neo4j、Redis/Celery 和 MinIO；直接切换会产生静默降级和两套
行为不一致的业务逻辑。

本轮只建立不改变服务器默认行为的 Phase 0 基础：

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

## 边界

- 本地隐私模式仅支持单用户，不与 `multi` 组合。
- 云端模式以远程服务器为权威，本地缓存不是第二个可独立写入的数据库。
- 任何从本地到云端的转换都必须经过可预检、可校验、可回滚的数据迁移，不允许
  通过切换环境变量隐式改变数据权威。
