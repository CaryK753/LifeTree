# 交叉验证、深度研究与多源搜索引擎设计

- 日期：2026-08-07
- 作者：wwj
- 状态：设计稿，待评审
- 关联：
  - `docs/项目计划书：LifeTree（人生树）.md` §4.9、§11.2（缺口 E）、§11.3（第五阶段 P1）
  - `docs/决策本体与预测模型设计-2026-07-28.md`
  - `docs/现状审计与改进建议-2026-07-28.md`
  - `docs/specs/2026-07-30-local-storage-foundation.md`（领域端口）

## 背景

LifeTree 已具备较完整的决策情报工作台骨架：信源建模（双轨可信度）、结构化抽取（四类原子 + PG/Neo4j 双写）、信源自动发现（LLM + Tavily probe）、Beta 信誉回流、LangGraph ReAct Agent（46+ 工具）、Review Inbox、风险传播与情景推演。

对照 §11 愿景差距，三个 P1 能力仍停留在 L1 骨架或零实现：

1. **交叉验证**（缺口 E）：当前工作树已有冲突检测与裁决服务，但存在"两套冲突系统不互通""孤儿模块""结构化管道不触发冲突检测""LLM `conflicts_with` 字段被丢弃"等断链。
2. **多源搜索引擎**：`CrawlerService` 完全硬编码 Tavily，无 `SearchEngine` 抽象，无 exa/博查配置点，搜索结果不落库。
3. **深度研究**：全仓库零匹配，无任何"多轮检索 + 跨源合并 + 综合报告"原语。

三功能强相关：多源搜索是基础层，深度研究是编排层（消费多源搜索 + 结构化管道 + 交叉验证合并），交叉验证是增强层（为深度研究提供自动合并能力，并为信源可信度提供回流路径）。本设计将三者作为整体规划，避免分别推进时的接口不一致。

**多源的核心理念**：多源不是"同一个引擎多查几次"，而是**让不同引擎发挥各自擅长的领域**——Tavily 擅长通用网页与官方公报、Exa 擅长语义检索与学术/技术文档、博查擅长中文资讯与国内政策、AnySearch 擅长垂直领域结构化数据与并行批量检索。同一事实从多个领域的引擎分别获取，再由交叉验证做**多源真实性投票**，并基于时态数据（同一事实在不同时间点的多源快照）**推理趋势演变方向**。这是本设计的核心主线，贯穿三功能。

## 现状关键缺口（基于 2026-08-07 代码盘点）

### 交叉验证

| 能力 | 位置 | 状态 |
| :--- | :--- | :--- |
| Relationship 级冲突检测 + 裁决 | `backend/app/services/cross_validation.py` | ✓ L1 完整 |
| Beta 信誉回流 + `ConflictResolution` 审计 | `cross_validation.py:103-240`、`source_reputation.py` | ✓ L1 完整 |
| Review Inbox 集成 + 前端冲突 Tab | `api/review.py:60`、`frontend/components/review/conflicts-tab.tsx` | ✓ L1 完整 |
| Agent 工具 `list_conflicts`/`resolve_conflict` | `services/advisor/tools.py:1870-1895` | ✓ L1 完整 |
| `Assertion` 时态+溯源字段 + `ix_assertions_temporal` 索引 | `models/event.py:184-219`、迁移 `l5e6f7a8b9c0` | ✓ 完备 |
| **LangGraph Assertion 级冲突图** | `services/conflict/graph.py` | ✗ **完整实现但从未被调用**（孤儿模块） |
| **结构化管道冲突检测阶段** | `services/structuring.py:230-366` | ✗ 写完 Assertion/Relationship 后不触发任何冲突检查 |
| **LLM Prompt `conflicts_with` 字段持久化** | `structuring.py:84` vs `:330-348` | ✗ Prompt 要求输出但持久化层直接丢弃 |
| **`Assertion.conflicting_with_id` 字段** | `models/event.py:208` | ✗ 死字段（无读写、无 FK） |
| **Celery 批量冲突扫描任务** | `workers/` | ✗ 无 |
| **`list_conflicts` 缓存** | `cross_validation.py:99-101` | ✗ 每次 `/review/inbox` 全表重算 |
| **两套冲突系统桥接** | `services/cross_validation.py` vs `services/conflict/` | ✗ 检测对象、判据、产物完全独立 |

### 多源搜索引擎

| 能力 | 位置 | 状态 |
| :--- | :--- | :--- |
| Tavily search/extract/crawl | `services/crawler.py:24-26,48,61,122,186` | ✓ 但类名直绑、URL 写死 |
| `web_search`/`web_fetch` 工具 | `services/advisor/tools.py:252-262,438-483` | ✓ 无 `engine` 参数 |
| Tavily key 三层配置（env/app_config/user_service_configs） | `core/config.py:70`、`models/llm_config.py:87-104`、`models/user_runtime.py:26` | ✓ 仅 tavily |
| Settings admin 端点 | `api/settings.py:412-415,477-482` | ✓ 仅 `/settings/tavily` |
| **`SearchEngine` 抽象层** | — | ✗ 无 |
| **exa/博查配置项与代码** | — | ✗ 全仓库零匹配 |
| **搜索结果落库** | `tools.py:438-483` | ✗ 仅返回 markdown 字符串作对话上下文，不写 `InformationSource`/`Event` |
| **多源结果去重与合并** | — | ✗ 前端仅按 URL 正则去重（`ai-elements/sources.tsx:125-140`） |

### 深度研究

| 能力 | 状态 |
| :--- | :--- |
| `deep research`/`multi-step search`/`agentic research` 关键词 | ✗ 全仓库零匹配 |
| 研究任务状态机与持久化 | ✗ `AdvisorState` 仅有 `messages`+`tool_calls` 审计轨迹 |
| 异步研究 Celery 任务 | ✗ 无（`run_scenario_reasoning` 可作长耗时任务模板） |
| 跨源合并工具 | ✗ `list_conflicts` 只检测不合并 |
| 研究原语 Agent 工具 | ✗ 无 `start_research`/`get_research_status` 类工具 |

### 复用基础（已完备）

- **结构化管道** `StructuringService.ingest_text`：任意文本 → 四类原子 → PG + Neo4j 双写 + embedding + 自动 risk_flag + 自动 spawn review branch。是三功能的关键复用基础。
- **Beta 信誉模型** `SourceReputationService`：先验强度 4.0，`record_verdict` 幂等更新。
- **ReAct 循环护栏** `ToolLoopGuard`：128 次工具调用上限、3 次相同调用上限、264 递归。对深度研究够用，但需新增 per-task 预算维度。
- **领域端口**（`docs/specs/2026-07-30-local-storage-foundation.md`）：`BlobStore`/`GraphStore`/`JobRunner`/`VectorStore` 已建立，本地与云端共用服务层逻辑。

## 决策

### 决策 1：交叉验证统一到 Assertion 级

**放弃** Relationship 级冲突检测（`services/cross_validation.py:detect_conflicts` 现有实现），**激活**孤儿 LangGraph 冲突图（`services/conflict/graph.py`），以 `Assertion` 作为唯一冲突载体。

理由：
- `Assertion` 已具备时态（`valid_from`/`valid_to`）+ 溯源（`source_id`/`observed_at`/`source_excerpt`/`content_hash`）+ 索引（`ix_assertions_temporal`），语义远富于 `Relationship`。
- LangGraph 冲突图已实现"检测 → 影响分级 → 自动 spawn Scenario 分支"完整流程，弃用等于浪费。
- Relationship 级 `conflicts_with` 边语义模糊（边与边冲突？实体与实体冲突？），实际使用中前端只能展示"冲突值列表"，无法表达时态版本。
- 统一载体后，结构化管道、Celery 批量扫描、深度研究合并三处触发点共用同一检测逻辑。

**迁移策略**：现有 `CrossValidationService` 重写为 LangGraph 冲突图的薄封装；`ConflictResolution` 审计表与 Beta 信誉回流逻辑保留；前端冲突 Tab 数据结构不变（仍消费 `/review/inbox` 的 `conflicts` 字段），但字段语义从 Relationship 组改为 Assertion 组。

### 决策 2：多源搜索采用"抽象基类 + 引擎实现 + 工厂"

不改动 `CrawlerService` 的公开方法签名（`search`/`extract`/`crawl`），将其重构为 facade，内部按 `engine` 参数分发到 `TavilyEngine`/`ExaEngine`/`BochaEngine`。每个引擎独立实现三个方法，返回统一的 `CrawlResult`/`ExtractResult` 数据类。

**不引入** "搜索引擎路由策略"（如按 query 类型自动选引擎）——默认由用户/管理员配置偏好，Agent 工具调用时显式传 `engine` 参数或传 `None` 走默认。深度研究可在研究计划中指定多引擎并行。

### 决策 3：搜索结果可选落库

`web_search`/`web_fetch` 工具增加 `persist: bool = false` 参数。`persist=true` 时，将搜索结果写入 `InformationSource`（`kind=public`/`news`，`credibility` 由启发式 + 引擎 score 推断），并触发 `StructuringService.ingest_text` 结构化。默认 `false` 保持现有对话上下文行为，避免污染主图谱。

深度研究任务**强制** `persist=true`，所有引用的搜索结果都落库，确保可溯源、可交叉验证、可信誉回流。

### 决策 4：深度研究采用"异步任务 + 状态机 + Agent 工具触发"

不把深度研究塞进单次 ReAct 闭环（会撞上 264 递归上限与 SSE 超时）。设计 `ResearchJob` 状态机 + Celery 长耗时任务，Agent 通过 `start_research` 工具创建任务，通过 `get_research_status`/`poll_research` 工具异步跟进，任务完成后结果回灌 LLM 上下文。

参考 `run_scenario_reasoning`（`workers/tasks.py:244-265`）的异步包装模式。

### 决策 5：交叉验证自动合并与人工裁决分层

- **自动合并**：多源一致事实（同 `subject`+`predicate`+`object_value`，且源可信度均 ≥ medium）自动确认，写 `Assertion.status=confirmed`，不进 Review Inbox。
- **自动存疑**：冲突但低影响（`severity=low`）的，自动 spawn 存疑子分支，不进 Review Inbox。
- **人工裁决**：冲突且 `severity ≥ medium` 或影响 `≥ high` 的，进 Review Inbox，用户裁决后回写 Beta 信誉。

### 决策 6：信源可信度回流路径扩展

当前只有交叉验证裁决一条回流。新增两条：
- **事件审核回流**：用户在 Review Inbox `approve`/`reject` Event 时，调 `SourceReputationService.record_verdict`。
- **预测对比回流**：`EvolutionMilestone.comparison_score` 已有"预测 vs 真实"分数，将其映射为 `record_verdict` 证据（预测命中=confirmed，偏离超阈值=refuted）。

### 决策 7：AgentTeam 作为可选编排层，不替换单 Agent

