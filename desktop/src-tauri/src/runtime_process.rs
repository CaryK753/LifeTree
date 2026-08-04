//! Python worker 进程管理 + 后台健康轮询。
//!
//! 与旧版的区别：
//! - `start()` 不再阻塞等待健康检查，立即返回端口和 token
//! - 健康轮询在后台异步执行，更新 `ready` 标志
//! - `RuntimeSupervisor` 持有 `Arc<AtomicBool>` 就绪标志，供 axum 代理层读取

use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{AppHandle, Manager};

const HEALTH_POLL_INTERVAL: Duration = Duration::from_millis(300);
const HEALTH_CHECK_TIMEOUT: Duration = Duration::from_millis(150);

/// axum 代理层使用的 worker 连接信息。
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeEndpoint {
    pub api_base_url: String,
    pub desktop_token: String,
}

/// Python worker 启动后的连接信息。
pub struct WorkerInfo {
    pub port: u16,
    pub token: String,
}

/// Python worker 进程信息。
struct WorkerProcess {
    child: Child,
    port: u16,
    token: String,
}

impl Drop for WorkerProcess {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// 运行时监管器：管理 Python worker 进程 + 就绪状态。
#[derive(Clone, Default)]
pub struct RuntimeSupervisor {
    process: Arc<Mutex<Option<WorkerProcess>>>,
    ready: Arc<AtomicBool>,
}

impl RuntimeSupervisor {
    pub fn is_running(&self) -> bool {
        let Ok(mut guard) = self.process.lock() else {
            return false;
        };
        let Some(process) = guard.as_mut() else {
            return false;
        };
        match process.child.try_wait() {
            Ok(None) => true,
            Ok(Some(_)) | Err(_) => {
                guard.take();
                self.ready.store(false, Ordering::Relaxed);
                false
            }
        }
    }

    pub fn is_ready(&self) -> bool {
        self.ready.load(Ordering::Relaxed)
    }

    /// 获取就绪标志的 Arc 引用（供 axum 代理层共享）。
    pub fn ready_flag(&self) -> Arc<AtomicBool> {
        self.ready.clone()
    }

    /// 启动 Python worker（非阻塞）。
    ///
    /// 立即返回 worker 端口和 token，不等待健康检查。后台异步轮询 `/health`，
    /// 通过后设置 `ready` 标志。axum 代理层在 `ready` 为 true 后开始转发。
    pub fn start(&self, executable: &Path, data_dir: &Path) -> Result<WorkerInfo, String> {
        let mut guard = self
            .process
            .lock()
            .map_err(|_| "本地运行时状态锁已损坏".to_owned())?;

        // 若已有进程在运行，直接返回
        if let Some(process) = guard.as_mut() {
            if process
                .child
                .try_wait()
                .map_err(|error| error.to_string())?
                .is_none()
            {
                return Ok(WorkerInfo {
                    port: process.port,
                    token: process.token.clone(),
                });
            }
            guard.take();
        }

        std::fs::create_dir_all(data_dir)
            .map_err(|error| format!("创建本地数据目录失败：{error}"))?;

        // stdout/stderr 写入日志文件
        let log_path = data_dir.join("worker.log");
        let log_file = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(true)
            .open(&log_path)
            .map_err(|error| format!("无法创建 worker 日志文件：{error}"))?;
        let err_file = log_file
            .try_clone()
            .map_err(|error| format!("无法复制 worker 日志句柄：{error}"))?;

        let port = reserve_loopback_port()?;
        let token = generate_token()?;
        let mut command = Command::new(executable);
        command
            .arg("--port")
            .arg(port.to_string())
            .arg("--data-dir")
            .arg(data_dir)
            .env("LIFETREE_DESKTOP_TOKEN", &token)
            .env(
                "LIFETREE_DESKTOP_PARENT_PID",
                std::process::id().to_string(),
            )
            .stdin(Stdio::null())
            .stdout(Stdio::from(log_file))
            .stderr(Stdio::from(err_file));

        // Windows: prevent the sidecar (PyInstaller console binary) from
        // popping up a cmd.exe window. Without this flag the console
        // window stays open and closing it kills the backend process.
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let child = command
            .spawn()
            .map_err(|error| format!("启动 Python worker 失败：{error}"))?;

        *guard = Some(WorkerProcess {
            child,
            port,
            token: token.clone(),
        });
        drop(guard);

        // 重置就绪标志
        self.ready.store(false, Ordering::Relaxed);

        // 后台异步轮询健康检查
        let ready = self.ready.clone();
        let process_lock = self.process.clone();
        let port_copy = port;
        tauri::async_runtime::spawn(async move {
            let deadline = Instant::now() + Duration::from_secs(60);
            while Instant::now() < deadline {
                // 检查进程是否已退出
                if let Ok(mut guard) = process_lock.lock() {
                    if let Some(p) = guard.as_mut() {
                        match p.child.try_wait() {
                            Ok(Some(_)) => {
                                guard.take();
                                ready.store(false, Ordering::Relaxed);
                                eprintln!("Python worker 已退出，就绪检查终止");
                                return;
                            }
                            Err(_) => {
                                guard.take();
                                ready.store(false, Ordering::Relaxed);
                                return;
                            }
                            Ok(None) => {}
                        }
                    } else {
                        return;
                    }
                } else {
                    return;
                }

                if health_check_sync(port_copy) {
                    ready.store(true, Ordering::Relaxed);
                    eprintln!("Python worker 已就绪（端口 {port_copy}）");
                    return;
                }
                tokio::time::sleep(HEALTH_POLL_INTERVAL).await;
            }
            eprintln!("Python worker 健康检查超时（端口 {port_copy}）");
        });

        Ok(WorkerInfo { port, token })
    }
}

pub fn sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let binary_name = if cfg!(windows) {
        "lifetree-sidecar.exe"
    } else {
        "lifetree-sidecar"
    };
    let current = std::env::current_exe().map_err(|error| error.to_string())?;
    let mut candidates = Vec::new();
    if let Some(parent) = current.parent() {
        candidates.push(parent.join(binary_name));
    }
    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.push(resource_dir.join(binary_name));
    }
    candidates.push(
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("binaries")
            .join(format!(
                "lifetree-sidecar-{}{}",
                target_triple(),
                exe_suffix()
            )),
    );
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| "未找到本地运行时 sidecar".to_owned())
}

