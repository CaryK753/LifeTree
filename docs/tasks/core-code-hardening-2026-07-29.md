# 主代码稳定性完善

日期：2026-07-29
作者：wwj

## 范围

- 审计当前工作树中尚未提交的核心能力实现。
- 优先修复接口契约、租户隔离、幂等、事务一致性和错误处理问题。
- 补充高风险路径回归测试并验证迁移、后端和前端构建。
- 本轮不实现桌面客户端、离线存储或云同步。

## TODO

- [x] 阅读仓库规则、当前改动和测试入口。
- [x] 运行基线检查并定位真实失败。
- [x] 审计新增 API、服务与迁移的高风险路径。
- [x] 实现最小修复并补充测试。
- [x] 运行后端测试、静态检查、前端类型检查与构建。
- [x] 记录验证结果与剩余风险。

## 验收标准

- 当前新增路由可正常加载，迁移链保持单一 head。
- 用户数据访问均受租户/所有权约束。
- 重复请求不会创建等价目标、重复提案或破坏状态机。
- 失败写入不会留下可见的部分提交状态。
- 受影响测试、前端类型检查和生产构建通过。

## 完成内容

- 新增 Action 完整性服务，统一校验 Goal、Scenario、Pathway、Requirement、RiskFactor 关联归属。
- Action 更新、完成接口与 AI 行动日历使用同一状态逻辑；失败校验不会提前污染完成状态。
- 管理员跨用户权限明确为只读，目标、路径、要求、Action 和信源提案写入必须由所有者执行。
- 交叉验证按信源所有者过滤；重复裁决幂等；只惩罚与胜出结论不一致的来源。
- 共享 RiskFactor 的写接口改为管理员权限，读取仍要求登录。
- 信源提案查询下推租户过滤，拒绝/接受状态转换增加所有权与冲突约束。
- 备份 merge 使用实体级 savepoint，replace 有错误时整体回滚；补充 Requirement/RiskFactor 多对多关联导出恢复及共享风险去重。
- ORM 索引、Passkey 唯一约束和循环外键声明与 Alembic head 对齐。
- 移除 `next/font/google` 构建期下载，前端生产构建不再依赖 Google Fonts。

## 验证结果

- 后端：`22 passed`。
- 定向 Ruff：`All checks passed!`。
- Python：`compileall` 通过。
- Alembic：数据库处于 `i2b3c4d5e6f7 (head)`，`No new upgrade operations detected`。
- OpenAPI：153 条路径成功生成，5 条本轮核心路由存在。
- 前端：`npm run type-check` 与 `npm run build` 通过，22 个页面完成生产构建。
- 运行时：后端 `/health` 返回 200，前端 `/` 返回 200。
- 差异检查：`git diff --check` 通过。

## 剩余风险

- `RiskFactor` 仍是共享本体，没有用户级所有权；当前通过管理员写权限避免跨租户污染，后续应区分全局模板和用户风险实例。
- `BackupService` 仍是超大历史文件，后续应按 export/import/codec 拆分并增加真实 PostgreSQL 往返恢复测试。
- 全仓 Ruff 尚有既存告警；本轮只保证受影响文件在排除项目既有 FastAPI `B008` 与 UTC 风格项后通过。
- 交叉验证仍基于 Relationship 对象 ID，不等同于完整的时态 Assertion/Claim 证据模型。