AgentTeam 是"主代理（Orchestrator）+ 多个子代理（Specialist）"的**可选编排层**，用于处理需要多视角、多领域、可并行拆解的复杂课题。**不替换**现有单 ReAct Agent（`advisor/graph.py`）——简单任务仍走单 Agent + 工具循环，AgentTeam 仅在任务复杂度超过阈值（如子问题数 ≥ 3、需跨 ≥ 2 个领域引擎、需独立验证）时由主 Agent 或用户显式启用。

理由：
- 单 Agent 在 128 次工具调用预算内能处理大多数日常咨询，强行多代理会徒增编排开销与 LLM 成本。
- 但深度研究、跨领域交叉验证、多方案对比推演这类任务，单 Agent 上下文窗口会被工具结果撑爆，且同一上下文里的"先入为主"会削弱交叉验证的独立性——子代理各自有独立上下文，能真正独立验证。
- AgentTeam 复用 Part A/B/C 的能力（SearchEngine、CrossValidationService、StructuringService），不重复造轮子。

**编排模式**采用 LangGraph 的 `Send` API 实现 fan-out / map-reduce，子代理本身是裁剪工具集的简化 ReAct 子图。

## 目标

- **交叉验证**：从 L1 升到 L2。统一到 Assertion 级，结构化管道自动触发冲突检测，Celery 每日批量扫描，自动合并/存疑/裁决分层，缓存冲突列表。
- **多源搜索引擎**：从 L0 升到 L2。抽象 `SearchEngine` 接口，实现 Tavily/Exa/博查/AnySearch 四引擎，配置点扩展到 admin UI 与用户个人配置，搜索结果可选落库。
- **深度研究**：从 L0 升到 L1-L2。`ResearchJob` 状态机 + Celery 长耗时任务 + 3 个 Agent 工具，支持多轮多源搜索 + 抓取 + 结构化 + 交叉验证合并 + 综合报告。
- **AgentTeam**：从 L0 升到 L1-L2。主代理 + 多子代理编排层，复用前三功能，处理跨领域、需独立验证、可并行拆解的复杂课题。
- **信源可信度**：回流路径从 1 条扩展到 3 条，冷启动期仍依赖启发式但明确标注。

## 非目标

- **不实现** 搜索引擎自动路由策略（按 query 类型选引擎）。
- **不实现** AgentTeam 的"全自动任务拆解"——主代理拆解子任务时需遵循预定义的"团队模板"（如"跨领域研究模板""多方案对比模板"），不允许主代理自由发挥创造任意子代理角色，避免不可控。
- **不实现** 子代理之间的实时通信/协商。子代理独立运行，互不感知，仅通过主代理汇总。需要协商的复杂任务不适用 AgentTeam。
- **不实现** 研究结果的"自动知识图谱合并"（研究结果落库为 Assertion/Event，但不自动合并到主图谱主分支，仍走 Review Inbox 或 Scenario 分支）。
- **不实现** 跨用户的研究结果共享或研究模板市场。
- **不重构** `StructuringService` 核心管道，仅在其末尾追加冲突检测阶段。
- **不实现** 关系级冲突检测到 Assertion 级的"数据迁移脚本"——现有 `Relationship(type=conflicts_with)` 边保留但不再新生成，自然衰减。
- **不承诺** 深度研究/AgentTeam 结论的可信度。所有结论必须标注"基于 N 个信源，M 个一致，K 个冲突，未经独立验证"。
- **不引入** exa/博查/AnySearch 的 Python SDK 依赖，直接 HTTP 调用（与 Tavily 现有实现风格一致）。
- **不替换** 现有单 ReAct Agent。AgentTeam 是可选编排层，简单任务仍走单 Agent。

## 设计 Part A：多源搜索引擎抽象层

### A.1 `SearchEngine` 抽象基类

新增 `backend/app/services/search_engines/` 目录：

```text
search_engines/
  __init__.py            # 导出 get_engine(engine_name) 工厂
  base.py                # SearchEngine 抽象基类 + 统一数据类 + DomainHint
  tavily_engine.py       # 复用现有 CrawlerService 的 Tavily 调用逻辑
  exa_engine.py          # Exa API 实现（语义检索/学术技术）
  bocha_engine.py        # 博查 API 实现（中文资讯/国内政策）
  anysearch_engine.py    # AnySearch API 实现（垂直领域/并行批量）
  domain_router.py       # 领域适配策略：按 query 领域推荐引擎组合
```

`base.py` 定义：

```python
@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float               # 0..1，引擎原始相关性分数
    published_at: datetime | None
    engine: str                # "tavily" | "exa" | "bocha"

@dataclass
class ExtractedPage:
    url: str
    content: str               # markdown
    title: str | None
    failed: bool
    error: str | None
    engine: str

class SearchEngine(ABC):
    name: str

    @abstractmethod
    async def search(
        self, query: str, *, max_results: int = 10,
        topic: str = "general", region: str | None = None,
        days: int | None = None,
    ) -> list[SearchHit]: ...

    @abstractmethod
    async def extract(
        self, urls: list[str], *, query: str | None = None,
        extract_depth: str = "basic",
    ) -> list[ExtractedPage]: ...

    @abstractmethod
    async def crawl(
        self, base_url: str, *, max_depth: int = 2,
        max_breadth: int = 20, limit: int = 50,
    ) -> list[ExtractedPage]: ...
```

**统一数据类** `SearchHit`/`ExtractedPage` 替代现有 `CrawlResult`/`ExtractResult`（`crawler.py:28-44`），新增 `engine` 字段。`CrawlerService` 改为 facade：

```python
class CrawlerService:
    def __init__(self, api_key: str | None = None, engine: str | None = None):
        self._engine = get_engine(engine or get_default_search_engine())

    async def search(self, query, **kw) -> list[CrawlResult]:
        hits = await self._engine.search(query, **kw)
        return [self._hit_to_result(h) for h in hits]
    # extract / crawl 同理
```

**兼容性**：`CrawlerService` 公开方法签名不变，现有调用方（`advisor/tools.py`、`api/crawler.py`、`workers/tasks.py`、`source_discovery.py`）零改动。新增 `engine` 参数有默认值，向后兼容。

### A.2 四引擎实现要点与领域适配

| 引擎 | 端点 | 认证 | 擅长领域 | 关键差异 |
| :--- | :--- | :--- | :--- | :--- |
| Tavily | `api.tavily.com/search`、`/extract`、`/crawl` | Bearer token | 通用网页、官方公报、新闻聚合 | 现有实现原样迁移到 `tavily_engine.py`；`crawl` 支持图遍历多页 |
| Exa | `api.exa.ai/search`、`/contents`、`/findSimilar` | `x-api-key` header | 语义检索、学术/技术文档、研究论文 | `search` 返回 `results[]` 含 `score`、`publishedDate`；支持 `category` 参数（research paper / tweet / linkedin 等）；`extract` 用 `/contents` 接口 |
| 博查 | `api.bochaai.com/v1/web-search` | `Authorization: Bearer` | 中文资讯、国内政策、国内论坛 | 返回 `data.webPages.value[]`，含 `score`、`datePublished`；无独立 extract/crawl，降级处理 |
| AnySearch | `api.anysearch.com/v1/search`、`/batch_search`、`/extract` | `Authorization: Bearer as_sk_xxx` | 垂直领域结构化数据、并行批量检索 | 原生 `domain`/`sub_domain` 垂直领域参数；`batch_search` 一次提交多个 query 并行返回；`extract` 返回 Markdown；支持匿名访问（限流更严） |

**博查 extract 降级策略**：博查无原生 extract API，`BochaEngine.extract` 先尝试 `TavilyEngine.extract`（若用户配置了 Tavily key），否则跳过该 URL 并在 `ExtractedPage.error` 标注 `"bocha extract unsupported, tavily not configured"`。`crawl` 同理降级为多次 `search`。

**AnySearch 垂直领域映射**：`AnySearchEngine` 暴露 `domain`/`sub_domain` 参数（来自 `shared/constants.json`，含政策、学术、新闻、金融等垂域列表）。`SearchEngine.search` 基类方法新增可选 `domain: str | None` 参数，仅 `AnySearchEngine` 实际消费，其他引擎忽略。调用方（深度研究 planner、Agent 工具）可按 query 主题传入 domain，命中垂直结构化数据。

**AnySearch batch_search 复用**：深度研究的 `searcher` 对多子问题并行检索时，优先用 `AnySearchEngine.batch_search`（单次 HTTP 并行返回），其他引擎仍各自单次调用后合并。

### A.3 配置点扩展

| 层 | 文件 | 新增字段 |
| :--- | :--- | :--- |
| env 兜底 | `core/config.py` | `exa_api_key`、`bocha_api_key`、`anysearch_api_key`、`search_default_engine`（默认 `"tavily"`） |
| 全局 DB | `AppConfig` 表 | `exa_api_key`、`bocha_api_key`、`anysearch_api_key`、`search_default_engine`、`search_engines_enabled`（JSON list，如 `["tavily","exa","bocha","anysearch"]`） |
| Per-user DB | `user_service_configs` | `exa_api_key`、`bocha_api_key`、`anysearch_api_key`、`search_default_engine`（用户可覆盖全局） |
| Registry | `llm/registry.py` | `get_exa_key`/`set_exa_key`/`get_bocha_key`/`set_bocha_key`/`get_anysearch_key`/`set_anysearch_key`/`get_search_default_engine`/`set_search_default_engine` |

`registry.py` 现有 `get_tavily_key`（行 1338-1339）模式作为模板，新增函数遵循相同读写模式（`_KEY_EXA = "exa_api_key"`、`_KEY_BOCHA = "bocha_api_key"`、`_KEY_ANYSEARCH = "anysearch_api_key"`、`_KEY_SEARCH_DEFAULT = "search_default_engine"`）。

### A.4 Settings API 扩展

`api/settings.py` 新增端点（与现有 `/settings/tavily` 风格一致）：

| 方法 | 路径 | 用途 |
| :--- | :--- | :--- |
| PUT | `/settings/exa` | 设置全局 Exa key（admin only） |
| GET | `/settings/exa/key` | 返回完整 key（admin only） |
| PUT | `/settings/bocha` | 设置全局博查 key |
| GET | `/settings/bocha/key` | 返回完整 key |
| PUT | `/settings/anysearch` | 设置全局 AnySearch key |
| GET | `/settings/anysearch/key` | 返回完整 key |
| GET/PUT | `/settings/search-engine` | 查询/设置默认引擎与启用列表 |

`_restricted_view`（`settings.py:177-201`）扩展：多用户模式下非 admin 看到的配置预览增加 `exa_api_key_configured`、`bocha_api_key_configured`、`anysearch_api_key_configured`、`search_default_engine` 字段。

### A.5 Advisor 工具扩展

`WebSearchInput`（`tools.py:252-256`）新增字段：

```python
class WebSearchInput(BaseModel):
    query: str
    max_results: int = 5  # 最大 10
    engine: Literal["tavily", "exa", "bocha", "anysearch"] | None = None  # None 走默认
    engines: list[Literal["tavily", "exa", "bocha", "anysearch"]] | None = None  # 多引擎并行（用于交叉验证）
    domain: str | None = None  # 垂直领域（AnySearch 消费，如 "policy"/"academic"/"news"）
    persist: bool = False  # 是否落库为 InformationSource + 结构化
```

