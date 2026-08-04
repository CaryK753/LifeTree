# LifeTree Desktop

LifeTree 桌面端采用 Tauri 2。当前阶段提供运行模式启动器和远程服务连接。
本地运行时已具备 SQLite（含 schema 迁移与字段加密）、文件 BlobStore、进程内
任务执行器、嵌入式图、向量搜索和 sidecar 端到端验证；`local_private` 模式
已可用。

## 开发环境

- Node.js 22+
- Rust stable
- macOS：Xcode Command Line Tools
- Windows：Microsoft C++ Build Tools 与 WebView2

安装和检查：

```bash
npm --prefix desktop install
npm --prefix desktop run check
```

启动桌面开发窗口：

```bash
npm --prefix desktop run dev
```

生成无安装包的 release 二进制，用于快速验证宿主和前端资源：

```bash
npm --prefix desktop run build -- --no-bundle
```

## 安全边界

- 自托管和云端地址只允许 HTTPS；本机回环地址允许 HTTP，便于本地开发。
- 地址中禁止用户名、密码、查询参数和 URL 片段。
- 只有本地 `bootstrap` 窗口拥有 Tauri capability；打开的远程页面不在权限列表中。
- 桌面配置不保存模型 API Key。后续密钥通过系统 Keychain/Credential Manager 管理。
