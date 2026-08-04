# 嵌入式图运行时

- 日期：2026-07-30
- 作者：wwj
- 状态：已完成

## 目标

- 为 `local` 模式实现持久化节点/边 GraphStore，不依赖 Neo4j。
- 保持现有 GraphService 调用契约不变。
- 支持 Goal、Pathway、Requirement、RiskFactor、Source、Event、Scenario 镜像。
- 支持邻域查询和 Event -> RiskFactor -> Pathway -> Goal 风险传播。
- 本地启动时从关系事实幂等重建派生图。

## TODO

- [x] 审计 GraphService 调用方和图查询契约。
- [x] 拆分 Cypher 常量，控制 GraphService 文件规模。
- [x] 实现本地节点/边模型和 EmbeddedGraphStore。
- [x] 接入 GraphService 并修复本地风险传播的外部驱动依赖。
- [x] 增加本地图持久化、邻域、传播与 API 回归测试。
- [x] 更新能力握手、桌面状态和项目文档。

## 边界

- 图表是可由关系事实重建的派生索引，不成为第二真相源。
- 本地模式不解释任意 Cypher；只实现领域所需的显式 GraphStore 操作。
- 用户/租户边界继续由关系库查询和可见节点集合约束。

## 完成结果

- `LocalGraphNode`/`LocalGraphEdge` 提供独立于服务器 Alembic metadata 的 SQLite
  节点/边表，边以 `sha256(source\0relation\0target)` 作主键保证幂等。
- `EmbeddedGraphStore` 实现 Goal/Pathway/Requirement/RiskFactor/Source/Event/Scenario
  的镜像写入、`neighborhood`、`propagate_risk` 与 `rebuild`；`GraphService` 在
  `local` 模式下全部走嵌入式实现，Cypher 仅在 `server` 模式执行。
- Cypher 常量抽到 `services/graph_queries.py`，`graph.py` 只保留分支调度。
- `rebuild_projection` 从关系事实（含 `pathway_requirements`、
  `pathway_risk_factors`、`Relationship`）幂等重建派生图。
- `/api/v1/runtime/capabilities` 报告 `graph=ready`，`/api/v1/system/components`
  报告 `embedded_graph` 为 `available=True, enabled=True`，二者保持一致。
- 回归测试覆盖：store 级增量镜像/邻域/传播、全量重建幂等性、本地 app 启动后
  系统组件与能力握手中 `graph` 状态断言（防止两侧再次漂移）。

## 验证

- 后端全量测试通过（含 `test_embedded_graph_store.py` 3 项、
  `test_local_runtime_adapters.py` 9 项）。
- Ruff 致命规则、`local` 模式隔离启动切片通过。