`WebFetchInput` 同理新增 `engine`、`persist`。

**多引擎并行**：当 `engines` 传入多个引擎时，`_web_search` 并发调用各引擎的 `search`，合并结果（按 `score` 归一化排序），去重（按 URL），返回合并后的 markdown 列表。每条结果标注 `engine` 来源，便于后续交叉验证识别"该事实来自哪些引擎"。

`_web_search`（`tools.py:438-460`）改造：
1. 从 `UserServiceConfig` 读取 per-user engine 偏好与对应 key（若 `engine=None`）。
2. 调 `CrawlerService(api_key, engine).search(...)`。
3. 若 `persist=True`：对每个 hit 创建 `InformationSource(kind="public"/"news"`，`credibility` 由 `score` 推断：`score≥0.8→medium`、`score≥0.5→low`、`<0.5→pending`），调 `StructuringService.ingest_text` 结构化 snippet。
4. 返回格式保持 markdown 字符串（前端 `parseSearchSources` 无需改动），追加 `persisted_count` 元信息。

### A.6 前端扩展

- `frontend/components/settings/platform-config.tsx`：admin 配置卡新增 Exa、博查、AnySearch key 输入项与默认引擎下拉，并展示每个引擎的擅长领域提示。
- `frontend/components/settings/personal-service-keys.tsx`：用户个人配置卡新增 Exa、博查、AnySearch key（per-user 覆盖）。
- `frontend/lib/api.ts`：新增 `setExaKey`/`getExaKey`/`setBochaKey`/`getBochaKey`/`setAnysearchKey`/`getAnysearchKey`/`getSearchEngineConfig`/`setSearchEngineConfig` 函数（行 807、911 附近）。
- `frontend/components/chat/chat-panel.tsx`：webSearch 开关旁新增引擎选择下拉（可选单引擎或多引擎并行，默认走配置偏好）。

### A.7 领域适配与多源协同策略（核心主线）

本节阐述"多源"的真正含义：不是同引擎多查，而是**跨引擎领域互补 + 真实性投票 + 趋势推理**。

#### 引擎领域画像

每个引擎在 `SearchEngine` 基类中声明 `domain_strengths: list[str]`，用于领域路由与 UI 提示：

| 引擎 | domain_strengths | 典型场景 |
| :--- | :--- | :--- |
| Tavily | `general`、`official`、`news` | 加拿大 IRCC 官方公报、英文新闻聚合 |
| Exa | `academic`、`semantic`、`technical` | 学术论文、技术文档、语义相似检索 |
| 博查 | `chinese_news`、`china_policy`、`forum` | 国内移民中介资讯、中文政策解读、论坛讨论 |
| AnySearch | `vertical`、`structured`、`batch` | 垂直领域结构化数据（金融/政策/学术）、多子问题并行检索 |

#### `domain_router` 领域推荐

`search_engines/domain_router.py` 提供 `recommend_engines(query, scope) -> list[str]`：

```python
def recommend_engines(query: str, scope: dict | None = None) -> list[str]:
    """按 query 主题推荐引擎组合（仅返回用户已配置 key 的引擎）。

    规则（启发式，可后续替换为 LLM 分类）：
    - query 含中文 + 政策/中介/论坛关键词 → 优先 bocha
    - query 含学术论文/研究/DOI/技术名词 → 优先 exa
    - query 明确属于垂直结构化领域（金融数据/政策条文/学术索引） → 优先 anysearch
    - 默认/官方公报/英文新闻 → tavily
    - 交叉验证场景：返回 2-3 个不同领域引擎，确保覆盖多角度
    """
```

`recommend_engines` **不强制**使用——Agent 工具调用时可显式传 `engines`，未传且 `scope` 含 `cross_validate=true` 时才调 `recommend_engines` 取推荐组合。

#### 真实性投票机制

交叉验证的"多源真实性投票"基于一个关键洞察：**同一事实若被多个独立领域引擎（如官方公报引擎 + 学术引擎 + 中文资讯引擎）一致报道，可信度远高于单一引擎多次返回**。因为不同领域引擎的信息源重叠度低，一致结果更接近独立验证。

`ConflictGroup` 数据结构扩展（在 Part B 详述）增加 `cross_engine_consensus: int` 字段：统计支持某 `object_value` 的**不同引擎数**（而非不同信源数）。投票权重：

```text
vote_weight(source) = source.credibility_score × engine_diversity_bonus
engine_diversity_bonus = 1.0 + 0.2 × (该值被多少个不同引擎支持)
```

- 单引擎 3 个信源一致：`engine_diversity_bonus = 1.2`（同引擎信源可能同源转载）
- 3 个不同引擎各 1 个信源一致：`engine_diversity_bonus = 1.6`（跨领域独立验证）

此权重在 `CrossValidationService` 自动合并与 `resolve_conflict` 裁决时使用。

#### 趋势推理机制

基于时态 Assertion（`valid_from`/`valid_to`/`observed_at`）的多源快照，推理事实演变方向：

```text
同一 subject + predicate 的 Assertion 序列（按时序排列）：
  t1: object_value=A  (source: bocha,  observed_at: 2026-03)
  t2: object_value=A  (source: tavily, observed_at: 2026-05)
  t3: object_value=B  (source: exa,    observed_at: 2026-07)
  t4: object_value=B  (source: bocha,  observed_at: 2026-07)
→ 趋势：A→B 转变，3 月起 A，7 月起 B，跨引擎确认转变发生在 5-7 月
```

`CrossValidationService` 新增 `detect_trends(subject, predicate) -> TrendAnalysis`：
- 聚合时态 Assertion 序列。
- 识别"值转变点"（某时刻起多源开始一致报道新值）。
- 输出 `TrendAnalysis{direction: stable|changing|divergent, transition_point: datetime|None, confidence: float}`。
- `direction=changing` 时自动 spawn 一个"趋势推演" Scenario 分支，标记旧值 Assertion `valid_to=transition_point`。

趋势推理结果回灌深度研究的 `synthesizing_node`，报告中体现"该政策金额从 X 趋于 Y，转变发生在 N 月"。

#### 深度研究中的多源协同

深度研究 `planner` 生成研究计划时，对每个子问题标注 `expected_domains`（预期涉及领域），`searcher` 据此调 `domain_router.recommend_engines` 选择引擎组合，确保：
- 事实型子问题（如"加拿大 FSW 配额"）→ 多引擎并行（tavily 官方 + bocha 中文资讯 + anysearch 垂直）做交叉验证
- 学术型子问题（如"语言成绩与移民成功率相关性"）→ exa 为主
- 趋势型子问题（如"近 2 年配额变化"）→ 多引擎按时窗分批检索，喂给趋势推理

`synthesizing_node` 综合报告时，对每个 key_finding 标注 `cross_engine_consensus` 与 `trend`，体现"该发现被 N 个不同领域引擎一致支持"或"该值呈上升趋势"。

## 设计 Part B：交叉验证增强（统一到 Assertion 级）

### B.1 数据模型变更

**启用 `Assertion.conflicting_with_id`**（`models/event.py:208`）：
- 新增 Alembic 迁移：加 FK 约束 `FOREIGN KEY (conflicting_with_id) REFERENCES assertions(id) ON DELETE SET NULL`。
- 字段语义：指向"与本 Assertion 冲突的主 Assertion"（同一 `subject`+`predicate`，不同 `object_value`）。双向引用（A.conflicting_with_id = B，B.conflicting_with_id = A）由检测服务保证。

**废弃 `Relationship(type="conflicts_with")`**：
- 不再新生成此类边。
- 现有边保留，不迁移，自然衰减（随 Relationship 半衰期）。
- `cross_validation.py:184-202` 创建 `conflicts_with` 边的逻辑移除。

**`ConflictResolution` 表扩展**（`models/intelligence.py:134-148`）：
- 新增 `assertion_ids: JSON`（list[str]）：参与冲突的所有 Assertion ID。
- 新增 `winning_assertion_id: str`：胜出 Assertion。
- 新增 `cross_engine_consensus: JSON`：`{"value": object_value, "supporting_engines": ["tavily","exa"], "engine_diversity_bonus": 1.6}`，记录裁决时的跨引擎一致性快照。
- `resolution_key` 语义变更：`{subject}:{predicate}:{object_value_hash}`（基于 Assertion 而非 Relationship）。

**`Assertion` 新增 `engine` 溯源字段**（`models/event.py`）：
- 新增 `engine: str | None`：记录该 Assertion 来自哪个搜索引擎抽取（`tavily`/`exa`/`bocha`/`anysearch`/`user_upload`/`NULL`）。
- 落库时机：`StructuringService.ingest_text` 时从 `InformationSource.meta.engine` 继承（搜索结果落库时写入 meta）。
- 用途：`cross_engine_consensus` 统计与 `engine_diversity_bonus` 计算依赖此字段。

### B.2 `CrossValidationService` 重写

`services/cross_validation.py` 重构为 LangGraph 冲突图的薄封装，保留对外接口（`detect_conflicts`/`list_conflicts`/`resolve_conflict`）：

```python
class CrossValidationService:
    def __init__(self, db: Session, user_id: str):
        self.db = db
        self.user_id = user_id

    async def detect_conflicts(self, goal_id: str | None = None) -> list[ConflictGroup]:
        """调用 run_conflict_detection，返回冲突组。"""
        return await run_conflict_detection(self.db, goal_id)

    def list_conflicts(self, use_cache: bool = True) -> list[ConflictGroup]:
        """带缓存的冲突列表（TTL 5min，Redis key: lifetree:conflicts:{user_id}）。"""
        ...

    def resolve_conflict(self, *, subject_id: str, predicate: str,
                         winning_source_id: str, rationale: str | None) -> ConflictResolution:
        """用户裁决：更新 Beta 信誉 + 写审计 + 标记 Assertion status。"""
        ...
```

**`services/conflict/graph.py` 改造**：
- `detect_conflicts_node`（行 55-107）：现有判据是"claim 文本是否不同"（粗粒度）。改为基于 `object_value` 严格比较 + `valid_to` 时态有效性检查（仅当 `valid_to IS NULL OR valid_to > now` 的 Assertion 参与冲突检测）。
- `classify_impact_node`（行 110-131）：现有 `CONFLICT_CONFIDENCE_DELTA=0.3` 阈值保留，新增"影响范围预演"——调 `RiskPropagationEngine` 假设性传播，若受影响 Goal/Pathway 数 ≥ 2 则升级 severity。
- 新增 `auto_merge_node`：多源一致事实自动确认（决策 5）。合并判据升级为"跨引擎一致性投票"——`cross_engine_consensus ≥ 2`（不同引擎数）且 `engine_diversity_bonus ≥ 1.4` 时自动确认，否则维持 `pending_review`。
- 新增 `trend_analysis_node`：对同一 `subject+predicate` 的时态 Assertion 序列调 `detect_trends`（见 A.7），`direction=changing` 时 spawn 趋势推演 Scenario 分支并标记旧值 `valid_to`。
- `spawn_scenario_branches_node`（行 134-186）：保留，对 `severity ≥ medium` 或 `direction=changing` 触发。

