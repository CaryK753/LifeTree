# 桌面端启动与发布加固

- 日期：2026-08-03
- 作者：wwj
- 状态：已完成

## 目标

- 修复桌面 CI 缺少前端构建依赖的问题。
- 保持已启动 Python worker 的会话 token，不在实例切换后生成无效 token。
- 收紧本地 axum 代理的跨域来源。
- 用 PyInstaller `onedir` 运行时载荷消除后续启动的单文件解包等待。

## TODO

- [x] 修复 CI 的前端依赖安装与缓存路径。
- [x] 修复 worker token 复用、代理跨域策略和代理路由兼容性。
- [x] 打包并安装 `onedir` sidecar 运行时载荷。
- [x] 避免本地 worker 就绪前业务页抢先发起请求，并移除路由切换的透明度闪烁。
- [x] 验证本地模式的 sidecar 启动、SSE 首包和桌面安装包内容。

## 2026-08-03 更新

- 启动器不再显示模型配置；本地模式的模型设置收敛到应用内设置页。
- “本地服务可用”只由已打包的 sidecar 判断，worker 是否正在运行仍作为运行态信息展示。
- 桌面宿主限制为单实例，避免两个 worker 同时写入同一份本地 SQLite 数据。
- sidecar 监视桌面宿主 PID，宿主异常退出后自行终止，避免孤立 worker 持有本地数据。
- 本地模式的 SSE 使用心跳流，不再尝试连接仅部署版需要的 Redis。
- 运行时载荷以应用版本为目录缓存，正式发布时必须递增桌面应用版本；后续可增加载荷 manifest 校验以支持同版本热修复。

## 验证

- `backend/.venv/bin/pytest backend/tests/test_desktop_sidecar.py backend/tests/test_desktop_security.py backend/tests/test_local_storage_foundation.py backend/tests/test_local_runtime_adapters.py -q`
  通过（16 项）。
- `npm --prefix frontend run type-check`、`npm --prefix frontend run build:desktop`、`cargo test`、`cargo clippy -- -D warnings` 通过。
- `npm --prefix desktop run build` 生成并验证 macOS `.app` 和 `.dmg` 的 ad-hoc 签名。
