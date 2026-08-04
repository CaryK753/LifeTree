# 桌面端签名自动更新

- 日期：2026-08-03
- 作者：wwj
- 状态：待发布验收

## 目标

- GitHub Release 同时发布安装包、已签名的更新包和 `latest.json`。
- 桌面端在后台检查更新，验证签名后下载，重启时安装新版本。
- 更新私钥只保存于本机受限目录及 GitHub Actions Secret，仓库只保留公钥。

## TODO

- [x] 生成专用更新密钥，并将私钥写入 GitHub Secret `TAURI_SIGNING_PRIVATE_KEY`。
- [x] 接入 Tauri updater 插件和后台安装逻辑。
- [x] 更新 GitHub Release 工作流以发布签名更新清单。
- [x] 用本地签名密钥构建并验证 updater 产物。

## 安全边界

- 私钥位于 `~/Library/Application Support/com.lifetree.desktop/`，文件权限为 `0600`；不会提交到仓库。
- 正式 macOS 公网分发仍应在 CI 注入 Apple Developer ID 签名和公证凭据；Tauri updater 的签名用于验证更新包完整性，不替代 Gatekeeper 公证。

## 验证

- `cargo test --manifest-path desktop/src-tauri/Cargo.toml` 和 `cargo clippy --all-targets -- -D warnings` 通过。
- `npm --prefix desktop run build` 在显式提供私钥及空密码时生成 `LifeTree.app.tar.gz` 和对应 `.sig`。
- Release 工作流已校验 `vX.Y.Z` 标签必须与 `tauri.conf.json` 版本一致，并在矩阵构建完成后生成 `latest.json`。
- 首次推送版本标签后，需用 GitHub Release 实际资产验证 macOS 与 Windows 的远程下载、签名校验和重启安装。