### B.3 结构化管道接入冲突检测

`services/structuring.py:_persist_extraction`（行 230-366）末尾追加：

```python
# 写完 Assertion/Relationship 后触发冲突检测
if extraction.assertions:
    assertion_ids = [a.id for a in persisted_assertions]
    await CrossValidationService(self.db, self.user_id).detect_conflicts_for_assertions(assertion_ids)
```

`detect_conflicts_for_assertions` 是新增方法，限定只扫描新写入的 Assertion 与已有 Assertion 的冲突，避免全表扫描。

**LLM `conflicts_with` 字段处理**（`structuring.py:84`）：
- Prompt 仍要求 LLM 输出 `conflicts_with`（作为 hint）。
- 持久化层读取该字段，若 LLM 标注了冲突，在 `Assertion.conflicting_with_id` 预填指向（需后端校验同 `subject`+`predicate` 才接受）。
- 最终冲突关系以 `detect_conflicts` 的检测结果为准，LLM hint 仅作加速。

### B.4 Celery 批量扫描任务

`workers/intelligence_tasks.py` 新增：

```python
@celery_app.task(name="scan_all_conflicts")
def scan_all_conflicts():
    """每日全量扫描所有用户的 Assertion 冲突，刷新缓存。"""
    # 遍历有活跃 Assertion 的 user
    # 对每个 user 调 CrossValidationService.detect_conflicts()
    # 结果写入 Redis 缓存（TTL 24h）
    # severity >= medium 的进 Review Inbox（通过现有 notification 链路）
```

Celery beat 注册（`celery_app.py:34-91`）：每日 04:30 执行（避开 03:00 graph_health_check 与 05:15 discover_emerging_risks）。

### B.5 缓存策略

- `list_conflicts` 结果缓存到 Redis，key `lifetree:conflicts:{user_id}`，TTL 5min。
- 缓存失效条件：新 Assertion 写入、用户裁决、`scan_all_conflicts` 任务完成。
- `/review/inbox` 请求优先读缓存，未命中调 `detect_conflicts` 并回填。

### B.6 Review Inbox 与前端适配

`api/review.py:60` 调用改为 `CrossValidationService.list_conflicts(use_cache=True)`。

`ReviewConflict` 类型（`frontend/lib/api.ts:1160`）字段语义变更：
- `conflicting_values` 改为引用 `Assertion.object_value` + `source_id` + `observed_at` + `confidence`。
- 新增 `valid_from`/`valid_to` 展示时态版本。
- 新增 `severity` 字段（low/medium/high）。

`frontend/components/review/conflicts-tab.tsx` 增强：
- 冲突卡片展示时态版本（`valid_from`~`valid_to`）。
- `severity=high` 的冲突置顶 + 高亮。
- 裁决按钮旁新增"查看原文摘录"（`source_excerpt`）。

### B.7 信源可信度回流扩展

**事件审核回流**（`api/review.py` 的 `approve`/`reject` Event 端点）：
- `approve` → `SourceReputationService.record_verdict(event.source, evidence_key=event.id, confirmed=True)`。
- `reject` → `record_verdict(..., confirmed=False)`。

**预测对比回流**（`workers/intelligence_tasks.py:compare_evolution_milestones`）：
- 现有任务已计算 `comparison_score`（`intelligence.py:81`）。
- 新增逻辑：对 `comparison_score` 偏离阈值（如 Brier > 0.3）的 milestone，找到其关联的 `ScenarioRun` 输入 Assertion，对每个 Assertion 的 source 调 `record_verdict(..., confirmed=comparison_score < threshold)`。
- 阈值与映射规则写入 `model_params` 表，避免硬编码（遵循缺口 G 的参数外置原则）。

## 设计 Part C：深度研究

### C.1 `ResearchJob` 状态机

新增 `backend/app/models/research.py`：

```python
class ResearchStatus(str, Enum):
    PLANNING = "planning"        # LLM 生成研究计划
    SEARCHING = "searching"      # 多源搜索中
    EXTRACTING = "extracting"    # 抓取全文中
    STRUCTURING = "structuring"  # 结构化抽取中
    VALIDATING = "validating"    # 交叉验证合并中
    SYNTHESIZING = "synthesizing"  # 生成综合报告中
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ResearchJob(Base):
    __tablename__ = "research_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"), index=True)
    question: Mapped[str] = mapped_column(Text)              # 研究问题
    scope: Mapped[dict] = mapped_column(JSON)                # {goal_id, pathway_id, region, time_range}
    plan: Mapped[dict | None] = mapped_column(JSON)          # LLM 生成的研究计划
    engines: Mapped[list] = mapped_column(JSON)              # ["tavily", "exa", "bocha"]
    status: Mapped[str] = mapped_column(String(32), default="planning")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    current_step: Mapped[str | None] = mapped_column(String(128))
    source_ids: Mapped[list] = mapped_column(JSON, default=list)  # 收集的 InformationSource IDs
    assertion_ids: Mapped[list] = mapped_column(JSON, default=list)
    conflict_ids: Mapped[list] = mapped_column(JSON, default=list)
    report: Mapped[dict | None] = mapped_column(JSON)        # 最终综合报告
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

Alembic 迁移新增 `research_jobs` 表。

### C.2 研究流程（Celery 任务）

新增 `backend/app/services/research/` 目录：

```text
research/
  __init__.py
  planner.py          # LLM 生成研究计划
  searcher.py         # 多源搜索执行器
  extractor.py        # URL 批量抓取
  synthesizer.py      # 综合报告生成
  graph.py            # LangGraph 编排：planning → searching → extracting → structuring → validating → synthesizing
  state.py            # ResearchState TypedDict
```

`ResearchState`（LangGraph 状态）：

```python
class ResearchState(TypedDict, total=False):
    job_id: str
    question: str
    scope: dict
    plan: dict                  # {sub_questions: [{q, engines, max_sources}]}
    sub_query_results: list     # 每个 sub_query 的 SearchHit 列表
    extracted_pages: list       # ExtractedPage 列表
    structured_atoms: dict      # {events: [], assertions: [], relationships: []}
    conflict_groups: list
    report: dict
    error: str | None
```

**LangGraph 编排**（`research/graph.py`）：

```text
planning_node
    ↓
searching_node  ← 循环每个 sub_question
    ↓
extracting_node ← 批量抓取 top-N URL（按 score 排序）
    ↓
structuring_node ← 调 StructuringService.ingest_text（persist=true）
    ↓
validating_node ← 调 CrossValidationService.detect_conflicts
    ↓
synthesizing_node ← LLM 生成综合报告
    ↓
finalize_node ← 写回 ResearchJob.report，状态 COMPLETED
```

每个节点更新 `ResearchJob.status`、`progress`、`current_step`，通过 Redis pub/sub 推送进度（复用 `lifetree:research:{job_id}` channel，前端通过现有 SSE 端点订阅）。

**预算控制**：
- `max_sub_questions: int = 5`（研究计划拆分的子问题数上限）
- `max_total_sources: int = 30`（收集的 URL 总数上限）
- `max_extract_chars: int = 50000`（总抓取字符数上限）
- `max_llm_calls: int = 20`（LLM 调用总次数上限，含规划 + 结构化 + 综合）
- 每个上限可在 `ResearchJob.scope` 中由调用方覆盖，但不超过全局最大值。

### C.3 综合报告结构

`ResearchJob.report` JSON 结构：

```json
{
  "summary": "研究结论摘要（2-3 段）",
  "key_findings": [
    {
      "finding": "发现陈述",
      "supporting_assertions": ["assertion_id_1", "assertion_id_2"],
      "conflicting_assertions": ["assertion_id_3"],
      "confidence": "high | medium | low",
      "cross_engine_consensus": 3,
      "trend": "stable | changing | divergent | null",
      "trend_detail": "该值从 X 趋于 Y，转变发生在 2026-05 至 2026-07",
      "caveats": "本发现基于 N 个信源（来自 M 个不同领域引擎），K 个一致，L 个冲突"
    }
  ],
  "conflicts": [
    {
      "subject": "...", "predicate": "...",
      "values": [{"value": "...", "source_id": "...", "engine": "...", "credibility": "..."}],
      "severity": "low | medium | high",
      "cross_engine_consensus": {"value": "...", "supporting_engines": ["tavily","exa"], "engine_diversity_bonus": 1.6},
      "resolution": "auto_merged | pending_review | user_resolved"
    }
  ],
  "trends": [
    {
      "subject": "...", "predicate": "...",
      "direction": "changing",
      "transition_point": "2026-06-01",
      "timeline": [{"value": "A", "observed_at": "2026-03", "engines": ["bocha"]}, {"value": "B", "observed_at": "2026-07", "engines": ["exa","bocha"]}],
      "confidence": 0.78
    }
  ],
  "sources": [
    {"source_id": "...", "title": "...", "url": "...", "engine": "...", "credibility_score": 0.72}
  ],
  "research_metadata": {
    "engines_used": ["tavily", "exa", "bocha", "anysearch"],
    "engine_domain_coverage": {"official": true, "academic": true, "chinese_news": true, "vertical": true},
    "total_sources_collected": 23,
    "total_assertions_extracted": 47,
    "total_conflicts_detected": 4,
    "total_trends_detected": 2,
    "duration_seconds": 187,
    "honesty_disclaimer": "本研究结论基于公开信源自动聚合，未经独立验证，仅供参考。"
  }
}
```

**诚实标注**（遵循 §11.6 产品护栏）：
- `confidence` 必须基于"一致信源数 vs 冲突信源数 + 跨引擎一致性"计算，不能由 LLM 主观填写。
- `cross_engine_consensus` 由后端统计，体现"该发现被 N 个不同领域引擎一致支持"。
- `trend` 由 `detect_trends` 计算，非 LLM 推断；`trend_detail` 由 LLM 基于后端给定的转变点描述。
- `honesty_disclaimer` 强制写入所有报告。
- 若 `total_sources_collected < 3` 或 `total_conflicts_detected > total_assertions_extracted * 0.3`，`summary` 必须包含"证据不足"或"信源高度冲突"警告。
- 若 `engine_domain_coverage` 仅覆盖单一领域（如只有 `chinese_news`），`summary` 必须包含"仅基于单一领域信源，缺乏跨领域交叉验证"警告。

### C.4 Agent 工具

新增 3 个工具（`services/advisor/tools.py`）：

```python
class StartResearchInput(BaseModel):
    question: str
    scope: dict = {}           # {goal_id?, pathway_id?, region?, time_range?}
    engines: list[str] | None = None  # None 走默认启用列表
    max_sub_questions: int = 5
    max_total_sources: int = 30

class ResearchStatusInput(BaseModel):
    job_id: str

