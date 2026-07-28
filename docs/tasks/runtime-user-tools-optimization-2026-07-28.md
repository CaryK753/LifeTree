# LifeTree 运行模式、用户服务与工具扩展优化

- 日期：2026-07-28
- 状态：已完成（SQLite 仓储适配器转后续里程碑）
- 作者：wwj

## 已确认产品规则

- [x] single 模式也必须注册账号，首个账号自动成为管理员。
- [x] single 等价于禁止新增注册的单实例模式；本地存储仅允许 single。
- [x] multi 必须使用全量服务部署，首个注册账号自动成为管理员。
- [x] 管理员可决定普通用户能否配置自己的 LLM、Tavily、MinerU 服务。
- [x] 管理员服务对普通用户只显示可用标识，不暴露密钥或编辑入口。
- [x] 普通用户的服务、默认模型、MCP、Skills 必须按用户隔离。
- [x] 聊天支持按会话选模型，并按供应商分组。
- [x] 所有“智能助手”用户文案统一为“智能助手”。
- [x] MCP 支持 HTTP、SSE、stdio；Skills 支持文本、压缩包、文件夹、GitHub 浅克隆。
- [x] 更新 README 与部署说明。

## 安全边界

- MCP stdio 命令不接受任意 shell 字符串，使用命令与参数数组并设置超时。
- 压缩包和文件夹导入必须阻止路径穿越、符号链接逃逸和超量解压。
- GitHub 导入只允许 HTTP(S) 仓库地址，使用浅克隆并限制大小与超时。
- 普通用户不能读取或覆盖管理员密钥；用户配置按 `user_id` 强隔离。
- Skills 内容作为用户提供的上下文，不得覆盖系统安全规则。

## 实施记录

- 新增 `user_service_configs`、`user_mcp_servers`、`user_skills` 及 Alembic 迁移。
- 两种运行模式都取消匿名 default-user 回退；single 首账号创建后由服务端强制禁止注册。
- 普通用户私有模型目录与管理员模型公开目录合并展示，密钥和管理员地址不出服务端。
- 私有 Tavily 用于智能助手 Web 工具，私有 MinerU 用于当前用户上传解析；未配置时回退管理员服务。
- 聊天请求新增 `model_id`，后端验证模型归属与 chat 能力；前端使用 AI Elements ModelSelector 交互并按供应商分组。
- `@lobehub/icons` 增加 Ollama、Qwen 与模型名称自动匹配。
- MCP 实现 Streamable HTTP、旧 SSE 和 stdio 的初始化、工具发现/调用流程；stdio 不经过 shell。
- Skills 四类导入均限制 2 MiB，并检查路径穿越、符号链接和 GitHub HTTPS 来源。
- `/auth` 更新圆月、右向左流星、高路灯和坐姿人物；认证页无 token 时不再请求 `/auth/me`。
- SQLite 仅确定为 single 专属方向。当前 ORM、pgvector 与 Neo4j 同步仍依赖 PostgreSQL，全量本地仓储适配器不在本次伪装为已完成。

## 验证记录

- Alembic `upgrade head` 成功应用到 `a6b8d0f2c4e6`。
- 后端测试：`7 passed`。
- 新增后端模块 Ruff：通过。
- 前端 `tsc --noEmit`：通过。
- 前端生产构建：通过，20 个路由全部生成成功。
- 匿名接口烟测：`/auth/config` 返回 200，`/auth/me` 与 `/settings/runtime/catalog` 返回 401。
