# SQLite Schema 迁移机制

- 日期：2026-07-31
- 作者：wwj
- 状态：已完成
- 关联：`docs/specs/2026-07-30-local-storage-foundation.md`、
  `docs/tasks/local-runtime-adapters-2026-07-30.md`

## 背景

本地隐私模式用 SQLite 作为关系库。当前 `initialize_local_database()` 直接调用
`Base.metadata.create_all(engine)` 建表，再 `PRAGMA user_version=1` 标记版本。

这导致两个问题：

1. **Schema 不可演进**：`create_all` 只会创建缺失的表，不会 ALTER 已有表。一旦
   本地库被使用后 ORM 模型新增列/索引/约束，旧库的旧列会保留，新代码读写时
   列缺失会抛 `OperationalError`，用户数据损坏。
2. **版本号无语义**：`user_version=1` 是手动写的常量，不反映实际 schema 状态，
   也无法判断一个库是否需要升级。

因此 `database` 适配器状态保持 `alpha`，`local_private_ready` 为 `false`。
本设计为本地 SQLite 引入轻量、可测试、可回滚的 schema 迁移机制，使 schema
可版本化演进，把 `database` 推向 `ready`。

## 目标

- 本地库启动时按 `user_version` 顺序应用未执行的迁移，每步在独立事务内。
- 迁移失败时回滚该步并中止启动，保留旧 schema 与数据，避免半成品状态。
- 全新库与现有 `user_version=1` 库均可正确升级，无需手工干预。
- 迁移函数可单元测试，无需真实启动整个 app。
- 不引入 Alembic 的全量复杂度（本地单库、单进程、无多人协作迁移脚本）。

## 非目标

- 不替代服务器侧的 Alembic 迁移；PG schema 仍由 Alembic 管理。
- 不实现 `.lifetree` 归档包导入导出（那是数据迁移，非 schema 迁移）。
- 不实现本地→云端的数据迁移流程（独立工作项）。
- 不实现加密（独立工作项，见 `local-storage-foundation.md`）。
- 不支持降级迁移（rollback）；失败时保留旧版本，由人工修复后重试。

## 设计

### 版本号语义

- `PRAGMA user_version` 存储 schema 版本号，从 `0` 开始。
  - `0`：全新库，未建任何 schema。
  - `1`：初始 schema（等价当前 `create_all` 建出的全部表 + 本地图表）。
  - `2, 3, ...`：后续每次 schema 变更递增。
- 代码侧维护 `LATEST_SCHEMA_VERSION = N`，表示当前代码期望的最高版本。
- 启动后库的 `user_version` 必须 `<= LATEST_SCHEMA_VERSION`；若
  `user_version > LATEST_SCHEMA_VERSION`（用户降级了 app 版本），拒绝启动并报错，
  避免旧代码读写不认识的 schema。

### 迁移注册表

在 `app/db/sqlite_migrations.py` 定义迁移注册表：

```python
SchemaMigration = namedtuple("SchemaMigration", ["version", "description", "apply"])

# version=N 表示该迁移将库从 N-1 升级到 N
MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration(1, "initial_schema", apply_v1_initial_schema),
    # SchemaMigration(2, "add_event_index", apply_v2_event_index),
)
```