class PollResearchInput(BaseModel):
    job_id: str
    timeout_seconds: int = 60  # 最长等待
```

**`start_research`**：创建 `ResearchJob`（status=planning），触发 Celery 任务 `run_research_job.delay(job_id)`，返回 `{"job_id": "...", "status": "planning"}`。LLM 拿到 job_id 后可在后续轮次查询。

**`get_research_status`**：读 `ResearchJob` 表，返回 `status`/`progress`/`current_step`/`error`。若 `status=completed`，返回完整 `report`。

**`poll_research`**：阻塞等待（最长 `timeout_seconds`），期间通过 Redis pub/sub 监听 `lifetree:research:{job_id}` channel。完成或超时返回当前状态。用于 LLM 在单轮对话内同步等待研究完成（适合短研究，长研究建议 LLM 主动调 `get_research_status` 多轮跟进）。

工具注册到 `build_advisor_tools`（`tools.py:2374-2435`），始终可用（不条件注入）。

### C.5 Celery 任务

`workers/research_tasks.py` 新增：

```python
@celery_app.task(name="run_research_job", soft_time_limit=600, time_limit=660)
def run_research_job(job_id: str):
    """执行深度研究任务。软超时 10 分钟，硬超时 11 分钟。"""
    # 加载 ResearchJob
    # 构建 LangGraph research graph
    # 流式执行，每个节点完成后更新 DB + 推送 SSE
    # 异常时 status=failed，写 error
```

软超时触发时，任务尝试将 `status` 置为 `failed` 并写 `error="soft time limit exceeded"`。

Celery beat **不**注册定时触发（研究任务由用户/Agent 按需启动）。

### C.6 前端

- `frontend/app/research/page.tsx`：研究任务列表页（新建路由）。
- `frontend/components/research/research-launcher.tsx`：研究问题输入框 + scope 选择 + 引擎选择 + 提交按钮。
- `frontend/components/research/research-progress.tsx`：进度展示（状态机可视化 + 进度条 + 当前步骤）。
- `frontend/components/research/research-report.tsx`：综合报告渲染（key_findings 卡片 + conflicts 表 + sources 列表 + honesty_disclaimer 高亮）。
- `frontend/lib/api.ts`：新增 `startResearch`/`getResearchStatus`/`listResearchJobs` 函数。
- 侧边栏 `frontend/components/layout/sidebar.tsx` 新增"深度研究"入口。

**与聊天集成**：`chat-panel.tsx` 解析 assistant 消息中的 `start_research`/`get_research_status` toolCalls，渲染为可点击的研究进度卡片，点击跳转 `/research/{job_id}`。

## 设计 Part D：AgentTeam 编排层

### D.1 架构概览

AgentTeam 采用"主代理（Orchestrator）+ 子代理（Specialist）"两层结构，基于 LangGraph 的 `Send` API 实现 fan-out / map-reduce 编排：

```text
用户/主 Agent 发起 AgentTeam 任务
        ↓
┌─────────────────────────────────┐
│  Orchestrator（主代理）          │
│  - 按团队模板拆解子任务          │
│  - 分配子代理角色 + 工具集 + 预算│
│  - 汇总子代理结果                │
│  - 可选：审查缺口 → 追加子代理   │
└─────────────────────────────────┘
        ↓ Send API fan-out（并行）
┌──────────┬──────────┬──────────┬──────────┐
│Specialist│Specialist│Specialist│Specialist│
│ 引擎A+域 │ 引擎B+域 │ 验证视角1│ 验证视角2│
│ 独立上下文│ 独立上下文│ 独立上下文│ 独立上下文│
│ 裁剪工具 │ 裁剪工具 │ 裁剪工具 │ 裁剪工具 │
└──────────┴──────────┴──────────┴──────────┘
        ↓ fan-in（汇总）
┌─────────────────────────────────┐
│  Orchestrator 汇总 + 综合       │
│  - 合并结果 / 识别分歧          │
│  - 调 CrossValidationService    │
│  - 生成最终输出                 │
└─────────────────────────────────┘
```

**关键设计**：
- **子代理独立上下文**：每个子代理有独立的 `messages` 列表，不共享主代理的历史，避免上下文污染与确认偏误。这是 AgentTeam 相对单 Agent 多次调工具的核心优势——交叉验证的独立性由此保证。
- **子代理工具集裁剪**：按角色只注入相关工具（如 ResearchSpecialist 只给 `web_search(指定 engine)` + `ingest_url` + `global_search`），降低工具选择复杂度。
- **子代理预算更小**：每个子代理 `max_tool_calls=20`（远小于主 Agent 的 128），强制聚焦。
- **复用前三功能**：子代理调用的底层能力仍是 Part A 的 `SearchEngine`、Part B 的 `CrossValidationService`、`StructuringService`，不重复实现。

### D.2 `AgentTeamJob` 状态机与模型

新增 `backend/app/models/agent_team.py`：

```python
class TeamStatus(str, Enum):
    DECOMPOSING = "decomposing"      # 主代理拆解子任务
    DISPATCHING = "dispatching"      # 分配子代理
    RUNNING = "running"              # 子代理并行执行
    AGGREGATING = "aggregating"      # 主代理汇总
    REVIEWING = "reviewing"          # 审查缺口，决定是否追加
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AgentTeamJob(Base):
    __tablename__ = "agent_team_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("user_profiles.id"), index=True)
    template: Mapped[str] = mapped_column(String(64))      # 团队模板标识
    objective: Mapped[str] = mapped_column(Text)            # 总目标
    scope: Mapped[dict] = mapped_column(JSON)               # {goal_id, engines, domains, ...}
    subtasks: Mapped[list] = mapped_column(JSON)            # 主代理拆解的子任务列表
    specialist_results: Mapped[list] = mapped_column(JSON, default=list)  # 各子代理结果
    status: Mapped[str] = mapped_column(String(32), default="decomposing")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_step: Mapped[str | None] = mapped_column(String(128))
    final_output: Mapped[dict | None] = mapped_column(JSON)
    iterations: Mapped[int] = mapped_column(Integer, default=0)  # fan-out 轮次（REVIEWING 可追加）
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**与 `ResearchJob` 的关系**：AgentTeam 是更通用的编排层，深度研究（Part C）可视为 AgentTeam 的一个团队模板（`cross_domain_research`）。实现上 `ResearchJob` 的固定管线处理简单研究，`AgentTeamJob` 处理需要多代理协作的复杂研究；两者并存，由 `start_research` 工具的 `use_team: bool` 参数选择。

### D.3 子代理角色与工具集裁剪

| 角色 | 职责 | 注入工具 | 预算 |
| :--- | :--- | :--- | :--- |
| `ResearchSpecialist` | 绑定引擎+领域，检索+抓取+结构化 | `web_search(engine=X, domain=Y)`、`web_fetch`、`ingest_url`、`global_search` | max_tool_calls=20 |
| `ValidationSpecialist` | 从特定角度独立验证给定事实 | `web_search`、`web_fetch`、`list_assertions`、`get_source_credibility` | max_tool_calls=15 |
| `SynthesisSpecialist` | 综合多个子代理结果为结构化输出 | `global_search`、`list_assertions`、`list_conflicts`、`detect_trends` | max_tool_calls=10 |
| `DomainAnalyst` | 特定领域（政策/经济/安全）深度分析 | `web_search`、`ingest_url`、`list_pathways`、`list_risk_factors`、`discover_risks` | max_tool_calls=20 |
| `ScenarioExplorer` | 推演特定 Pathway/Scenario 的演变 | `run_scenario_reasoning`、`compare_scenarios`、`list_decision_tree` | max_tool_calls=10 |

子代理工具集在 `backend/app/services/agent_team/roles.py` 中定义，主代理按团队模板选择角色组合。

### D.4 团队模板（预定义编排模式）

团队模板是决策 7 的"非全自动拆解"约束的落地——主代理只能在模板框架内拆解，不能创造任意角色。

| 模板标识 | 适用场景 | 子代理组合 | 编排模式 |
| :--- | :--- | :--- | :--- |
| `cross_domain_research` | 跨领域深度研究 | N×ResearchSpecialist（不同引擎+领域）+ 1×SynthesisSpecialist | fan-out → fan-in |
| `independent_validation` | 关键事实独立验证 | N×ValidationSpecialist（不同角度/引擎）+ 1×SynthesisSpecialist | fan-out → fan-in |
| `multi_pathway_compare` | 多方案对比推演 | N×ScenarioExplorer（不同 Pathway）+ 1×SynthesisSpecialist | fan-out → fan-in |
| `risk_scan` | 多维度风险扫描 | N×DomainAnalyst（政策/经济/安全/安全） | fan-out → fan-in |
| `iterative_research` | 迭代式研究（发现缺口再补） | ResearchSpecialist 轮 + SynthesisSpecialist 审查 | fan-out → REVIEWING → 追加 fan-out（≤2 轮） |

模板定义在 `backend/app/services/agent_team/templates.py`，包含：角色组合、子任务拆解提示词、汇总提示词、最大迭代轮次。

### D.5 编排流程（Celery + LangGraph）

新增 `backend/app/services/agent_team/` 目录：

```text
agent_team/
  __init__.py
  roles.py              # 子代理角色定义 + 工具集裁剪
  templates.py          # 团队模板
  orchestrator.py       # 主代理：拆解/分配/汇总/审查
  specialist_graph.py   # 子代理子图（简化 ReAct）
  graph.py              # AgentTeam LangGraph 编排（Send API fan-out）
  state.py              # TeamState
```

`TeamState`（LangGraph 状态）：

```python
class TeamState(TypedDict, total=False):
    job_id: str
    objective: str
    scope: dict
    template: str
    subtasks: list[dict]          # [{role, instruction, engine, domain, budget}]
    specialist_results: list[dict]  # [{subtask_id, role, output, atoms, sources}]
    aggregated: dict | None
    review_gaps: list[dict]       # 审查发现的缺口
    iteration: int
    final_output: dict | None
    error: str | None
```

**LangGraph 编排**（`graph.py`）：

```text
decompose_node（主代理按模板拆解）
    ↓
dispatch_node（分配子代理，Send API fan-out）
    ↓ 并行
specialist_node × N（各子代理独立 ReAct 子图）
    ↓ fan-in
aggregate_node（主代理汇总）
    ↓
review_node（条件：模板允许迭代且有缺口）
    ↓ 有缺口              ↓ 无缺口
回到 dispatch_node      finalize_node（写 final_output，COMPLETED）
```

每个节点更新 `AgentTeamJob.status`/`progress`/`current_step`，通过 Redis pub/sub 推送进度（channel `lifetree:agent_team:{job_id}`）。

### D.6 预算与护栏

