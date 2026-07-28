# LifeTree 产品审计与认证修复

- 日期：2026-07-28
- 状态：已完成
- 作者：wwj

## TODO

- [x] 对照项目计划书与现有前后端能力，记录未实现项和普通用户体验问题
- [x] 审查 single / multi 模式逻辑并提出可执行改进
- [x] 评估 SQLite 本地桌面模式与 Ollama 模型协议
- [x] 修复 Profile OAuth 绑定状态不刷新
- [x] 修复 OAuth 注册后头像和邮箱缺失
- [x] 阻止 Auth 未登录页面频繁请求受保护接口
- [x] 完成受影响范围内的类型检查、后端测试或静态验证

## 约束

- 保留工作树中已有的未提交改动。
- 只对完成本任务所需的文件进行最小修改。
- 不通过全局 skip / ignore / disable 配置掩盖错误。

## 结论记录

完整结论见 `docs/现状审计与改进建议-2026-07-28.md`。

- OAuth 身份归一化单测：3 项通过。
- Python compileall：通过。
- 新增前端文件未产生 TypeScript 错误；全仓 type-check 仍被既有场景、sources 与 Cytoscape 错误阻塞。
- ESLint 9 配置存在循环结构错误，命令在加载配置阶段失败。
