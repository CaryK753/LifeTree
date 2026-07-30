# 工作台整合设计 spec

**日期**：2026-07-30
**作者**：wwj
**状态**：待实施
**关联文档**：
- [项目计划书](../项目计划书：LifeTree（人生树）.md) §5 用户体验与交互设计
- [现状审计与改进建议](../现状审计与改进建议-2026-07-28.md)

---

## 1. 背景与问题

当前侧栏「决策管理」分组下挂了 7 个入口（概览 / 目标罗盘 / 目标 / 行动日历 / 证据关系图 / 情景对比 / 决策树），用户需要在多个页面之间跳转才能完成"看一个目标的整体状态→对比情景→审视决策树"这类连续任务。三个核心问题：

1. **目标罗盘 vs 目标**：`/dashboard` 与 `/goals/[id]` 都基于同一个 `useDashboard(goalId)` 数据源，渲染同类分析卡片（GoalCompass、RiskHeatmap、Milestones、EventFeed、CredibilityMeter），前者多了 Streak / Cruising / RegretFreeActions / FactorBreakdown / SurvivalCurve / TimelineGantt，后者多了 Pathways/Requirements/Scenarios 标签页。两个页面功能高度重叠，用户不知道该看哪个。
2. **三图页分散**：`/graph`（Cytoscape 拓扑）、`/scenarios`（树/网格/对比/演化四视图）、`/tree/[goalId]`（React Flow + dagre 决策树）都是"对同一个 goal 的可视化"，却分成三个独立路由，用户每次都要先在脑子里"选页"再"选 goal"，增加认知成本。三者职责并不重叠（图谱=实体关系拓扑；情景=分支假设对比；决策树=路径节点状态），但视觉表达类似，应作为同一工作台的不同视图。
3. **信息来源 vs 待审核**：`/sources` 显示"信源可信度待评定"（credibility=pending），`/review` 显示"事件状态待审核"（status=pending_review），两套待办查询的是不同字段，因此 sources 里的 pending 不会出现在 review。用户期望"所有待我处理的事都在一个收件箱里"。后端已有 `useUnifiedReview()` 聚合了 events + source_proposals + risk_proposals + conflicts，但前端 /review 没有使用 sources 部分，/sources 又单独维护一套 pending 队列。

---

## 2. 设计目标

- 把"看一个目标的全貌"压缩为**单一工作台**：用户选了目标，所有相关视图（概览 / 路径 / 图谱 / 情景 / 决策树）都在同一页签切换。
- 把"待我处理的事"压缩为**单一审核中心**：事件 / 信源提案 / 风险提案 / 冲突 / 信源可信度待评定都在 `/review` 内以 Tab 呈现。
- 侧栏从 7 入口减至 4 入口，保留：**目标 / 行动日历 / 智能助手 / 风险预警**；信息来源与待审核合并到「审核中心」，图谱/情景/决策树收入目标工作台。
- 与项目计划书 §5 的"降低认知成本、消除决策瘫痪、统一收件箱"理念一致；不引入新数据模型，仅做前端路由与组件整合。

---

## 3. 范围

**做**：
- 重构 `/goals/[id]/page.tsx` 为 6 视图工作台：`overview / pathways / graph / scenarios / tree / scenarios-compare`（合并 dashboard 全部分析卡片到 overview）。
- 在 `/review/page.tsx` 新增「信源」Tab，把 `/sources` 的 pending 队列与可信度标记功能搬过来；`/sources` 路由保留为"信源列表 + 生命周期 + 调度"管理页（移除 pending 卡片，避免与 review 重复）。
- `sidebar.tsx` 导航分组重构：4 个主入口（目标 / 行动 / 助手 / 预警）+ 信息分组（审核中心 / 信息来源）+ 数据分组（录入 / 插件）。
- `/dashboard` 路由保留为兼容入口，重定向到 `/goals/{primary_goal_id}` 或 `/goals`。
- i18n 6 语言新增 `nav.reviewCenter`、`goalDetail.tab.graph`、`goalDetail.tab.tree`、`goalDetail.tab.scenariosCompare` 等键。

**不做**：
- 不改后端 API 或数据模型（`useUnifiedReview` 已就绪）。
- 不改 `/graph`、`/scenarios`、`/tree/[goalId]` 独立路由（保留作为深链入口，但从侧栏移除）。
- 不改 `/actions`、`/chat`、`/notifications`、`/ingest`、`/plugins`、`/admin`。
- 不重构 dashboard 子组件（GoalCompass、RiskHeatmap 等），只搬位置。

---

## 4. 信息架构

### 4.1 新侧栏结构

```
决策管理
  ├─ 目标 (/goals)               ← 列表 + 工作台入口
  └─ 行动日历 (/actions)
洞察与辅助
  ├─ 智能助手 (/chat)
  ├─ 审核中心 (/review)           ← 升级，含信源 Tab
  ├─ 信息来源 (/sources)          ← 保留，移除 pending 卡片
  └─ 风险预警 (/notifications)
数据与信息
  ├─ 信息录入 (/ingest)
  └─ 插件 (/plugins)
系统（admin 可见）
  └─ 管理后台 (/admin)
```