| 维度 | 限制 | 说明 |
| :--- | :--- | :--- |
| 子代理工具调用 | 每个 ≤ 20 | 远小于主 Agent 的 128 |
| 子代理 LLM 调用 | 每个 ≤ 15 | 含 ReAct 推理 + 工具选择 |
| 团队总 LLM 调用 | ≤ 80 | 含主代理拆解/汇总/审查 |
| 子代理并发数 | ≤ 5 | 控制 API 速率与成本 |
| 迭代轮次 | ≤ 2 | `iterative_research` 模板最多 2 轮 fan-out |
| 任务总时长 | 软超时 900s / 硬超时 960s | 比 ResearchJob（600s）更宽裕 |

预算超限时子代理优雅终止，已收集的部分结果回传主代理，主代理在汇总时标注"子代理 X 因预算超限未完成"。

### D.7 Agent 工具

新增 3 个工具（`services/advisor/tools.py`）：

```python
class StartTeamInput(BaseModel):
    objective: str
    template: Literal["cross_domain_research", "independent_validation",
                      "multi_pathway_compare", "risk_scan", "iterative_research"]
    scope: dict = {}           # {goal_id?, engines?, domains?, subquestions?}
    max_specialists: int = 5

class TeamStatusInput(BaseModel):
    job_id: str

class PollTeamInput(BaseModel):
    job_id: str
    timeout_seconds: int = 120  # AgentTeam 比 Research 更长
```

- `start_team`：创建 `AgentTeamJob`，触发 Celery `run_agent_team.delay(job_id)`，返回 `job_id` + `status`。
- `get_team_status`：读 `AgentTeamJob` 表，返回 `status`/`progress`/`specialist_results` 摘要。
- `poll_team`：阻塞等待（最长 `timeout_seconds`），完成或超时返回。

工具注册到 `build_advisor_tools`，始终可用。主 Agent 可在对话中判断任务复杂度后自主调用 `start_team`，或用户在 `/agent-team` 页面手动发起。

### D.8 Celery 任务

`workers/agent_team_tasks.py`：

```python
@celery_app.task(name="run_agent_team", soft_time_limit=900, time_limit=960)
def run_agent_team(job_id: str):
    """执行 AgentTeam 任务。"""
    # 加载 AgentTeamJob
    # 按模板构建 LangGraph team graph
    # 流式执行，节点完成后更新 DB + 推送 SSE
    # 子代理并行用 asyncio.gather 或 LangGraph Send
```

Celery beat **不**注册定时触发（按需启动）。

### D.9 前端

- `frontend/app/agent-team/page.tsx`：AgentTeam 任务列表页。
- `frontend/components/agent-team/team-launcher.tsx`：目标输入 + 模板选择 + scope 配置 + 子代理预览。
- `frontend/components/agent-team/team-progress.tsx`：进度展示（主代理状态 + 各子代理状态卡片 + fan-out/fan-in 可视化）。
- `frontend/components/agent-team/team-result.tsx`：最终输出渲染（按模板适配：研究报告 / 验证结论 / 方案对比表 / 风险清单）。
- `frontend/lib/api.ts`：新增 `startTeam`/`getTeamStatus`/`listTeamJobs`。
- 侧边栏新增"Agent 团队"入口。
- 聊天中 `start_team` toolCall 渲染为可点击团队进度卡片。

## AgentTeam 增强清单

本节回答"哪些功能可以用 AgentTeam 增强"。AgentTeam 不是独立功能，而是为现有功能提供"多代理协作"增强层。下表按"功能 → 单 Agent 现状局限 → AgentTeam 增强点"组织。

### 增强 1：深度研究（Part C）— 跨领域并行研究

| 维度 | 单 Agent 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 子问题处理 | 串行检索，前一个结果占用上下文影响后续 | 多个 ResearchSpecialist 并行，各自绑定不同引擎+领域，独立上下文 |
| 领域覆盖 | 受单上下文限制，倾向只查 1-2 个引擎 | `cross_domain_research` 模板强制分配 Tavily+Exa+博查+AnySearch 给不同子代理 |
| 上下文压力 | 所有工具结果堆在一个 messages 列表，易超 token budget | 子代理各自消化工具结果，只回传结构化摘要给主代理 |
| 迭代补缺 | 单 Agent 难以判断"哪个领域还没查够" | `iterative_research` 模板的 review_node 显式审查领域覆盖缺口，追加子代理 |

### 增强 2：交叉验证（Part B）— 独立验证消除确认偏误

| 维度 | 单 Agent 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 验证独立性 | 同一上下文里先查到的结果会"锚定"后续判断 | `independent_validation` 模板：N 个 ValidationSpecialist 各自独立检索+判断，互不感知 |
| 视角多样性 | 单 Agent 倾向用同一关键词反复搜 | 子代理被赋予不同验证视角（如"官方公报视角""学术视角""中文资讯视角"） |
| 投票质量 | Part B 的 `cross_engine_consensus` 基于引擎数，但同引擎内仍可能被单 Agent 主导 | 子代理独立产出结论后，主代理做"多代理投票"，与"多引擎投票"叠加，双重独立性 |
| 趋势推理 | 单 Agent 难以同时持有多个时态快照 | 不同子代理分别检索不同时间窗，主代理汇总时态序列喂给 `detect_trends` |

### 增强 3：多源搜索（Part A）— 引擎并行与领域路由

| 维度 | 单 Agent 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 引擎并行 | `engines` 参数已支持并发，但结果都进同一上下文 | 每个引擎一个子代理，结果在子代理内初步去重+结构化后再回传 |
| 领域路由 | `domain_router` 推荐引擎组合，但单 Agent 可能不采纳 | 模板强制按推荐分配，子代理无权更改引擎 |
| 结果质量 | 单 Agent 容易被高 score 但低相关结果带偏 | 子代理聚焦单一引擎，能更细致判断结果相关性 |

### 增强 4：多方案对比推演（新能力）

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| Pathway 对比 | `compare_scenarios` 工具串行推演，单上下文 | `multi_pathway_compare` 模板：每个 ScenarioExplorer 子代理独立推演一个 Pathway |
| 推演深度 | 单 Agent 受预算限制，每个 Pathway 推演浅 | 子代理专注单 Pathway，可推演更深 |
| 对比客观性 | 单 Agent 推演所有方案可能有隐性偏向 | 独立推演避免偏向，主代理只做客观对比 |

### 增强 5：风险发现（现有 `discover_risks`）— 多维度并行扫描

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 风险维度 | `discover_risks` 聚类已有 Event，不主动跨维度扫描 | `risk_scan` 模板：DomainAnalyst 子代理分别扫描政策/经济/安全/社会维度 |
| 信源拓展 | 不主动联网查新风险 | 子代理可联网检索各维度新兴风险信号 |

### 增强 6：信源发现（现有 `propose_sources`）— 分领域探索

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 信源多样性 | 单 Agent 倾向推荐同类信源 | 不同领域子代理分别探索官方/学术/中文资讯/垂直信源 |
| 覆盖盲区 | 单 Agent 易遗漏非主要领域信源 | 模板强制覆盖多领域，主代理审查领域覆盖度 |

### 增强 7：知识图谱审计（新能力）

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 图谱一致性 | 无主动审计 | 子代理分模块（Goals/Pathways/Risks/Events）审计图谱内部矛盾与过期 Assertion |
| 过期检测 | `graph_health_check` 仅做 decay sweep | DomainAnalyst 子代理结合联网检索判断 Assertion 是否过期 |

### 增强 8：报告生成（深度研究/决策简报）— 分章节起草

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 报告质量 | 单 LLM 一次性生成全文，章节间易不一致 | SynthesisSpecialist 子代理分章节起草，主代理统稿保证一致性 |
| 篇幅 | 单次生成受输出 token 限制 | 分章节突破长度限制 |

### 增强 9：复杂决策立项（新能力）

| 维度 | 现状 | AgentTeam 增强 |
| :--- | :--- | :--- |
| 立项调研 | 用户手动整理信息 | `cross_domain_research` + `multi_pathway_compare` 组合，自动产出立项依据 |
| 多视角论证 | 单 Agent 论证单一 | 子代理分别扮演"支持者/质疑者/中立分析者"角色（ValidationSpecialist 变体） |

> **增强边界**：AgentTeam 不增强"简单问答""单次工具调用""CRUD 操作"这类低复杂度任务。主 Agent 在对话中会自行判断是否需要启动 AgentTeam（基于子问题数、领域跨度、是否需独立验证），避免过度编排。

## 依赖关系与协同

```text
多源搜索引擎（Part A）
    ↓ 提供 SearchEngine 抽象
    ├──→ 交叉验证（Part B）：搜索结果落库为 Assertion，触发冲突检测
    ├──→ 深度研究（Part C）：多引擎并行搜索 + 结果落库
    └──→ AgentTeam（Part D）：子代理绑定引擎+领域并行检索

交叉验证（Part B）
    ↑ 消费 Assertion
    ├──→ 深度研究（Part C）：validating_node 调用 detect_conflicts + auto_merge
    └──→ AgentTeam（Part D）：independent_validation 模板做多代理独立验证

结构化管道（现有，复用）
    ↑ 消费搜索结果文本
    └──→ 四功能都依赖：搜索结果 → ingest_text → Assertion/Event → 图谱

AgentTeam（Part D）
    ↑ 复用 Part A/B/C 能力
    └──→ 为深度研究/交叉验证/多方案对比/风险扫描等提供多代理协作增强

信源可信度（现有 Beta 模型，扩展）
    ← 交叉验证裁决回流（现有）
    ← 事件审核回流（新增）
    ← 预测对比回流（新增）
    ← 深度研究/AgentTeam 自动合并回流（新增：auto_merge 时对一致信源 record_verdict）
```

**关键协同点**：
1. 深度研究的 `searching_node` 调用 Part A 的 `SearchEngine.search`，`structuring_node` 调用 `StructuringService.ingest_text`（`persist=true`），`validating_node` 调用 Part B 的 `CrossValidationService.detect_conflicts`。
2. Part A 的 `persist=true` 路径与 Part B 的结构化管道冲突检测形成闭环：搜索结果 → 落库 → 自动冲突检测 → 自动合并/存疑/裁决。
3. Part C 的综合报告 `conflicts` 字段直接复用 Part B 的 `ConflictGroup` 数据结构。
4. AgentTeam（Part D）的子代理调用 Part A 的 `SearchEngine`（绑定 engine）、Part B 的 `CrossValidationService`（验证）、Part C 的 `StructuringService`（结构化），是三功能的编排层而非重复实现。
5. AgentTeam 的 `independent_validation` 模板产出"多代理投票"，与 Part B 的"多引擎投票"叠加，形成双重独立性保障。

## 实施路线图

### 阶段 1：多源搜索引擎抽象层（Part A）— P0

前置条件：无。

