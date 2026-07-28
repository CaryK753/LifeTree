# LifeTree 项目书

**版本**：1.1  
**最后更新**：2026-07-28  
**作者**：LifeTree 团队  
**密级**：内部

---

## 目录

1. [项目愿景与使命](#1-项目愿景与使命)  
2. [问题域与市场痛点](#2-问题域与市场痛点)  
3. [产品定位与核心价值](#3-产品定位与核心价值)  
4. [核心功能与机制详解](#4-核心功能与机制详解)  
   - 4.1 [长周期多源信息聚合与结构化](#41-长周期多源信息聚合与结构化)  
   - 4.2 [知识图谱与因果推理引擎](#42-知识图谱与因果推理引擎)  
   - 4.3 [分支推演与情景规划](#43-分支推演与情景规划)  
   - 4.4 [用户画像与个性化决策](#44-用户画像与个性化决策)  
   - 4.5 [即时风险预警与通知](#45-即时风险预警与通知)  
   - 4.6 [可能性预测与数学模型](#46-可能性预测与数学模型)  
   - 4.7 [用户私有信息集成与可信度管理](#47-用户私有信息集成与可信度管理)  
   - 4.8 [去重、合并与信息生命周期管理](#48-去重合并与信息生命周期管理)  
5. [用户体验与交互设计](#5-用户体验与交互设计)  
6. [产品盲点与应对策略](#6-产品盲点与应对策略)  
7. [技术架构](#7-技术架构)  
   - 7.1 [整体架构概览](#71-整体架构概览)  
   - 7.2 [前端架构设计](#72-前端架构设计)  
   - 7.3 [后端架构设计](#73-后端架构设计)  
   - 7.4 [数据存储设计](#74-数据存储设计)  
   - 7.5 [关键数据流](#75-关键数据流)  
   - 7.6 [部署与运维架构](#76-部署与运维架构)  
   - 7.7 [安全与权限模型](#77-安全与权限模型)  
   - 7.8 [插件系统](#78-插件系统)  
8. [开源与商业化策略](#8-开源与商业化策略)  
9. [实施路线图](#9-实施路线图)  
10. [实施现状与已落地能力](#10-实施现状与已落地能力)  

---

## 1. 项目愿景与使命

**愿景**：成为每个认真规划人生的人手中的“决策罗盘”，在不确定的世界中持续提供清晰、可信、个性化的中长期决策洞察。

**使命**：通过聚合公开与私域信息，结合知识图谱与因果推理模型，为用户构建一个动态、可演进的决策沙盘，帮助他们提前感知风险、评估路径、推演未来，做出更有信心的重大人生选择。

---

## 2. 问题域与市场痛点

人生中的重大决策（移民、留学、海外置业、职业转型、退休养老等）通常具有以下特征：

- **周期长**：往往需要提前 2-5 年准备，涉及资金、语言、资格等多个慢变量。
- **信息多源且碎片化**：政策、经济、治安、国际关系等信息分散在政府网站、新闻媒体、专业论坛、付费报告、私域社群中。
- **依赖趋势跟踪而非快照**：仅靠单次搜索无法理解一个事件在时间轴上的演变，也无法感知多个因素的交叉影响。
- **缺失风险预警**：传统搜索引擎只能被动响应查询，无法主动告知“某个长期酝酿的风险正在接近你的目标”。
- **通用信息与个人条件脱节**：同样的政策变化，对不同背景和进度的用户，影响截然不同，但现有工具无法做出个性化推演。

**现有解决方案的局限**：
- 搜索引擎（Google, Bing）：只给切片，不给趋势和关联。
- 移民留学中介：依赖人力，信息更新滞后，利益相关，且无法提供透明推演。
- 普通笔记/表格软件：无法自动化监控和分析外部变化。

---

## 3. 产品定位与核心价值

LifeTree 是 **一款专注于中长期个人决策的智能信息系统**。它并非简单的工具，而是一个 **“决策操作系统”**。

它为用户提供的核心价值是：

- **一个持续更新的个人化知识图谱**：融合公开与私域信息，围绕用户目标自动生长。
- **一个动态的因果推理与风险预警引擎**：识别事件之间的关联，提前量化风险。
- **一套可控的“多重未来”沙盘**：在信息冲突或决策犹豫时，分叉出多种情景并平行推演，供用户对比。
- **一位伴随全周期的 AI 决策顾问**：能读懂用户的个人背景、偏好和进度，给出具有可执行性的建议。

---

## 4. 核心功能与机制详解

### 4.1 长周期多源信息聚合与结构化

**痛点**：信息存在于搜索引擎、政府 API、付费墙后、用户邮箱/社群里，格式多样，缺少统一整合。

**解决方案**：
- **公开信息源**：使用 Tavily 等搜索代理引擎进行周期性抓取，原始爬虫和维护不自己做。
- **私域信息源**：允许用户通过文本粘贴、文件上传、邮件转发等方式提交自己的信源（如顾问邮件、论坛内部消息、PDF 报告等）。
- **结构化管道**：所有流入的非结构化文本，均通过 LLM 提取为统一的“信息原子”：
  - **事件**：主体、动作、对象、时间、旧值、新值
  - **指标快照**：数值型数据点，含区域、时间、单位
  - **断言**：未完全证实的声明，带可信度标记
  - **关系声明**：因果或相关关系
- **LLM 抽取控制**：使用 Instructor 或 LangChain 的 Structured Output 确保输出符合 Pydantic Schema；引入抽取置信度评分，低分进入人工审核队列。

### 4.2 知识图谱与因果推理引擎

**理念**：借鉴 Palantir 的“本体驱动的知识图谱”，构建人生决策专用本体。

**核心实体**：
- **Goal**：用户目标（如“2029年前获得加拿大 PR”）
- **Pathway**：实现路径（如“联邦技术移民”）
- **Requirement**：要求节点（语言成绩、资金证明、学历认证）
- **RiskFactor**：外部风险（政策突变、治安恶化、汇率波动）
- **InformationSource**：每条数据的来源与可信度

**关系类型**：`影响`、`要求`、`替代`、`预警`、`等同于`、`导致` 等。

**图谱生长机制**：
- 当结构化管道输出新事件时，图谱自动挂载到相关实体上。
- 因果推理层在图谱上执行**风险传播算法**：当一个政策节点发生变化，顺着影响边更新所有关联路径和目标的风险评分。
- 存储于 Neo4j，利用 Cypher 进行深度路径查询和影响范围计算。

### 4.3 分支推演与情景规划

**痛点**：信息冲突、信源质量不一、用户自身也可能存在多种假设。线性预测无法应对真实世界的模糊性。

**解决方案**：引入“情景分叉”机制。
- 当系统检测到对同一实体存在冲突断言（如官方金额 vs 用户情报金额），自动创建**主分支和子分支**。
- 用户可手动触发“禁用存疑信息开启推演”，或在决策顾问中提问“如果 X 会发生什么？”来新建情景。
- 每个情景独立进行计算和模拟，互不污染。
- 用户界面呈现**情景矩阵**：横轴为不同假设分支，纵轴为时间线，每个情景显示风险评分和关键里程碑。
- **分支防爆炸**：设置影响力阈值，仅保留对目标达成影响显著的分支；当存疑信息被证实或证伪时，分支自动合并或关闭；长期未更新且低影响的分支进入休眠。

### 4.4 用户画像、对话驱动图谱生长与动态决策

**对话驱动生长机制（Conversational Graph Building）**：
- **替代繁重表单**：彻底摒弃传统“坐下来填完 50 个表单”的冰冷交互。用户只需像与真实决策顾问聊天一样交流（如：“我今年30，在考虑去加拿大还是日本”、“我上周雅思听力考了7.5”、“中介说这个配额好像缩减了”）。
- **后台实时抽取与 Tool Calling**：AI 在对话过程中利用 Tool Calling 静默提取结构化原子，自动完成：
  1. `update_user_profile`（更新年龄、语言、资金、生命周期）
  2. `create_scenario_branch`（创建“加拿大分支”与“日本分支”）
  3. `add_user_source`（记录中介情报或个人凭证）
  4. `update_requirement_status`（点亮已达标节点）
- **透明卡片反馈（Chat-to-Graph Loop）**：对话界面侧边/下方随聊随弹“为您同步更新了沙盘：【雅思听力: 7.5】”，用户可一键确认或纠偏，既无填表负荷，又能随时把控。

**画像结构**：
- **基础属性**：年龄、国籍、学历、语言成绩、资金范围等（支持聊天自然提取、简历/文档解析与渐进式补充）。
- **申请生命周期状态（Lifecycle Stage）**：明确标注用户所处阶段（`planning`筹备中, `submitted`已递交, `in_review`审理中, `waiting_eoi`等邀），用于精准匹配新旧政策“祖父条款/过渡期”豁免。
- **家庭与主副申请人（Joint Profile）**：支持家庭多角色属性合并（如配偶语言成绩、资金共享池）。
- **目标与偏好**：主目标、倾向路径、优先因素（成本、速度、气候）、风险容忍度。
- **行为与进度**：当前考试计划、资金积累进度、已完成步骤。可通过对话自然提取与更新。
- **隐式标签**：从聊天交互中推测的治安敏感度、子女教育重视度等，用于信息过滤。

**画像驱动**：
- 路径匹配：自动筛选符合画像条件的路径并计算差距。
- 个性化预警：同一政策变化，基于生命周期状态（如已递交用户豁免新规）做精准差异化预警。
- 进度洞察：语言达标但资金落后，系统自动调高资金类政策变动的提醒优先级。

### 4.5 即时风险预警与巡航/静眠模式（Cruising Mode）

- **风险识别层**：cron 抓取后，LLM 额外输出 `risk_flag`（高风险/中/低，类型，紧迫度）。
- **巡航/静眠模式（Cruising Mode）**：
  - 在长期等待期（如递交材料后 6-12 个月审理期），允许用户开启巡航态。
  - 巡航态下屏蔽中低风险日常推送，仅当检测到对关键路径有 `CRITICAL` 影响或涉及祖父条款变动时，方激活唤醒预警，防止“预警疲劳（Alert Fatigue）”。
- **波及扫描**：根据风险类型，在图谱中查找所有受影响用户，结合用户画像生成个性化影响摘要。
- **多渠道推送**：Email、站内信、SMS（用户可选），App 推送。严重事件可触发 SMS。
- **推送节制**：单用户同类型事件冷却期、免打扰时段设置。

### 4.6 可能性预测、数学模型与风险可控度（Risk Controllability Grade）

采用多层融合的预测体系，并重构输出形式：

- **贝叶斯网络与蒙特卡洛模拟**：考虑外部事件概率分布和用户行动选择，运行数千次模拟，计算置信区间。
- **风险可控度等级（Risk Controllability Grade）**：
  - 不再单纯给用户展示易引发生理焦虑的单一点胜率（如“68%”）。
  - 转化为三级“风险可控度”（**稳健 / 中等风险 / 高风险脆弱**）及**核心瓶颈消除卡片**（如：“消除该扣分项仅需提高雅思单项0.5分”）。
- **输出形式**：呈现为置信区间、风险可控度等级与因子分解归因瀑布图。

### 4.7 用户私有信息集成与可信度管理及隐私防线

- 所有私有上传信息打上 `source=user_upload`，并默认设为“可信度：待用户评定”。
- **端侧脱敏预览**：解析前在前端自动对姓名、身份证号、资产具体账号进行遮蔽脱敏，消除隐私顾虑。
- 用户可手动标记“可靠”或“存疑”。
- 分析报告明确区分“基于公开信息”和“混入私密信息”的结论，并标注可能的风险。
- 法律免责：上传流程强制确认“我知道这些信息未经平台验证，后果自负”。

### 4.8 去重、合并与信息生命周期管理

- **去重**：基于语义指纹（主体+动作+对象+时间窗）和跨源实体对齐（LLM 辅助判定）进行合并。
- **更新 vs 新事件**：更新旧节点并记录历史版本，而非新建节点。
- **知识半衰期**：政策信息默认有效期 2 年，到期需刷新；新闻事件影响力定期衰减。
- **图谱健康巡检**：自动任务定期标记并清理孤立、过时节点。

### 4.9 信息审核收件箱（Review Inbox）与后台沉降验真

**痛点**：若要求普通用户在收件箱中逐条卡片审核抓取的互联网传闻或解析原子，会甩给用户极高的数据把关负荷与验真焦虑。

**解决方案**：重构 Review Inbox 为“分层自动沉降与高影响度留存”。
- **智能置信度分层**：
  - 高置信度官方源事件：自动挂载主图谱，免人工干预。
  - 中低置信度传闻：后台自动创建轻量级“存疑子分支”，计算其对用户目标的潜在影响度。
  - 仅当存疑事件对用户关键路径产生 `HIGH` 或 `CRITICAL` 影响时，才推送到 Review Inbox 提醒用户关注。
- **卡片式极简快捷 UI**：仅展示必要的高影响待办，提供一键 `采纳` / `忽略` / `保持低权重沉降`。

---

## 5. 用户体验与交互设计

围绕“降低冷启动门槛”、“建立算法信任”、“消除长周期焦虑”三大目标，重构 UX 交互体系：

### 5.1 场景模板市场与渐进式向导（Scenario Marketplace & Progressive Wizard）
- **场景模板库**：官方与社区提供热门人生场景模板（如“新西兰技术移民”、“日本 IT 转型”）。一键导入基础图谱框架。
- **渐进式立项向导（Progressive Wizard）**：
  - 首次使用仅需 3 个极简问题（目标国家/领域、预计时间、大概预算），先生成粗粒度预测。
  - 随着用户深入使用，在触及关键分支时才提示补充工作细节或成绩单，彻底解决冷启动填表疲劳。
  - 支持直接拖入 PDF 简历/成绩单自动智能提取。

### 5.2 多视窗交互与关键路径高亮（Timeline/Gantt & Critical Path）
- **时间线/甘特图主视图**：默认以时间轴为主视图，清晰呈现“当前阶段重点”、“未来里程碑”与“关键窗口期”。
- **关键路径高亮**：提供“聚焦模式”，自动收起非关键分支，高亮“短板要求节点”（如语言未达标）与“致命风险节点”。

### 5.3 白盒化推理与因子归因瀑布图（Attribution Waterfall）
- **归因瀑布图**：点击风险可控度等级，弹窗展示透明的因子分解：
  - `+85%` 基础符合度（学历与工作年限满足基本要求）
  - `-12%` [致命风险] 资金准备存在 $20,000 缺口
  - `-5%` [存疑事件] 社区传闻 2027 年配额缩减
- **信源溯源下钻**：任何扣分因子均可一键下钻查看原始文件或新闻网页。

### 5.4 无悔微行动与巡航抗焦虑设计（No-Regret Micro Actions & Cruising Mode）
- **解焦微行动**：推理引擎结合短板自动收敛输出 1~2 项无悔微行动（如：“距离语言审核窗口仅剩 90 天，提高单项 0.5 分可消除资金波动风险”）。
- **巡航免打扰态**：在漫长等待期开启巡航模式，隐藏琐碎通知，保护用户免受无谓焦虑打扰。

### 5.5 多情景活跃限制与家庭/多角色协同（Active Branch Limits & Family Sandbox）
- **并发活跃分支限制**：限制界面同时激活的核心对比分支最多 3 个，超出的分支自动沉降归档，有效消除决策瘫痪。
- **家庭/多角色联合协同**：除了加密只读/评论链接外，支持主副申请人（如夫妻）共同构建联合画像，在同一个沙盘中并排测算不同主申方案的风险可控度。

---

## 6. 产品盲点与应对策略矩阵

结合真实用户全流程视角，汇总系统 16 大核心痛点与优化策略矩阵：

| 痛点/盲点类别 | 具体风险与痛点 | 深度应对与优化策略 |
| :--- | :--- | :--- |
| **1. 冷启动门槛** | 空白画布无从下手，首次填表成本极高 | 提供模板套用，配套 3 步渐进式立项向导与简历/PDF 智能提取 |
| **2. 节点意面图** | 节点>20 后拓扑图变成混乱蛛网 | 以“时间线/甘特图”为主视图，增加“关键路径”聚焦高亮 |
| **3. 算法胜率焦虑** | 单一胜率数字（如 68%）引发精算焦虑 | 转为“风险可控度等级”（稳健/中等/脆弱）与瓶颈消除指导 |
| **4. 分支瘫痪负荷** | 多分支组合爆炸导致决策瘫痪 | 限制最多 3 个活跃并发分支，超出的自动化沉降归档 |
| **5. 长周期等待断崖** | 6-12个月等待期无动作，导致用户流失 | 引入“巡航/静眠免打扰态”，降频防打扰，仅关键突变唤醒 |
| **6. 验真包袱倒置** | 强制用户审核 Review Inbox 增加把关负担 | 置信度自动分层与后台权重化沉降，仅高影响度触达用户 |
| **7. 政策过渡期割裂** | 新旧政策变动未区分已递交/未递交用户 | 画像中引入生命周期状态（Submitted/EOI），精准匹配祖父条款 |
| **8. 协同能力局限** | 单人只读/评论分享无法满足家庭共同决策 | 支持家庭联合画像（主副申请人合并测算）与共享沙盘 |
| **9. 隐私保护信任墙** | 上传敏感凭证/文档担心数据泄露 | 前端本地端侧敏感字段自动遮蔽脱敏 + 白盒安全提示 |
| **10. 信息数据污染** | 自动抓取或解析的脏数据污染图谱 | 隔离缓冲队列 + 后台概率权重衰减，避免直挂主图谱 |
| **11. 工程与计算成本** | LLM 结构化抽取与模拟计算成本过高 | 分层模型（轻量 NLP 预处理 + LLM 结构化），置信度过滤 |
| **12. 知识熵增** | 信息过时导致图谱失效 | 引入知识半衰期衰减模型、自动巡检与到期提示机制 |

---

## 7. 技术架构

### 7.1 整体架构概览

- **前端**：React/Next.js 16（App Router）+ Tailwind CSS + Radix UI，构建为 PWA，支持 standalone / minimal-ui 显示模式
- **后端 API**：Python FastAPI，SSE 实时推送，LangGraph ReAct Agent 编排
- **任务队列与调度**：Celery Worker + Celery Beat + Flower 监控
- **主数据库**：PostgreSQL 16（开启 pgvector 扩展，存放事件嵌入向量）
- **图数据库**：Neo4j 5.20（含 APOC），存储本体实例与关系
- **缓存与消息**：Redis 7（Celery broker + SSE pub/sub）
- **对象存储**：MinIO（用户上传原始文件 + LLM 中间结果）
- **反向代理**：Nginx（统一入口，SSE 流式转发，无 CORS）
- **LLM 编排**：前端 Vercel AI SDK 流式 + 后端 LangGraph ReAct Agent + Instructor 结构化输出；多供应商适配（OpenAI / Anthropic / AlibabaCloud / Google / DeepSeek / Zhipu / ByteDance / Microsoft / AWS / Mistral / Cohere / Meta 等通过 `@lobehub/icons` 显示品牌头像）
- **国际化**：内置 6 语言（zh-CN / zh-TW / en / es / de / fr），cookie 驱动 + 自动检测
- **监控与日志**：Flower（Celery 任务监控）+ Docker healthcheck + Sentry（规划中）
- **CI/CD**：GitHub Actions（构建并推送 GHCR 镜像，linux/amd64）

### 7.2 前端架构设计

- **框架**：Next.js 16，App Router，SSR/SSG/ISR 混合，Turbopack 构建。
- **AI 集成**：Vercel AI SDK 实现与 FastAPI 后端的流式对话（SSE 直连后端，绕过 Next.js dev proxy 缓冲），支持工具调用（触发推演、添加监控）。
- **状态管理**：React Context + SWR 做服务端状态同步；`useSyncExternalStore` 实现聊天会话本地持久化（按 user ID 分区存储）。
- **可视化**：ECharts（概率曲线、归因瀑布图）；Cytoscape.js（知识图谱拓扑图，支持节点点击下钻原始事件）；Recharts（时间线甘特图）。
- **样式**：Tailwind CSS + Radix UI 构建无障碍组件，支持亮色/暗色/系统三种主题，遵循 `prefers-reduced-motion` 媒体查询。
- **国际化**：自研 i18n provider，6 语言完整翻译（zh-CN 基准 / zh-TW / en / es / de / fr），cookie 驱动 + `navigator.language` 自动检测，缺失 key 回退 zh-CN。
- **PWA**：manifest.webmanifest（standalone 显示 + maskable 图标 + 3 个 shortcuts：罗盘/对话/预警）+ Service Worker + 内联 PWA 检测脚本（hydration 前注入 `html.pwa` 类避免闪烁）+ 抽屉式侧边栏（viewport < 1024px 触发）。
- **多用户模式**：AuthGate 组件在 multi-user 模式下未认证不渲染 children（避免 SWR 误触发 API 请求）；单用户模式回退到默认用户（Alex Chen）。
- **移动端**：已通过 PWA 完整支持 iOS/iPadOS（apple-touch-icon + apple-mobile-web-app-capable），后续可探索 SwiftUI 原生体验。

### 7.3 后端架构设计

- **API 层**：FastAPI 提供 19 个路由模块的 RESTful API 和 SSE 端点（实时风险推送 + 模拟进度 + 聊天流）。
- **AI 顾问（chat）**：基于 LangGraph `create_react_agent` 的 ReAct Agent，通过 `astream_events` v2 流式输出。注册 14 个工具：
  - **读取**：`list_pathways` / `list_requirements` / `list_risk_factors` / `list_recent_events` / `get_scenario_summary` / `list_memories`
  - **写入**：`create_goal` / `create_pathway` / `create_requirement` / `update_requirement_status` / `create_risk_factor` / `create_scenario_branch` / `remember` / `forget` / `update_user_profile` / `add_user_source`
  - **执行**：`run_scenario_reasoning`
  - **网络**：`web_search` / `web_fetch`
  - **上下文构建**：`_build_context_block` 注入用户/目标/路径/要求/风险因子/情景 + 多样性记忆选取（15 条，per-category cap）；100k token 历史截断（原子分组，首条用户消息保留）。
- **服务模块**：
  - `crawler_service`：调度 Tavily API 和用户自定义源抓取。
  - `structuring_service`：LLM 管道（Instructor + Pydantic），非结构化文本到结构化原子，输出 events/metrics/assertions/relationships。
  - `dedup_service`：sha256 语义指纹（subject|action|object|time_window）去重。
  - `review_inbox_service`：信息审核队列，按置信度自动分层（approved≥0.8 / pending_review<0.8 且 impact≥high / sunk_low_weight 其他）。
  - `graph_service`：Neo4j 交互层，7 类节点（Goal/Pathway/Requirement/RiskFactor/Event/InformationSource/Scenario）+ 7 类关系，含 `PROPAGATE_RISK_FROM_EVENT` 多跳风险传播遍历。双存储策略：PG 为真相源，Neo4j 镜像用于路径查询。
  - `user_profiling_service`：用户画像构建与更新，每次 PATCH 后自动 refresh。
  - `reasoning_engine`：风险传播算法、贝叶斯网络更新、蒙特卡洛模拟调度、因子归因瀑布与无悔行动计算（由 Celery 异步执行）。
  - `notification_service`：多通道分发（email / in_app / sms(stub) / push），含 6 小时冷却 + 安静时段 + Cruising Mode 抑制规则。SMTP 支持 SSL(465)/STARTTLS(587)，HTML 模板。
  - `lifecycle_service`：知识半衰期管理（policy=730d / economic=180d / security=90d 等），自动巡检与归档。
  - `plugin_upload_service` / `plugin_runner`：用户插件 AST 检查、契约验证、运行时加载（详见 7.8）。
  - `webauthn_service`：Passkey 注册/认证/管理（discoverable credentials + sign_count 防 replay）。
- **SSE 实时推送**：Redis pub/sub channel `lifetree:risk:{user_id}` + `lifetree:scenario:{scenario_id}`，best-effort publish。
- **任务队列**：Celery Worker 处理长耗时预测任务；Celery Beat 定时触发 cron 抓取（`--schedule /tmp/celerybeat-schedule` 避免非 root 容器权限错误）；Flower 监控。

### 7.4 数据存储设计

- **PostgreSQL 16（pgvector）**：约 22 张核心表，覆盖以下域：
  - **用户与认证**：`user_profiles`（含 demographics/priority_factors/risk_tolerance/progress/implicit_tags/notify_channels/quiet_hours 等 JSONB 字段）/ `user_uploads`（含 user_credibility 状态机）/ `user_oauth_links` / `user_passkeys` / `user_plugins` / `user_memories`
  - **目标本体**：`goals` / `pathways`（含 milestones/eligibility）/ `requirements`（含 gap_status/gap_delta/weight）/ `risk_factors`（含 half_life_days）
  - **信息原子**：`information_sources` / `events`（含 `embedding Vector(1536)` + extraction_confidence + status 三态）/ `event_fingerprints`（sha256 去重）/ `metric_snapshots` / `assertions` / `relationships`
  - **情景与推理**：`scenarios`（含 success_probability/key_risk_factors/impact_threshold）/ `scenario_runs`（含 engine 类型与 iterations）
  - **通知与风险**：`notification_logs` / `risk_assessments` / `risk_propagation_logs`
  - **LLM 与平台配置**：`llm_providers` / `llm_models`（capabilities JSONB）/ `app_config`（key-value 存储 tavily/mineru/smtp/oauth_providers/use_mode 等）
  - 向量扩展：`events.embedding` 列支持 RAG 式“相似事件检索”和个性化知识库问答。
- **Neo4j 5.20**：
  - 核心本体实例：Goal / Pathway / Requirement / RiskFactor / Event / InformationSource / Scenario（7 类节点）。
  - 关系：`HAS_PATHWAY` / `REQUIRES` / `AFFECTS` / `EMITTED` / `BELONGS_TO` / `BRANCHES_FROM` / `SUPERSEDES`（7 类）。
  - 每个情景（Scenario）是独立的子图或带标签的分支，查询时按情景 ID 过滤。
  - `PROPAGATE_RISK_FROM_EVENT` Cypher 查询：从 Event 沿 `AFFECTS*0..4` 跳遍历到 Pathway/Goal，量化风险传播。
- **MinIO**：
  - 用户上传的原始文件（PDF，截图）。
  - LLM 中间处理结果备份。
- **Alembic 迁移**：8 个版本，从初始 schema 到 Passkey 设备类型字段扩容（VARCHAR(64)），entrypoint 脚本自动创建 pgvector 扩展后再运行迁移。

### 7.5 关键数据流

**信息流入与图谱更新流**：
1. Cron 触发 → `crawler_service` 调 Tavily/用户源 → 获取新文本。
2. 文本入 `structuring_service` → LLM 输出结构化事件（Pydantic）。
3. 事件推入 `Review Inbox` 暂存队列 → 用户收到审核通知或符合自动通过策略。
4. 用户确认后去重模块比对已存事件 → 写入 Neo4j 对应节点，建立关联。
5. 若事件带高风险标签，立刻触发 `notification_service` 扫描受影响用户并推送。
6. 异步触发 `reasoning_engine` 重算受影响目标的风险分与归因瀑布。

**用户互动与推演流**：
1. 用户通过 AI 顾问提问或点击“推演” → 请求到 FastAPI。
2. API 创建情景分支 → 在 Neo4j 中复制并修改相关节点。
3. 发送任务到 Celery 执行蒙特卡洛/贝叶斯推理。
4. 前端通过 SSE 或轮询获取计算进度和结果 → 在情景面板中对比（Diff View）。

### 7.6 部署与运维架构

**容器化部署**：Docker Compose 单栈编排，9 个服务 + 5 个命名卷。

| 服务 | 镜像 | 端口 | 说明 |
| :--- | :--- | :--- | :--- |
| postgres | pgvector/pgvector:pg16 | 15432:5432 | 主数据库，含 pgvector 扩展 |
| neo4j | neo4j:5.20 | 17687:7687 / 17474:7474 | 图数据库，含 APOC |
| redis | redis:7-alpine | 16379:16379 | Celery broker + SSE pub/sub（非默认端口避免冲突） |
| minio | minio/minio:latest | 19000:9000 / 19001:9001 | 对象存储 |
| backend | ghcr.io/caryk753/lifetree-backend | 18000:18000 | FastAPI + Uvicorn |
| worker | 同 backend | — | Celery Worker |
| beat | 同 backend | — | Celery Beat（`--schedule /tmp/celerybeat-schedule`） |
| flower | mher/flower:latest | 15555:5555 | Celery 任务监控 |
| frontend | ghcr.io/caryk753/lifetree-frontend | 13000（仅 expose） | Next.js 16 生产构建 |
| nginx | nginx:alpine | 80 → 统一入口 | 反向代理，SSE 流式转发 |

- **非默认端口策略**：所有暴露服务使用非默认端口（15432/17687/17474/16379/19000/19001/18000/13000/15555），避免共享服务器端口冲突。
- **GHCR 预构建镜像**：默认从 GitHub Container Registry 拉取，`docker compose up -d` 即可启动；本地构建需 `--build` 标志。
- **CI/CD 工作流**：
  - `build-and-push.yml`：push 到 main 或 `v*` tag 触发，构建 linux/amd64 镜像并推送 GHCR，GHA 缓存加速。
  - `release.yml`：`v*` tag 触发，从 `CHANGELOG.md` 提取对应版本段落作为 GitHub Release notes。
- **Healthcheck**：PostgreSQL/Neo4j/Redis/MinIO/Backend/Frontend 均配置 healthcheck；前端使用 `wget -q -O /dev/null` 避免 alpine 镜像 `--spider` 误报。
- **数据持久化**：5 个命名卷（postgres_data / neo4j_data / redis_data / minio_data / backend_plugins），跨重启保留。插件目录 `backend_plugins:/app/plugins/user_uploaded/` 持久化用户自定义脚本。

### 7.7 安全与权限模型

**双模式架构**：通过 `LIFETREE_USE_MODE` 环境变量 + DB `app_config.use_mode`（DB 优先）切换。

- **单用户模式（默认）**：无需登录，回退到默认用户（Alex Chen），适合个人自部署。
- **多用户模式**：强制登录，AuthGate 组件未认证不渲染 children；第一注册用户自动晋升 admin（`_should_promote_first_admin`）。

**Admin 权限**：
- 通过 `LIFETREE_ADMIN_USER_IDS` 环境变量配置，运行时 `_apply_admin_override` 动态注入（DB role 字段始终为 'user'，避免持久化敏感角色）。
- Admin 专属端点：`/admin/stats` / `/admin/users` CRUD + role/is_enabled/password 管理。
- 防自降级：最后一个 admin 不能自我降级、禁用或删除。
- 多用户模式下，普通用户无法查看 admin 配置的 API Key（设置页只读）。

**认证方式**：
- **邮箱+密码**：注册 + 验证码（admin 启用 `email_verification` 后强制）。
- **OAuth**：8 个预设供应商（GitHub / Google / Microsoft / GitLab / Discord / LinkedIn / Facebook / Apple）+ 自定义任意 OAuth2 供应商。state 防 CSRF（Redis 10 分钟 TTL），支持 login/register/bind 三模式。OAuth 头像不覆盖用户自定义字段（仅空时填充）。
- **Passkey（WebAuthn）**：discoverable credentials 免登录认证，多设备绑定，sign_count 单调递增防 replay。admin 启用 `passkey_login` 后用户可在 /profile 绑定。
- **JWT**：access token + refresh token，Bearer 模式。

**数据隔离**：所有业务表含 `user_id` 字段，按用户 ID 隔离；聊天会话本地存储按 `lifetree.chat.conversations.v2.<userId>` 分区。

**隐私防线**：
- 私有上传信息默认 `source=user_upload` + `user_credibility=pending`。
- 前端端侧脱敏预览（姓名、身份证号、账号遮蔽）。
- 法律免责强制确认。

### 7.8 插件系统

**定位**：允许用户上传自定义 Python 脚本扩展信源适配器（如 RSS 抓取、特定网站爬虫），无需修改主代码。

**安全沙箱**：
- **AST 语法检查**：`ast.parse` + 顶层 `class Plugin:` 识别 + `manifest`/`fetch` 静态方法校验。
- **导入黑名单**：`os` / `sys` / `subprocess` / `shutil` / `ctypes` / `socket` / `multiprocessing` / `importlib` / `pickle` / `marshal` / `pty` / `posix` / `nt` / `resource` 等。
- **危险调用检查**：`eval` / `exec` / `compile` / `__import__`。
- **契约验证**：`safe_import_for_validation` 临时文件加载 + 调用 `Plugin.manifest()` 验证返回 `PluginManifest` 类型。

**API 端点**：
- `POST /plugins/upload`：上传 + AST 检查 + 契约验证，文件名小写 snake_case `.py`，256 KiB 上限。
- `PATCH /plugins/{id}/enabled`：启停。
- `DELETE /plugins/{id}`：软删除（文件 + DB row + sys.modules 缓存）。
- `POST /plugins/{id}/run`：运行插件 `fetch()` 方法。

**持久化**：Docker named volume `backend_plugins:/app/plugins/user_uploaded/` 跨重启保留用户插件。

**内置示例**：`plugins/sample_rss_feed.py` + `plugins/sample_web_scraper.py`。

---

## 8. 开源与商业化策略

**核心理念**：开放核心，服务收费。用透明赢得信任，用服务赢得生意。

**开源部分（AGPLv3）**：
- 核心推理引擎（贝叶斯网络、蒙特卡洛模拟、分支管理、归因瀑布）
- 知识图谱本体与图谱构建工具
- 信源适配器框架
- LLM 结构化抽取管道与 Review Inbox
- 前端基础组件库（MIT）

**闭源部分（商业许可）**：
- 托管平台和自动运维
- 高级协作功能（家庭/顾问多用户协作）
- 场景模板市场官方认证付费模板
- 自研领域微调模型权重
- 官方信源可信度评级数据
- 企业级控制台与 API

**许可证选择**：核心仓库采用 **GNU AGPLv3**，防止云厂商直接封装成 SaaS 而不回馈代码。同时提供商业双授权，闭源需求单独购买。

---

## 9. 实施路线图

**第一阶段：核心原型与零门槛冷启动（MVP+）**
- 聚焦场景：**加拿大联邦技术移民（FSW）** 官方 Demo 模板。
- 实现基础信息抓取与结构化管道。
- 引入 **信息审核收件箱（Review Inbox）**，解决数据污染问题。
- 搭建基础知识图谱，实现 **时间线/甘特图主视图**。
- 提供基础风险预警（邮件通知）。
- **目标**：跑通数据闭环与开箱即用冷启动体验。

**第二阶段：白盒归因、分支推演与用户画像**
- 完成用户画像系统，实现个性化风险评分。
- 集成 **归因瀑布图（Attribution Waterfall）**，实现透明化推理因子解读。
- 实现 **情景差异对比看板（Diff View）** 与分支管理。
- 引入私域信息上传与 **场景模板市场** 框架。
- **目标**：实现多情景智能决策对比与白盒算法信任。

**第三阶段：预测引擎、无悔行动与协作生态**
- 集成贝叶斯网络和蒙特卡洛模拟，输出概率区间。
- 自动收敛输出 **“每周无悔微行动”**，增加里程碑点亮与打卡激励。
- 支持 **家庭/顾问加密只读与评论协同**。
- 推出 iOS/iPadOS 原生应用（PWA/Native），实现移动端推送。
- **目标**：产品走向成熟，形成抗焦虑的陪伴式决策系统。

**第四阶段：多场景扩展与商业化**
- 扩展官方模板：澳洲移民、英国留学、美国 H1B、数字游民规划、职业转型。
- 推出 B2B 顾问面板，赋能移民留学中介与规划师。
- 引入匿名社区洞察与模板共享生态，形成数据网络效应。
- 探索企业级许可证和国际市场。
- **目标**：成为个人中长期决策领域的标准平台。

---

## 10. 实施现状与已落地能力

**截至 2026-07-28**，LifeTree 已完成第一阶段全部目标与第二、三阶段主体能力，可投入实际使用。以下为对照路线图的实际进度盘点。

### 10.1 后端 API（19 个路由模块，全部已实现）

| 模块 | 关键端点 | 状态 |
| :--- | :--- | :--- |
| auth | register / login / refresh / me / config / oauth start/callback/bind / send-code / register-with-code | ✅ |
| passkey | registration/options/verify + auth/options/verify + list/delete | ✅ |
| admin | stats / users CRUD + role/is_enabled/password | ✅ |
| users | CRUD + 画像字段更新 | ✅ |
| goals | Goal/Pathway/Requirement/RiskFactor CRUD | ✅ |
| scenarios | CRUD + run/branch/merge/prune | ✅ |
| ingest | /ingest/text + /ingest/upload（Mineru 解析 + MinIO 存储） | ✅ |
| graph | /graph/{goal_id} 知识图谱快照 | ✅ |
| chat | /chat/stream SSE 流式 + LangGraph ReAct + 14 工具 | ✅ |
| notifications | list + unread-count + bulk-read + {id}/read | ✅ |
| dashboard | /dashboard/{goal_id} 目标罗盘聚合 | ✅ |
| sse | /sse Redis pub/sub 实时推送 | ✅ |
| settings | providers/models/roles/tavily/mineru/smtp/oauth/use-mode/email-verification/disable-registration/passkey-login/service-address/test 全套 | ✅ |
| plugins | /plugins + /plugins/upload + /plugins/{id} DELETE/PATCH/run | ✅ |
| memories | 用户记忆 CRUD | ✅ |
| lifecycle | distribution/events/refresh/archive/half-life/sweep | ✅ |
| events / risk_factors / crawler / system | 查询与管理端点 | ✅ |

### 10.2 前端页面（14 个路由，全部已实现）

| 路由 | 功能 | 状态 |
| :--- | :--- | :--- |
| / | 首页 | ✅ |
| /dashboard | 目标罗盘（含风险热力图/生存曲线/因子分解/无悔行动/里程碑） | ✅ |
| /goals + /goals/[id] | 目标管理 + 详情 | ✅ |
| /scenarios | 情景对比（树/网格/对比三视图 + 概率曲线 overlay） | ✅ |
| /chat | AI 顾问对话（SSE 流式 + Tool Call UI + 历史侧边栏） | ✅ |
| /sources | 信息源管理（含 DELETE + 确认弹窗） | ✅ |
| /notifications | 通知中心（severity/read 筛选） | ✅ |
| /profile | 用户画像（含 MemoryBoard + Passkey 绑定 + OAuth 绑定） | ✅ |
| /settings | 系统组件 + OAuth 绑定 + 主题 + 语言 + 关于 + 管理员快捷入口 | ✅ |
| /admin | 平台配置（供应商/模型/API Key/SMTP/OAuth providers/Auth settings + UseMode） | ✅ |
| /plugins | 插件管理（上传 + 启停 + 删除） | ✅ |
| /ingest | 信息录入 | ✅ |
| /graph | 知识图谱可视化（Cytoscape，节点可点击下钻） | ✅ |
| /auth + /auth/callback/[provider] | 登录注册（ASCII 动态树木背景 + 流星动画） | ✅ |

### 10.3 核心引擎落地状态

| 引擎 | 关键能力 | 状态 |
| :--- | :--- | :--- |
| 知识图谱 | 7 类节点 + 7 类关系 + PROPAGATE_RISK_FROM_EVENT 多跳遍历 + 双存储（PG 真相源 + Neo4j 镜像） | ✅ |
| 情景分支 | CRUD + branch/merge/prune + 概率曲线 overlay + 3 活跃分支限制 + 自动休眠 | ✅ |
| 风险预警 | email/in_app/sms(stub)/push + SSE + SMTP(SSL/STARTTLS) + 6h 冷却 + 安静时段 + Cruising Mode | ✅ |
| 结构化管道 | Instructor + Pydantic + sha256 去重 + 三态置信度分层 + Vector(1536) 嵌入 + 半衰期管理 | ✅ |
| 用户画像 | 完整字段 + ProfilingService 自动 refresh + 记忆板 + lifecycle_stage + joint_profiles | ✅ |
| AI 顾问 | LangGraph ReAct + 14 工具 + 100k token 截断 + 多样性记忆选取 + Tool Call 透明卡片 | ✅ |
| 蒙特卡洛/贝叶斯 | scenario_runs 表 + engine 类型字段（已搭骨架，深度模拟算法待业务校准） | 🟡 部分实现 |

### 10.4 部署与运维落地状态

| 能力 | 详情 | 状态 |
| :--- | :--- | :--- |
| Docker Compose | 9 服务 + 5 卷 + 非默认端口 + Nginx 统一入口 | ✅ |
| GitHub Actions | build-and-push.yml（GHCR 镜像）+ release.yml（CHANGELOG Release notes） | ✅ |
| GHCR 预构建镜像 | ghcr.io/caryk753/lifetree-backend / lifetree-frontend | ✅ |
| Healthcheck | 全服务配置 + 前端 wget -q -O /dev/null | ✅ |
| 数据持久化 | 5 命名卷 + 插件目录持久化 | ✅ |
| Alembic 迁移 | 8 个版本 + entrypoint 自动创建 pgvector 扩展 | ✅ |

### 10.5 安全与权限落地状态

| 能力 | 详情 | 状态 |
| :--- | :--- | :--- |
| 双模式 | single（默认用户回退）/ multi（强制登录） | ✅ |
| Admin 权限 | LIFETREE_ADMIN_USER_IDS 动态注入 + 防自降级 + 第一注册自动晋升 | ✅ |
| 邮箱+密码 | 注册 + 验证码（admin 启用后强制） | ✅ |
| OAuth | 8 预设（GitHub/Google/Microsoft/GitLab/Discord/LinkedIn/Facebook/Apple）+ 自定义 + 绑定/解绑 | ✅ |
| Passkey | WebAuthn discoverable credentials + 多设备 + sign_count 防 replay | ✅ |
| JWT | access + refresh token，Bearer 模式 | ✅ |
| 数据隔离 | user_id 字段 + 聊天分区存储 | ✅ |
| 隐私防线 | 端侧脱敏 + 法律免责 + user_credibility 状态机 | ✅ |

### 10.6 国际化与无障碍落地状态

| 能力 | 详情 | 状态 |
| :--- | :--- | :--- |
| i18n | 6 语言（zh-CN/zh-TW/en/es/de/fr），cookie 驱动 + 自动检测 + zh-CN 回退 | ✅ |
| PWA | manifest + Service Worker + 抽屉式侧边栏 + shortcuts + iOS 适配 | ✅ |
| 主题 | 亮色/暗色/系统三态 + prefers-reduced-motion 支持 | ✅ |
| 无障碍 | ECharts/Cytoscape aria-label + 键盘导航 + 焦点管理 | ✅ |

### 10.7 待完善项

- **SMS 通道**：目前为 stub，需接入真实网关（如 Twilio / 阿里云短信）。
- **移动端原生**：当前依赖 PWA，SwiftUI 原生 iOS/iPadOS 待规划。
- **B2B 顾问面板**：尚未启动。
- **匿名社区洞察**：尚未启动。
- **深度模拟算法**：scenario_runs 表与 engine 类型已搭骨架，蒙特卡洛/贝叶斯参数校准需结合真实场景迭代。
- **场景模板市场**：框架已就绪，官方模板仅 FSW + OINP/PNP/CEC 多路径种子，待扩展。

---

*LifeTree，让每一个重大人生选择，都有迹可循，有枝可依。*