**变化**：移除「概览」（合并到 /goals 列表上方）、「目标罗盘」（合并到 /goals/[id]）、「证据关系图」、「情景对比」、「决策树」（合并到 /goals/[id] 工作台）。

### 4.2 目标工作台 Tab 结构

`/goals/[id]` 页面 Tab：

| Tab | 内容 | 数据源 |
| --- | --- | --- |
| 概览 (overview) | GoalCompass + Streak + Cruising + RegretFreeActions + FactorBreakdown + SurvivalCurve + RiskHeatmap + TimelineGantt + Milestones + EventFeed + CredibilityMeter + ChangesSummaryBanner | `useDashboard(goalId)` |
| 路径 (pathways) | Pathway 卡片列表 + Requirements 表 | `usePathways` / `useRequirements` |
| 图谱 (graph) | Cytoscape 知识图谱拓扑（节点可点击下钻） | `useGraph(goalId)` |
| 情景 (scenarios) | 情景树 + 概率曲线 overlay + 演化视图 | `useScenarios(goalId)` |
| 决策树 (tree) | React Flow + dagre 决策路径 | `getDecisionTree(goalId)` |

> 移除原 `/goals/[id]` 的 `scenarios` Tab 内嵌的 `ScenarioComparison`（死亡组件），改用 `/scenarios` 同款 ScenarioTree + ScenarioCurveOverlay + ScenarioEvolution 组件。`grid` viewMode 因长期未实现，删除按钮。

### 4.3 审核中心 Tab 结构

`/review` 页面 Tab：

| Tab | 内容 | 数据源 |
| --- | --- | --- |
| 事件 (events) | 当前 `usePendingReview` 列表 + IntelligenceReviewSections（source_proposals / risk_proposals / conflicts） | `usePendingReview` + `useUnifiedReview` |
| 信源 (sources) | `/sources` 中 pending 卡片搬过来：信源可信度待评定列表 + 标记可靠/存疑按钮 | `useSources` 过滤 pending |
| 冲突 (conflicts) | 从 IntelligenceReviewSections 抽出单独 Tab | `useUnifiedReview.conflicts` |

`/sources` 页面：移除「Review Queue」卡片，保留 CredibilityMeter / LifecyclePanel / 全量列表 / 调度对话框。在头部加提示「待评定信源请至审核中心处理」。

---

## 5. 组件与数据流

### 5.1 目标工作台

```
GoalsDetailPage
├─ Header（标题 + 状态徽章 + 快捷按钮 + 编辑按钮）
├─ GoalEditDialog
├─ GoalCelebration
└─ Tabs
   ├─ overview  → <DashboardBody>（从 /dashboard 抽出）
   ├─ pathways  → <PathwaysTab>（保留原实现）
   ├─ graph     → <KnowledgeGraph goalId={goalId} />
   ├─ scenarios → <ScenariosTab goalId={goalId} />（含 tree/compare/evolve 视图切换）
   └─ tree      → <DecisionTreeTab goalId={goalId} />（封装 ReactFlowProvider）
```

**抽组件**：把 `app/dashboard/page.tsx` 的 `DashboardBody` + `StatChip` + `CruisingStatChip` + `EmptyGoalState` 抽到 `components/dashboard/dashboard-body.tsx`，供 `/goals/[id]` overview Tab 复用。

**goal 选择**：`/goals` 列表页不变；点击卡片进入 `/goals/[id]`，即工作台。

**兼容**：`/dashboard` 路由保留，重定向逻辑：读 `useUserProfile().primary_goal_id` → 若有则 `router.replace('/goals/'+id)`，否则 `router.replace('/goals')`。

### 5.2 审核中心

```
ReviewCenterPage
├─ Header（标题 + 总待办徽章）
└─ Tabs
   ├─ events     → <EventsTab>（原 ReviewInboxPage 主体）
   ├─ sources    → <SourcesReviewTab>（pending 队列 + 标记按钮）
   └─ conflicts  → <ConflictsTab>（从 IntelligenceReviewSections 拆出）
```

**新增组件**：`components/review/sources-review-tab.tsx` — 复用 `/sources` 中 pending 卡片的 UI，但只显示 pending 列表 + 标记按钮（不含调度、删除等管理操作，那些留在 /sources）。

**移除**：`/sources/page.tsx` 的「Review Queue」卡片（约 80 行），改为头部一行链接到 /review。

### 5.3 侧栏

`NAV_GROUPS` 改为：