| 工作项 | 依赖 | 优先级 |
| :--- | :--- | :--- |
| `SearchEngine` 抽象基类 + 统一数据类 + `domain_strengths` | 无 | P0 |
| `TavilyEngine` 迁移现有逻辑 | `SearchEngine` | P0 |
| `CrawlerService` 改造为 facade | `TavilyEngine` | P0 |
| 配置点扩展（env/AppConfig/UserServiceConfig/registry，含 anysearch） | 无 | P0 |
| Settings API 端点（exa/bocha/anysearch/search-engine） | 配置点 | P0 |
| `ExaEngine` 实现 | `SearchEngine` | P1 |
| `BochaEngine` 实现（含 extract 降级） | `SearchEngine` | P1 |
| `AnySearchEngine` 实现（含 domain/sub_domain + batch_search） | `SearchEngine` | P1 |
| `domain_router` 领域推荐 | 四引擎实现 | P1 |
| Advisor 工具 `engine`/`engines`/`domain`/`persist` 参数 | `CrawlerService` facade | P0 |
| 前端配置卡片（platform-config + personal-service-keys，含领域提示） | Settings API | P1 |

### 阶段 2：交叉验证增强（Part B）— P0

前置条件：无（与阶段 1 可并行）。

| 工作项 | 依赖 | 优先级 |
| :--- | :--- | :--- |
| Alembic 迁移：`Assertion.conflicting_with_id` FK + `engine` 字段 + `ConflictResolution` 扩展（含 `cross_engine_consensus`） | 无 | P0 |
| `services/conflict/graph.py` 改造（object_value 严格比较 + 时态过滤 + auto_merge + trend_analysis_node） | 迁移 | P0 |
| `CrossValidationService` 重写为 LangGraph 薄封装 + 缓存 + `detect_trends` | graph 改造 | P0 |
| 跨引擎一致性投票（`cross_engine_consensus` + `engine_diversity_bonus`） | `Assertion.engine` 字段 | P0 |
| 结构化管道接入冲突检测 | `CrossValidationService` | P0 |
| LLM `conflicts_with` 字段持久化 | 迁移 | P1 |
| Celery `scan_all_conflicts` 任务 | `CrossValidationService` | P1 |
| 事件审核回流（`record_verdict` 接入 review.py） | 无 | P1 |
| 前端冲突 Tab 适配（时态展示 + severity + 跨引擎一致性 + 趋势） | `ReviewConflict` 类型变更 | P1 |
| 预测对比回流（`compare_evolution_milestones` 接入） | `model_params` 表 | P2 |

### 阶段 3：深度研究（Part C）— P1

前置条件：阶段 1 完成（`SearchEngine` 抽象）、阶段 2 完成（`detect_conflicts` 可调用）。

| 工作项 | 依赖 | 优先级 |
| :--- | :--- | :--- |
| `ResearchJob` 模型 + Alembic 迁移 | 无 | P0 |
| `research/` 服务模块（planner/searcher/extractor/synthesizer/graph/state） | `ResearchJob` | P0 |
| Celery `run_research_job` 任务 | research graph | P0 |
| Agent 工具（start_research/get_research_status/poll_research） | Celery 任务 | P0 |
| 前端 `/research` 页面 + 组件 | Agent 工具 | P1 |
| 聊天集成（research 进度卡片） | 前端页面 | P1 |
| 预算控制与超时处理 | research graph | P0 |
| 诚实标注与报告校验 | synthesizer | P0 |

### 阶段 4：信源可信度回流完善 — P2

前置条件：阶段 2 完成。

| 工作项 | 依赖 | 优先级 |
| :--- | :--- | :--- |
| 深度研究/AgentTeam auto_merge 回流 | 阶段 3/5 | P2 |
| 信誉冷启动期标注（前端显示"启发式，未经 N 次证据校准"） | 无 | P2 |

### 阶段 5：AgentTeam 编排层（Part D）— P1

前置条件：阶段 1 完成（SearchEngine 抽象）、阶段 2 完成（detect_conflicts 可调用）、阶段 3 完成（ResearchJob 模式可参考）。

| 工作项 | 依赖 | 优先级 |
| :--- | :--- | :--- |
| `AgentTeamJob` 模型 + Alembic 迁移 | 无 | P0 |
| `agent_team/` 服务模块（roles/templates/orchestrator/specialist_graph/graph/state） | `AgentTeamJob` | P0 |
| 5 个团队模板实现（cross_domain_research/independent_validation/multi_pathway_compare/risk_scan/iterative_research） | 服务模块 | P0 |
| Celery `run_agent_team` 任务 | team graph | P0 |
| Agent 工具（start_team/get_team_status/poll_team） | Celery 任务 | P0 |
| 子代理工具集裁剪 + 独立 loop_guard | 服务模块 | P0 |
| 预算与超时控制（子代理 ≤20 调用，团队 ≤80 LLM，软超时 900s） | team graph | P0 |
| 前端 `/agent-team` 页面 + 组件（launcher/progress/result） | Agent 工具 | P1 |
| 聊天集成（team 进度卡片） | 前端页面 | P1 |
| 主 Agent 自主判断是否启动 AgentTeam 的路由逻辑 | Agent 工具 | P1 |

## 边界与风险

### 边界

- **不替代用户决策**：交叉验证自动合并仅处理"多源一致 + 高可信源"的事实级 Assertion；涉及 Goal/Pathway 选择的价值判断仍由用户裁决。
- **深度研究不写入主图谱主分支**：研究结果落库为 Assertion（`status=pending_review` 或 `scenario_id=<research_branch>`），不直接 `status=approved` 挂主图谱，避免污染。
- **多源搜索不解决信源可访问性**：付费墙、JS 渲染、反爬等问题由各引擎自身能力决定，本设计不内置绕过机制。
- **本地隐私模式兼容**：`SearchEngine` 抽象层需通过领域端口（`docs/specs/2026-07-30-local-storage-foundation.md`）适配本地模式——本地模式下若用户未配置任何搜索 key，`web_search` 工具应优雅降级为"不可用"而非崩溃。

### 风险

| 风险 | 影响 | 缓解 |
| :--- | :--- | :--- |
| **Exa/博查/AnySearch API 变更** | 引擎实现失效 | 每个引擎独立实现，单引擎故障不影响其他；API 版本固定在配置中 |
| **博查无 extract API** | 抓取全文能力受限 | 降级到 Tavily extract 或跳过，`ExtractedPage.error` 明确标注 |
| **AnySearch 垂直领域列表变更** | `domain_router` 推荐失效 | `shared/constants.json` 运行时加载，支持热更新；领域映射失败时回退到通用搜索 |
| **多引擎并行延迟与成本** | 4 引擎并行检索耗时与 API 成本翻倍 | `engines` 参数默认不启用并行，仅交叉验证/深度研究场景使用；`batch_search` 复用减少请求数 |
| **跨引擎一致性投票的领域判定主观性** | `domain_strengths` 与 `engine_diversity_bonus` 系数可能不准 | 系数写入 `model_params` 表可调；先验值保守（0.2），随回流数据校准 |
| **趋势推理的时态稀疏性** | 早期数据点不足导致趋势误判 | `detect_trends` 要求至少 2 个不同时点 + 2 个引擎才输出 `changing`，否则标 `divergent` 或 `stable` |
| **深度研究 LLM 成本** | 单次研究可能消耗 20+ 次 LLM 调用 | `max_llm_calls` 预算上限 + 用户可见的成本预估 |
| **深度研究超时** | 10 分钟软超时可能不够复杂研究 | 软超时 600s + 硬超时 660s，超时后 `status=failed`，用户可重启 |
| **交叉验证统一到 Assertion 级的迁移风险** | 现有 `Relationship(type=conflicts_with)` 边语义丢失 | 现有边保留不迁移，自然衰减；新检测逻辑上线前做 A/B 对比（同时跑两套，对比冲突数） |
| **`Assertion.conflicting_with_id` FK 约束** | 现有数据可能有孤儿引用 | 迁移前先 `UPDATE assertions SET conflicting_with_id = NULL WHERE conflicting_with_id NOT IN (SELECT id FROM assertions)` |
| **结构化管道追加冲突检测的性能** | 每次 ingest 都触发检测 | `detect_conflicts_for_assertions` 限定只扫描新 Assertion，不全表扫描；异步执行（不阻塞 ingest 返回） |
| **深度研究/AgentTeam 报告的可信度** | LLM 可能过度自信 | `confidence` 由后端基于信源一致性 + 跨引擎共识计算，不由 LLM 填写；`honesty_disclaimer` 强制写入 |
| **AgentTeam 编排开销与成本** | 多子代理 LLM 调用叠加，单任务成本高 | 团队总 LLM 调用 ≤ 80 上限；主 Agent 自主判断是否启动，简单任务不触发；前端展示成本预估 |
| **AgentTeam 子代理失控** | 子代理偏离任务或无限循环 | 子代理独立 loop_guard（max_tool_calls=20，max_identical=2）；工具集裁剪限制可用工具；软超时 900s |
| **AgentTeam 任务持久化与恢复** | 长任务中断后无法恢复 | `AgentTeamJob` 持久化子任务与部分结果；中断后可查看已完成子代理结果，手动重启未完成部分 |
| **子代理结果汇总冲突** | 多子代理产出矛盾结果 | 主代理汇总时调 `CrossValidationService.detect_conflicts`；矛盾结果进 Review Inbox 而非自动取舍 |

## 验收标准（L2 成熟度口径）

参照 §11.0 成熟度等级，本设计目标为 L2（可用），部分能力达到 L2-L3 之间。

### 交叉验证 L2 验收

- [ ] `Assertion.conflicting_with_id` FK 约束生效，无孤儿引用；`Assertion.engine` 字段可用。
- [ ] 结构化管道写入 Assertion 后自动触发冲突检测，异步完成，不阻塞 ingest 返回。
- [ ] `CrossValidationService.detect_conflicts` 基于 `object_value` + 时态有效性，不再基于 `Relationship`。
- [ ] 跨引擎一致性投票：`cross_engine_consensus` 与 `engine_diversity_bonus` 计算正确，自动合并判据生效。
- [ ] 趋势推理：`detect_trends` 对时态序列输出 `direction`/`transition_point`，`changing` 时自动 spawn 趋势分支。
- [ ] `list_conflicts` 缓存生效，TTL 5min，缓存命中率 > 80%（正常使用下）。
- [ ] Celery `scan_all_conflicts` 每日执行，结果写入缓存 + 推送高 severity 冲突到 Review Inbox。
- [ ] 自动合并：跨引擎一致（≥2 引擎）+ 高可信源 Assertion 自动 `status=confirmed`，不进 Review Inbox。
- [ ] 事件审核回流：用户 approve/reject Event 后，源 `credibility_score` 更新。
- [ ] 前端冲突 Tab 展示时态版本 + severity + 跨引擎一致性 + 趋势 + 原文摘录。
- [ ] 回归测试：现有 `test_risk_tenancy.py` 等测试全通过；新增冲突检测单元测试覆盖时态、多源一致、跨引擎投票、趋势推理、自动合并、用户裁决场景。

### 多源搜索引擎 L2 验收

