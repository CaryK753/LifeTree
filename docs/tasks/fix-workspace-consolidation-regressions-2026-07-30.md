# 修复工作台整合回归

日期：2026-07-30
作者：wwj

## TODO

- [x] 修复目标编辑时描述被清空，以及无目标用户访问旧 Dashboard 卡住。
- [x] 明确 Scenario 必须绑定 Pathway，移除访问页面时自动休眠分支的副作用。
- [x] 用补偿迁移确定性修正 Scenario 到 Pathway 的历史概率回填。
- [x] 将待评估 InformationSource 纳入统一审核收件箱、计数和深链。
- [x] 消除审核中心重复展示的冲突，并拆分本轮涉及的超长页面。
- [x] 同步更新内置工具的 Scenario-Pathway 契约与模型可用 ID 上下文。
- [x] 运行后端测试、Ruff、Alembic、TypeScript 和生产构建验证。

## 数据职责

- Pathway 表示实现目标的可执行路线，也是决策树节点。
- Scenario 表示绑定到某条 Pathway 的假设沙箱，用于对同一路线做条件变化比较。
- 新 Scenario 不再依靠名称猜测 Pathway；旧数据暂时保留兼容解析。
- InformationSource 的可信度待评估属于审核中心待办，信源库只负责资产管理。

## 验收记录

- 后端 52 项测试通过，新增覆盖 Scenario 自动绑定、强制选择、选中对象演化和
  全量内置工具 Schema/Agent 绑定。
- Ruff 致命规则、本轮 import 规则、Python compileall 和迁移离线 SQL 生成通过。
- Next.js 生产构建通过，共 22 个动态路由。
- 浏览器验证 `/scenarios` 深链、审核信源标签和目标描述编辑；390px 视口无页面横向溢出。