每个 `apply_vN(conn)` 接收 SQLAlchemy `Connection`，在自身事务内执行 DDL，不提交
（由外层统一提交）。迁移函数必须**幂等安全**：重复执行不报错（防崩溃重试时
重复应用同一步）。DDL 用 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS` 等。

### 启动流程

`initialize_local_database()` 改造为：

1. 确保 ORM 模型已 import（注册 metadata）。
2. 读 `PRAGMA user_version` → `current`。
3. 若 `current > LATEST_SCHEMA_VERSION`：抛 `RuntimeError`，拒绝启动。
4. 对 `current < target <= LATEST_SCHEMA_VERSION` 的每个迁移：
   - 在 `engine.begin()` 事务内调用 `migration.apply(conn)`。
   - 成功：事务提交，`PRAGMA user_version = target`（同事务内）。
   - 失败：事务回滚，向上抛异常，中止启动。库停留在 `current` 版本，数据完整。
5. 迁移全部完成后，触发 `EmbeddedGraphStore().rebuild()`（图是派生索引，重建
   不属于 schema 迁移，放在最后）。

事务粒度：**每个迁移一步事务**。不在一个大事务里跑全部迁移，避免长事务锁库，
也让部分失败的诊断更清晰。

### v1 初始迁移

`apply_v1_initial_schema(conn)` 等价当前行为：

- `Base.metadata.create_all(conn)` 建全部 ORM 表。
- `LocalGraphBase.metadata.create_all(conn)` 建本地图表。
- 全部 DDL 本就 `IF NOT EXISTS` 语义（SQLAlchemy `create_all` 不重建已有表），
  因此对已存在 `user_version=1` 但实际表已建的库重入安全。

这保证：
- 全新库（`user_version=0`）：应用 v1，建表，版本→1。
- 现有库（`user_version=1`，表已建）：跳过 v1（`current >= target`），无 DDL。

### 向后兼容

| 库状态 | `user_version` | 启动行为 |
|---|---|---|
| 全新 | 0 | 应用 v1，建表，版本→1 |
| 当前部署 | 1 | 跳过 v1，直接 rebuild 图 |
| 未来 v2 后的旧部署 | 1 | 应用 v2，版本→2，再 rebuild 图 |
| 降级（用户装回旧 app） | > LATEST | 拒绝启动，报错指引升级 |

当前所有已部署本地库的 `user_version` 都是 `1`，与 v1 迁移目标一致，因此改造
对现有部署零影响。

### 迁移函数契约

```python
def apply_vN(conn: Connection) -> None:
    """将 schema 从 N-1 升级到 N。在调用方提供的事务内执行。

    要求：
    - 幂等：重复执行不抛错（用 IF NOT EXISTS / 先检查后执行）。
    - 不调用 conn.commit() / conn.rollback()（由外层管理）。
    - 不修改 PRAGMA user_version（由外层管理）。
    - 失败时抛异常，外层回滚事务。
    """
```

## 边界

- 迁移只管 schema，不管数据修复。数据迁移由业务层在迁移后另行处理（如本地图
  rebuild）。
- 不支持跨版本跳跃式迁移；必须按版本号顺序应用每一步。
- 迁移函数不得依赖 app 运行时状态（settings、缓存等），只依赖 conn 与 metadata。
- `local` 模式仍是单进程；迁移在启动时串行执行，无并发问题。

## 验证计划

- 单元测试（`tests/test_sqlite_migrations.py`）：
  - 全新库：`user_version` 从 0 升到 `LATEST`，全部表存在。
  - 现有库（预置 `user_version=1` + 表）：跳过 v1，版本不变，表不重建。
  - 迁移失败回滚：注入一个抛异常的测试迁移，验证事务回滚、`user_version` 不变、
    启动中止。
  - 降级保护：预置 `user_version > LATEST`，验证拒绝启动。
  - 幂等性：对已应用的迁移重复调用不报错。
- 现有 `test_local_app_boots_without_server_infrastructure` 仍通过（端到端验证
  本地启动建库 + 数据保留）。
- `test_local_runtime_adapters.py` 中 `database` 适配器状态断言从 `alpha` 改为
  `ready`。

## 后续迁移示例

未来需要给 `events` 表加索引时：

```python
def apply_v2_event_index(conn: Connection) -> None:
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_events_user_created "
        "ON events (user_id, created_at)"
    ))

MIGRATIONS = (
    SchemaMigration(1, "initial_schema", apply_v1_initial_schema),
    SchemaMigration(2, "event_user_created_index", apply_v2_event_index),
)
LATEST_SCHEMA_VERSION = 2
```

现有 `user_version=1` 的库启动时自动应用 v2，版本→2。

## 完成结果

- `app/db/sqlite_migrations.py` 实现迁移注册表 `MIGRATIONS`、版本号
  `LATEST_SCHEMA_VERSION`、`get_schema_version` 与 `run_pending_migrations`。
- v1 初始迁移 `apply_v1_initial_schema` 等价原 `create_all` 行为，对已建库幂等。
- `initialize_local_database()` 改为调用 `run_pending_migrations(engine)`，移除
  原手动 `create_all` + `PRAGMA user_version=1`。
- 降级保护：`user_version > LATEST_SCHEMA_VERSION` 时抛 `RuntimeError` 拒绝启动。
- 每个迁移独立事务（`engine.begin()`），失败回滚该步，`user_version` 停留在
  最后成功版本，数据完整。
- `database` 适配器 `backend` 从 `sqlite` 改为 `sqlite_migrations`，`status` 保持
  `alpha`（加密未完成，见 `local-storage-foundation.md` 边界）。

## 验证

- `tests/test_sqlite_migrations.py` 5 项全过：全新库迁移、现有 v1 库跳过、
  迁移失败回滚保留旧版本、降级拒绝启动、v1 幂等性。
- 后端全量测试通过，`test_local_app_boots_without_server_infrastructure`
  端到端验证本地启动建库 + 数据保留仍通过。
- Ruff 致命规则零错误。
