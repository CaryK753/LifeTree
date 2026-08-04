# 桌面端打包端到端验证

- 日期：2026-07-31
- 作者：wwj
- 状态：已完成
- 关联：`docs/tasks/desktop-foundation-2026-07-30.md`、
  `docs/specs/2026-07-30-local-storage-foundation.md`

## 背景

`desktop_bundle` 是 `local_private_ready` 的最后一个 `pending` 适配器。打包
基础设施已完整：

- `backend/scripts/build_desktop_sidecar.py`：PyInstaller 打包 sidecar 二进制
  到 `desktop/src-tauri/binaries/`。
- `desktop/scripts/build-web.mjs`：Next.js 静态导出 + launcher Vite 构建。
- `desktop/src-tauri/tauri.conf.json`：启用完整安装包构建；未配置发布签名时
  使用本机 ad-hoc 签名验证 macOS 安装包。
- `desktop/src-tauri/src/runtime_process.rs`：Tauri 宿主查找 sidecar 二进制、
  用 `--port --data-dir` 启动、轮询 `/health` 直到就绪。

但缺少端到端验证：sidecar 入口点 `app/desktop_sidecar.py` 能否真正启动并响应
健康检查，特别是在新增了加密机制后（`initialize_local_database()` 现在调用
`ensure_encryption_available()`，keyring 不可用会中止启动）。

## 目标

- 验证 sidecar 入口点的完整启动链路：参数解析 → 环境变量设置 → app 创建 →
  uvicorn 启动 → 健康检查响应。
- 验证 sidecar 与加密机制兼容：有 `LIFETREE_LOCAL_ENCRYPTION_KEY` 时正常启动。
- 验证 sidecar 的 token 认证：无 token 的请求被拒绝，有 token 的请求通过。
- 将 `desktop_bundle` 状态从 `pending` 改为 `ready`。

## 非目标

- 不涉及对外分发所需的 Developer ID / Windows 代码签名；正式发布仍需在 CI
  注入相应证书。
- 不测试 PyInstaller 打包后的二进制本身（慢且依赖构建环境）；测试直接运行
  `app.desktop_sidecar` 模块，验证入口点逻辑。

## 验证方案

新增 `tests/test_desktop_sidecar.py`，用子进程启动 sidecar：

1. 设置 `LIFETREE_DESKTOP_TOKEN`（32+ 字符）和 `LIFETREE_LOCAL_ENCRYPTION_KEY`。
2. 分配空闲端口，用 `subprocess.Popen` 启动
   `python -m app.desktop_sidecar --port {port} --data-dir {tmp_path}`。
3. 轮询 `GET /health` 直到返回 200 或超时（30s）。
4. 验证：
   - `/health` 返回 `{"status": "ok"}`。
   - `/api/v1/runtime/capabilities` 无 token 返回 401。
   - 带 token 的 `/api/v1/runtime/capabilities` 返回 200 且
     `local_private_ready=true`。
5. 清理：终止子进程。

## 完成结果

- `tests/test_desktop_sidecar.py` 验证 sidecar 端到端启动、健康检查、token
  认证和 `local_private_ready` 状态。
- `desktop_bundle` 适配器状态从 `pending` 改为 `ready`。
- `local_private_ready` 现在返回 `true`（所有适配器均 ready）。
- `desktop/README.md` 更新反映 `local_private` 已可用。

## 边界

- 本机已可生成 `.dmg`；对外发布仍需 Developer ID / Windows 代码签名。
- sidecar 在无 keyring 的桌面环境（headless Linux）需设置
  `LIFETREE_LOCAL_ENCRYPTION_KEY` env var 才能启动；macOS/Windows 桌面环境
  通过 OS Keychain / Credential Manager 自动管理密钥。
- `bundle.active=true`，CI 同时验证桌面端构建与安装包流程。

## 验证

- `tests/test_desktop_sidecar.py` 端到端测试通过。
- 后端全量测试通过。
- `local_private_ready=true` 由 capabilities 端点确认。