- [ ] `SearchEngine` 抽象基类 + `TavilyEngine`/`ExaEngine`/`BochaEngine`/`AnySearchEngine` 四实现。
- [ ] `CrawlerService` facade 对现有调用方零影响（`advisor/tools.py`、`api/crawler.py`、`workers/tasks.py`、`source_discovery.py` 无改动即可工作）。
- [ ] `domain_router.recommend_engines` 按 query 主题推荐引擎组合，仅返回用户已配置 key 的引擎。
- [ ] 配置点：env + AppConfig + UserServiceConfig + registry 全套（含 anysearch），admin UI 与用户个人配置卡可设置。
- [ ] Settings API：`/settings/exa`、`/settings/bocha`、`/settings/anysearch`、`/settings/search-engine` 端点可用，多用户模式下非 admin 看到脱敏预览。
- [ ] `web_search`/`web_fetch` 工具支持 `engine`/`engines`/`domain`/`persist` 参数；`persist=true` 时搜索结果落库为 `InformationSource` + 结构化，并记录 `meta.engine`。
- [ ] 多引擎并行：`engines` 传入多引擎时并发调用、合并去重、每条结果标注 `engine` 来源。
- [ ] AnySearch 垂直领域：`domain` 参数传入时 `AnySearchEngine` 命中垂直结构化数据；`batch_search` 支持多 query 并行。
- [ ] 单引擎故障隔离：某引擎 key 未配置时，其他引擎调用正常；未配置引擎调用返回明确错误提示。
- [ ] 博查 extract 降级：博查无 extract 时降级到 Tavily 或返回 `error` 字段，不抛异常。

### 深度研究 L2 验收

- [ ] `ResearchJob` 表与迁移上线，状态机 8 态完整。
- [ ] Celery `run_research_job` 任务可执行完整研究流程（planning → searching → extracting → structuring → validating → synthesizing），软超时 600s。
- [ ] 3 个 Agent 工具（start_research/get_research_status/poll_research）注册并在对话中可调用。
- [ ] 预算控制生效：`max_sub_questions`/`max_total_sources`/`max_extract_chars`/`max_llm_calls` 超限时任务优雅终止并标注原因。
- [ ] 综合报告 `confidence` 由后端基于信源一致性计算，不由 LLM 填写。
- [ ] `honesty_disclaimer` 强制写入所有报告；证据不足或高冲突时 `summary` 包含警告。
- [ ] 前端 `/research` 页面可启动研究、查看进度、阅读报告。
- [ ] 聊天中 `start_research` toolCall 渲染为可点击进度卡片。
- [ ] 研究结果落库为 `Assertion`（`status=pending_review` 或 `scenario_id=<research_branch>`），不直接挂主图谱。

### AgentTeam L2 验收

- [ ] `AgentTeamJob` 表与迁移上线，状态机 8 态完整（decomposing/dispatching/running/aggregating/reviewing/completed/failed/cancelled）。
- [ ] 5 个团队模板实现并可用：`cross_domain_research`/`independent_validation`/`multi_pathway_compare`/`risk_scan`/`iterative_research`。
- [ ] Celery `run_agent_team` 任务可执行完整编排流程（拆解 → 分配 → 并行 → 汇总 → 可选审查 → 完成），软超时 900s。
- [ ] 3 个 Agent 工具（start_team/get_team_status/poll_team）注册并在对话中可调用。
- [ ] 子代理独立上下文：每个子代理有独立 messages，不共享主代理历史。
- [ ] 子代理工具集裁剪：按角色只注入相关工具，`ResearchSpecialist` 无写ontology工具，`ValidationSpecialist` 无创建工具。
- [ ] 子代理预算：每个 ≤ 20 工具调用、≤ 15 LLM 调用；团队总 LLM ≤ 80；超限优雅终止并标注。
- [ ] 子代理并发 ≤ 5；`iterative_research` 迭代轮次 ≤ 2。
- [ ] fan-out/fan-in 编排：子代理并行执行后主代理汇总，汇总时调 `CrossValidationService.detect_conflicts` 处理矛盾结果。
- [ ] 前端 `/agent-team` 页面可启动团队任务、查看主代理+子代理进度、阅读最终输出。
- [ ] 聊天中 `start_team` toolCall 渲染为可点击团队进度卡片。
- [ ] 主 Agent 自主路由：简单任务不触发 AgentTeam，复杂任务（子问题 ≥3 或跨 ≥2 领域或需独立验证）才启动。
- [ ] 诚实标注：AgentTeam 输出包含 `honesty_disclaimer` 与子代理贡献来源标注。

### 信源可信度回流 L2 验收

- [ ] 三条回流路径（交叉验证裁决、事件审核、预测对比）均可触发 `record_verdict`。
- [ ] 深度研究 auto_merge 时对一致信源调 `record_verdict`。
- [ ] 冷启动期（证据数 < 4）前端显示"启发式，未经 N 次证据校准"标注。

---

## 附录：关键文件改动清单

### 新增文件

| 路径 | 用途 |
| :--- | :--- |
| `backend/app/services/search_engines/__init__.py` | 引擎工厂导出 |
| `backend/app/services/search_engines/base.py` | `SearchEngine` 抽象基类 + `SearchHit`/`ExtractedPage` + `domain_strengths` |
| `backend/app/services/search_engines/tavily_engine.py` | Tavily 实现（迁移自 `crawler.py`） |
| `backend/app/services/search_engines/exa_engine.py` | Exa 实现 |
| `backend/app/services/search_engines/bocha_engine.py` | 博查实现 |
| `backend/app/services/search_engines/anysearch_engine.py` | AnySearch 实现（含 domain/sub_domain + batch_search） |
| `backend/app/services/search_engines/domain_router.py` | 领域适配策略：按 query 推荐引擎组合 |
| `backend/app/models/research.py` | `ResearchJob` 模型 |
| `backend/app/models/agent_team.py` | `AgentTeamJob` 模型 |
| `backend/app/services/research/__init__.py` | 研究服务导出 |
| `backend/app/services/research/planner.py` | LLM 研究计划生成 |
| `backend/app/services/research/searcher.py` | 多源搜索执行器 |
| `backend/app/services/research/extractor.py` | URL 批量抓取 |
| `backend/app/services/research/synthesizer.py` | 综合报告生成 |
| `backend/app/services/research/graph.py` | LangGraph 研究编排 |
| `backend/app/services/research/state.py` | `ResearchState` |
| `backend/app/services/agent_team/__init__.py` | AgentTeam 服务导出 |
| `backend/app/services/agent_team/roles.py` | 子代理角色定义 + 工具集裁剪 |
| `backend/app/services/agent_team/templates.py` | 5 个团队模板 |
| `backend/app/services/agent_team/orchestrator.py` | 主代理：拆解/分配/汇总/审查 |
| `backend/app/services/agent_team/specialist_graph.py` | 子代理子图（简化 ReAct） |
| `backend/app/services/agent_team/graph.py` | AgentTeam LangGraph 编排（Send API） |
| `backend/app/services/agent_team/state.py` | `TeamState` |
| `backend/app/workers/research_tasks.py` | `run_research_job` Celery 任务 |
| `backend/app/workers/agent_team_tasks.py` | `run_agent_team` Celery 任务 |
| `backend/alembic/versions/o8b9c0d1e2f3_add_search_engine_config.py` | exa/bocha/anysearch/search_default_engine 配置迁移 |
| `backend/alembic/versions/p9c0d1e2f3a4_unify_conflict_to_assertion.py` | `Assertion.conflicting_with_id` FK + `engine` 字段 + `ConflictResolution` 扩展 |
| `backend/alembic/versions/q0d1e2f3a4b5_add_research_jobs.py` | `research_jobs` 表 |
| `backend/alembic/versions/r1e2f3a4b5c6_add_agent_team_jobs.py` | `agent_team_jobs` 表 |
| `frontend/app/research/page.tsx` | 研究任务列表页 |
| `frontend/components/research/research-launcher.tsx` | 研究启动器 |
| `frontend/components/research/research-progress.tsx` | 进度展示 |
| `frontend/components/research/research-report.tsx` | 报告渲染 |
| `frontend/app/agent-team/page.tsx` | AgentTeam 任务列表页 |
| `frontend/components/agent-team/team-launcher.tsx` | 团队启动器 |
| `frontend/components/agent-team/team-progress.tsx` | 主代理+子代理进度展示 |
| `frontend/components/agent-team/team-result.tsx` | 最终输出渲染 |

### 改动文件

| 路径 | 改动 |
| :--- | :--- |
| `backend/app/services/crawler.py` | `CrawlerService` 改为 facade，内部委托 `SearchEngine` |
| `backend/app/llm/registry.py` | 新增 exa/bocha/anysearch/search_default 读写函数 |
| `backend/app/core/config.py` | 新增 env 字段（含 anysearch_api_key） |
| `backend/app/models/llm_config.py` | `AppConfig` keys 注释扩展（含 anysearch） |
| `backend/app/models/user_runtime.py` | `UserServiceConfig` 新增 exa/bocha/anysearch/search_default |
| `backend/app/models/intelligence.py` | `ConflictResolution` 新增 `assertion_ids`/`winning_assertion_id`/`cross_engine_consensus` |
| `backend/app/models/event.py` | `Assertion.conflicting_with_id` 启用 FK；新增 `engine` 字段 |
| `backend/app/api/settings.py` | 新增 exa/bocha/anysearch/search-engine 端点 + `_restricted_view` 扩展 |
| `backend/app/api/review.py` | `list_conflicts` 改用缓存；事件审核接 `record_verdict` |
| `backend/app/services/cross_validation.py` | 重写为 LangGraph 薄封装 + 缓存 + `detect_trends` |
| `backend/app/services/conflict/graph.py` | `detect_conflicts_node` 改用 object_value + 时态；新增 `auto_merge_node` + `trend_analysis_node` |
| `backend/app/services/structuring.py` | 末尾追加冲突检测；持久化 `conflicts_with` hint |
| `backend/app/services/advisor/tools.py` | `WebSearchInput`/`WebFetchInput` 加 `engine`/`engines`/`domain`/`persist`；新增 3 个研究工具 + 3 个 AgentTeam 工具 |
| `backend/app/workers/celery_app.py` | beat 注册 `scan_all_conflicts` |
| `backend/app/workers/intelligence_tasks.py` | 新增 `scan_all_conflicts`；`compare_evolution_milestones` 接入回流 |
| `frontend/lib/api.ts` | 新增 exa/bocha/anysearch/search-engine/research/agent-team API 函数 |
| `frontend/components/settings/platform-config.tsx` | 新增 Exa/博查/AnySearch/默认引擎配置卡（含领域提示） |
| `frontend/components/settings/personal-service-keys.tsx` | 新增 Exa/博查/AnySearch per-user key |
| `frontend/components/review/conflicts-tab.tsx` | 时态展示 + severity + 跨引擎一致性 + 趋势 + 原文摘录 |
| `frontend/components/chat/chat-panel.tsx` | 解析研究/团队 toolCall 渲染进度卡片 |
| `frontend/components/layout/sidebar.tsx` | 新增"深度研究"与"Agent 团队"入口 |

---

*本设计基于 2026-08-07 代码盘点，所有"现状"描述均对应实际文件与行号。实施时若代码已演进，需重新核对现状再开工。*