```ts
const NAV_GROUPS: NavGroup[] = [
  {
    labelKey: "nav.group.decisions",
    items: [
      { href: "/goals", labelKey: "nav.goals", icon: Compass },
      { href: "/actions", labelKey: "nav.actions", icon: ListTodo },
    ],
  },
  {
    labelKey: "nav.group.insights",
    items: [
      { href: "/chat", labelKey: "nav.chat", icon: MessageSquare },
      { href: "/review", labelKey: "nav.reviewCenter", icon: Inbox },
      { href: "/sources", labelKey: "nav.sources", icon: ShieldCheck },
      { href: "/notifications", labelKey: "nav.notifications", icon: Bell },
    ],
  },
  {
    labelKey: "nav.group.data",
    items: [
      { href: "/ingest", labelKey: "nav.ingest", icon: Upload },
      { href: "/plugins", labelKey: "nav.plugins", icon: Plug },
    ],
  },
];
```

移除：`Home`、`Gauge`、`Network`、`GitBranch`、`TreePine` 图标 import；移除 `/`、`/dashboard`、`/graph`、`/scenarios`、`/tree` 项。

> 「概览」(`/`) 路由保留，但不在侧栏；用户点 logo 回首页。

---

## 6. 路由兼容

| 旧路由 | 行为 |
| --- | --- |
| `/` | 保留首页（不动） |
| `/dashboard` | 重定向到 `/goals/{primary_goal_id}` 或 `/goals` |
| `/graph` | 保留页面，但不在侧栏（深链入口） |
| `/scenarios` | 保留页面，但不在侧栏 |
| `/tree/[goalId]` | 保留页面，但不在侧栏 |
| `/sources` | 保留，移除 Review Queue 卡片 |
| `/review` | 升级为审核中心（3 Tab） |

---

## 7. i18n 新增键

6 语言（zh-CN / zh-TW / en / es / de / fr）均需补齐：

```
nav.reviewCenter            // 审核中心 / 審核中心 / Review Center / Centro de revisión / Prüfzentrum / Centre de révision
nav.group.workbench         // 工作台（若需分组重命名）
goalDetail.tab.graph        // 图谱 / 證據圖譜 / Graph / Grafo / Graph / Graphe
goalDetail.tab.tree         // 决策树 / 決策樹 / Decision Tree / Árbol de decisiones / Entscheidungsbaum / Arbre de décision
goalDetail.tab.scenariosCompare  // 情景对比 / 情境對比 / Scenarios / Escenarios / Szenarien / Scénarios
review.tab.events           // 事件 / 事件 / Events / Eventos / Ereignisse / Événements
review.tab.sources          // 信源 / 信源 / Sources / Fuentes / Quellen / Sources
review.tab.conflicts        // 冲突 / 衝突 / Conflicts / Conflictos / Konflikte / Conflits
review.sources.empty        // 没有待评定信源 / 無待評定信源 / No sources pending review / ...
review.sources.subtitle     // 标记信源可信度，影响后续推理权重 / ...
sources.reviewHint          // 待评定信源请至审核中心处理 / ...
dashboard.redirecting       // 正在跳转到目标工作台 / ...
```

废弃键（保留但不再使用，避免破坏旧翻译）：`nav.dashboard`、`nav.graph`、`nav.scenarios`、`nav.tree`、`nav.overview`。

---

## 8. 死代码清理

- `components/scenarios/scenario-comparison.tsx`：原 `/goals/[id]` scenarios Tab 内嵌，被新的 `<ScenariosTab>` 替换后删除。
- `app/scenarios/page.tsx` 的 `viewMode === "grid"` 分支：未实现，删除按钮与分支。
- `TYPE_COLORS.Scenario` 占位（如存在于 graph 配置中）：检查并清理。

---

## 9. 验收

- [ ] `/goals/[id]` 工作台 5 个 Tab 都能渲染，切换无报错。
- [ ] `/dashboard` 访问自动跳转到 `/goals/{id}` 或 `/goals`。
- [ ] `/review` 三个 Tab 都能渲染，信源 Tab 标记后 `/sources` 列表同步刷新。
- [ ] `/sources` 移除 Review Queue 卡片，头部有「待评定信源请至审核中心」提示。
- [ ] 侧栏只剩 8 个主入口（2+4+2）+ admin 项，无 `/dashboard`、`/graph`、`/scenarios`、`/tree`、`/`(概览)。
- [ ] 6 语言切换无 missing key 警告。
- [ ] `pnpm -C frontend typecheck` 通过。
- [ ] `pnpm -C frontend lint` 无新增错误。

---

## 10. 风险与回滚

- **风险**：用户 bookmark 了 `/dashboard`、`/graph`、`/scenarios`、`/tree` — 这些路由保留，不会 404；仅 `/dashboard` 重定向。
- **回滚**：所有改动集中在前端 `app/`、`components/`、`lib/i18n/messages.ts`，git revert 即可恢复。
- **未覆盖**：移动端 PWA 抽屉式侧栏的视觉验证需手动测试；如发现条目过密，可后续调整分组。