pub fn prepared_sidecar_path(app: &AppHandle, data_dir: &Path) -> Result<PathBuf, String> {
    let Some(source_dir) = bundled_runtime_dir(app) else {
        return sidecar_path(app);
    };
    let version = app.package_info().version.to_string();
    let install_dir = data_dir
        .parent()
        .ok_or("本地数据目录无效")?
        .join("sidecar-runtime")
        .join(version);
    let executable = install_dir.join(sidecar_binary_name());
    if executable.is_file() {
        return Ok(executable);
    }

    let staging_dir = install_dir.with_extension("installing");
    let _ = std::fs::remove_dir_all(&staging_dir);
    copy_runtime_tree(&source_dir, &staging_dir)?;
    if let Some(parent) = install_dir.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|error| format!("创建 sidecar 运行时目录失败：{error}"))?;
    }
    let _ = std::fs::remove_dir_all(&install_dir);
    std::fs::rename(&staging_dir, &install_dir)
        .map_err(|error| format!("安装 sidecar 运行时失败：{error}"))?;
    Ok(executable)
}

fn bundled_runtime_dir(app: &AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    [
        resource_dir.join("sidecar-runtime"),
        resource_dir.join("resources/sidecar-runtime"),
        resource_dir.join("_up_/resources/sidecar-runtime"),
    ]
    .into_iter()
    .find(|path| path.join(sidecar_binary_name()).is_file())
}

fn copy_runtime_tree(source: &Path, destination: &Path) -> Result<(), String> {
    std::fs::create_dir_all(destination)
        .map_err(|error| format!("创建 sidecar 临时目录失败：{error}"))?;
    for entry in std::fs::read_dir(source)
        .map_err(|error| format!("读取 sidecar 运行时文件失败：{error}"))?
    {
        let entry = entry.map_err(|error| error.to_string())?;
        let target = destination.join(entry.file_name());
        let kind = entry.file_type().map_err(|error| error.to_string())?;
        if kind.is_dir() {
            copy_runtime_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            std::fs::copy(entry.path(), &target)
                .map_err(|error| format!("复制 sidecar 运行时文件失败：{error}"))?;
            #[cfg(unix)]
            {
                let permissions = std::fs::metadata(entry.path())
                    .map_err(|error| error.to_string())?
                    .permissions();
                std::fs::set_permissions(&target, permissions)
                    .map_err(|error| format!("设置 sidecar 文件权限失败：{error}"))?;
            }
        }
    }
    Ok(())
}

fn sidecar_binary_name() -> &'static str {
    if cfg!(windows) {
        "lifetree-sidecar.exe"
    } else {
        "lifetree-sidecar"
    }
}

fn reserve_loopback_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .map_err(|error| format!("无法分配本地端口：{error}"))?;
    listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("无法读取本地端口：{error}"))
}

fn generate_token() -> Result<String, String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| format!("生成会话令牌失败：{error}"))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

/// 同步健康检查（在 async 上下文中通过 spawn_blocking 调用）。
fn health_check_sync(port: u16) -> bool {
    let address = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), port);
    let Ok(mut stream) = TcpStream::connect_timeout(&address, HEALTH_CHECK_TIMEOUT) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(HEALTH_CHECK_TIMEOUT));
    let request =
        format!("GET /health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = [0_u8; 64];
    matches!(stream.read(&mut response), Ok(size) if response[..size].starts_with(b"HTTP/1.1 200"))
}

#[cfg(target_os = "macos")]
fn target_triple() -> &'static str {
    if cfg!(target_arch = "aarch64") {
        "aarch64-apple-darwin"
    } else {
        "x86_64-apple-darwin"
    }
}

#[cfg(target_os = "windows")]
fn target_triple() -> &'static str {
    "x86_64-pc-windows-msvc"
}

fn exe_suffix() -> &'static str {
    if cfg!(windows) {
        ".exe"
    } else {
        ""
    }
}
