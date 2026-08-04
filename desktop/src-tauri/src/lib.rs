use std::fs;
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    window::Color,
    ActivationPolicy, AppHandle, Manager, State, Theme, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;
use url::Url;

mod desktop_server;
mod runtime_process;

use desktop_server::{DesktopServer, WorkerTarget};
use runtime_process::{
    prepared_sidecar_path, sidecar_path, RuntimeEndpoint, RuntimeSupervisor, WorkerInfo,
};

// 托盘图标变体（编译时嵌入二进制）
#[cfg(not(target_os = "macos"))]
const TRAY_ICON_LIGHT: &[u8] = include_bytes!("../icons/tray-light-64.png");
#[cfg(not(target_os = "macos"))]
const TRAY_ICON_DARK: &[u8] = include_bytes!("../icons/tray-dark-64.png");
const TRAY_ICON_WHITE: &[u8] = include_bytes!("../icons/tray-white-64.png");
#[allow(dead_code)]
const TRAY_ICON_CLEAR_DARK: &[u8] = include_bytes!("../icons/tray-cleardark-64.png");

/// macOS 菜单栏固定使用白色图标；Windows 托盘遵循系统主题。
#[cfg(target_os = "macos")]
fn tray_icon_for_theme(_theme: Theme) -> &'static [u8] {
    TRAY_ICON_WHITE
}

#[cfg(not(target_os = "macos"))]
fn tray_icon_for_theme(theme: Theme) -> &'static [u8] {
    match theme {
        Theme::Dark => TRAY_ICON_DARK,
        _ => TRAY_ICON_LIGHT,
    }
}

/// 更新托盘图标以匹配当前系统主题。
fn update_tray_icon(app: &AppHandle) {
    let theme = app
        .get_webview_window("bootstrap")
        .or_else(|| app.get_webview_window("lifetree"))
        .and_then(|w| w.theme().ok())
        .unwrap_or(Theme::Light);
    let icon_bytes = tray_icon_for_theme(theme);
    if let Ok(image) = tauri::image::Image::from_bytes(icon_bytes) {
        if let Some(tray) = app.tray_by_id("lifetree-tray") {
            let _ = tray.set_icon(Some(image));
        }
    }
}
const CONFIG_FILE: &str = "desktop-runtime.json";
const LOCALE_FILE: &str = "desktop-locale.json";

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum RuntimeMode {
    LocalPrivate,
    SelfHosted,
    CloudMultiTenant,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum ModelRuntime {
    ServerManaged,
    Ollama,
    LlamaCpp,
    OpenaiCompatible,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
struct RuntimeConfig {
    version: u16,
    mode: RuntimeMode,
    service_url: String,
    model_runtime: ModelRuntime,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct LocalRuntimeStatus {
    sidecar_present: bool,
    running: bool,
    ready: bool,
    available: bool,
}

/// 桌面端服务器状态：管理 axum 代理服务器和 worker 目标。
#[derive(Clone, Default)]
struct DesktopServerState {
    /// axum 代理服务器的端口（0 表示未启动）。
    server_port: Arc<std::sync::atomic::AtomicU16>,
    /// worker 代理目标（None 表示未配置）。
    worker_target: Arc<tokio::sync::RwLock<Option<WorkerTarget>>>,
    /// axum 服务器句柄（用于 shutdown）。
    server_handle: Arc<std::sync::Mutex<Option<DesktopServer>>>,
}

/// 启动本地运行时：axum 代理服务器 + Python worker。
///
/// axum 服务器在毫秒级内启动，Python worker 在后台异步启动。
/// 返回的 `RuntimeEndpoint` 中 `api_base_url` 指向 axum 服务器
/// （而非 Python worker），前端通过 axum 代理访问 worker。
async fn start_local_runtime_impl(
    app: AppHandle,
    supervisor: RuntimeSupervisor,
    server_state: DesktopServerState,
) -> Result<RuntimeEndpoint, String> {
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("无法确定本地数据目录：{error}"))?
        .join("local-runtime");
    let executable = prepared_sidecar_path(&app, &data_dir)?;

    // 1. 启动 Python worker（非阻塞，后台异步健康轮询）
    let supervisor_for_blocking = supervisor.clone();
    let worker_info: WorkerInfo = tauri::async_runtime::spawn_blocking(move || {
        supervisor_for_blocking.start(&executable, &data_dir)
    })
    .await
    .map_err(|error| format!("本地运行时任务失败：{error}"))??;

    // 2. 设置 axum 代理目标
    let target = WorkerTarget {
        port: worker_info.port,
        ready: supervisor.ready_flag(),
    };
    *server_state.worker_target.write().await = Some(target);

    // 3. 启动 axum 代理服务器（如果尚未启动）
    let current_port = server_state.server_port.load(Ordering::Relaxed);
    if current_port == 0 {
        let proxy_port = reserve_proxy_port()?;
        let server = DesktopServer::start(proxy_port, server_state.worker_target.clone()).await?;
        server_state
            .server_port
            .store(server.addr.port(), Ordering::Relaxed);
        *server_state.server_handle.lock().unwrap() = Some(server);
    }

    // 4. 返回 axum 服务器的 endpoint（前端连接到 axum，不是直接连 worker）
    let port = server_state.server_port.load(Ordering::Relaxed);
    Ok(RuntimeEndpoint {
        api_base_url: format!("http://127.0.0.1:{port}"),
        desktop_token: worker_info.token,
    })
}

fn reserve_proxy_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, 0))
        .map_err(|error| format!("无法分配代理端口：{error}"))?;
    let port = listener
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("无法读取代理端口：{error}"))?;
    drop(listener);
    Ok(port)
}

fn config_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join(CONFIG_FILE))
        .map_err(|error| format!("无法确定配置目录：{error}"))
}

fn locale_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join(LOCALE_FILE))
        .map_err(|error| format!("无法确定配置目录：{error}"))
}

#[derive(Deserialize, Serialize)]
struct LocaleConfig {
    locale: String,
}

/// 读取已保存的语言设置，未设置时返回 None。
#[tauri::command]
fn load_locale(app: AppHandle) -> Result<Option<String>, String> {
    let path = locale_path(&app)?;
    if !path.exists() {
        return Ok(None);
    }
    let content = fs::read_to_string(path).map_err(|e| format!("读取语言设置失败：{e}"))?;
    let config: LocaleConfig =
        serde_json::from_str(&content).map_err(|e| format!("语言设置格式错误：{e}"))?;
    Ok(Some(config.locale))
}

/// 保存语言设置。
#[tauri::command]
fn save_locale(app: AppHandle, locale: String) -> Result<(), String> {
    let supported = ["zh-CN", "zh-TW", "en", "es", "de", "fr"];
    if !supported.contains(&locale.as_str()) {
        return Err(format!("不支持的语言：{locale}"));
    }
    let path = locale_path(&app)?;
    let parent = path.parent().ok_or("配置目录无效")?;
    fs::create_dir_all(parent).map_err(|e| format!("创建配置目录失败：{e}"))?;
    let config = LocaleConfig { locale };
    let content = serde_json::to_vec_pretty(&config).map_err(|e| e.to_string())?;
    fs::write(path, content).map_err(|e| format!("保存语言设置失败：{e}"))?;
    Ok(())
}

fn validate_config(mut config: RuntimeConfig) -> Result<RuntimeConfig, String> {
    if config.version != 1 {
        return Err("不支持的桌面配置版本".into());
    }
    if config.mode == RuntimeMode::LocalPrivate {
        if config.model_runtime != ModelRuntime::ServerManaged {
            return Err("请进入本地服务后配置模型运行时".into());
        }
        config.service_url.clear();
        return Ok(config);
    }
    if config.model_runtime != ModelRuntime::ServerManaged {
        return Err("远程模式的模型应由所连接的服务管理".into());
    }

    let url = Url::parse(config.service_url.trim()).map_err(|_| "服务地址无效")?;
    let is_loopback = matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "::1"));
    if url.scheme() != "https" && !(url.scheme() == "http" && is_loopback) {
        return Err("服务地址必须使用 HTTPS；本机回环地址可使用 HTTP".into());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("服务地址不能包含用户名或密码".into());
    }
    if url.query().is_some() || url.fragment().is_some() {
        return Err("服务地址不能包含查询参数或片段".into());
    }
    if url.path() != "/" && !url.path().is_empty() {
        return Err("服务地址必须指向 LifeTree 站点根目录".into());
    }

    config.service_url = url.as_str().trim_end_matches('/').to_owned();
    Ok(config)
}

#[tauri::command]
fn local_runtime_status(
    app: AppHandle,
    window: WebviewWindow,
    supervisor: State<'_, RuntimeSupervisor>,
) -> Result<LocalRuntimeStatus, String> {
    ensure_bootstrap_window(&window)?;
    let sidecar_present = sidecar_path(&app).is_ok();
    let running = supervisor.is_running();
    let ready = supervisor.is_ready();
    Ok(LocalRuntimeStatus {
        sidecar_present,
        running,
        ready,
        available: sidecar_present,
    })
}

#[tauri::command]
async fn start_local_runtime(
    app: AppHandle,
    window: WebviewWindow,
    supervisor: State<'_, RuntimeSupervisor>,
    server_state: State<'_, DesktopServerState>,
) -> Result<RuntimeEndpoint, String> {
    ensure_bootstrap_window(&window)?;
    let endpoint = start_local_runtime_impl(
        app,
        supervisor.inner().clone(),
        server_state.inner().clone(),
    )
    .await?;
    Ok(endpoint)
}

#[tauri::command]
fn load_runtime_config(app: AppHandle) -> Result<Option<RuntimeConfig>, String> {
    let path = config_path(&app)?;
    if !path.exists() {
        return Ok(None);
    }
    let content = fs::read_to_string(path).map_err(|error| format!("读取配置失败：{error}"))?;
    let config =
        serde_json::from_str(&content).map_err(|error| format!("配置格式错误：{error}"))?;
    Ok(Some(config))
}

#[tauri::command]
fn save_runtime_config(
    app: AppHandle,
    window: WebviewWindow,
    config: RuntimeConfig,
) -> Result<RuntimeConfig, String> {
    ensure_bootstrap_window(&window)?;
    let config = validate_config(config)?;
    let path = config_path(&app)?;
    let parent = path.parent().ok_or("配置目录无效")?;
    fs::create_dir_all(parent).map_err(|error| format!("创建配置目录失败：{error}"))?;
    let content = serde_json::to_vec_pretty(&config).map_err(|error| error.to_string())?;
    fs::write(path, content).map_err(|error| format!("保存配置失败：{error}"))?;
    Ok(config)
}

#[tauri::command]
async fn open_runtime(
    app: AppHandle,
    window: WebviewWindow,
    config: RuntimeConfig,
    supervisor: State<'_, RuntimeSupervisor>,
    server_state: State<'_, DesktopServerState>,
) -> Result<(), String> {
    ensure_bootstrap_window(&window)?;
    let config = validate_config(config)?;
    let (url, initialization_script) = if config.mode == RuntimeMode::LocalPrivate {
        let endpoint = start_local_runtime_impl(
            app.clone(),
            supervisor.inner().clone(),
            server_state.inner().clone(),
        )
        .await?;
        let runtime = serde_json::to_string(&endpoint).map_err(|error| error.to_string())?;
        (
            WebviewUrl::App("index.html".into()),
            Some(format!(
                "Object.defineProperty(window, '__LIFETREE_RUNTIME__', {{ value: Object.freeze({runtime}), configurable: false }});"
            )),
        )
    } else {
        let url = Url::parse(&config.service_url).map_err(|error| error.to_string())?;
        (WebviewUrl::External(url), None)
    };

    if let Some(existing) = app.get_webview_window("lifetree") {
        existing.set_focus().map_err(|error| error.to_string())?;
    } else {
        let devtools = std::env::var_os("LIFETREE_DESKTOP_DEVTOOLS").is_some();
        let bg_script = initial_background_script();
        let mut builder = WebviewWindowBuilder::new(&app, "lifetree", url)
            .devtools(devtools)
            .visible(false)
            .background_color(Color(15, 20, 16, 255))
            .initialization_script(bg_script);
        if let Some(script) = initialization_script {
            builder = builder.initialization_script(script);
        }
        let created = builder
            .title("LifeTree")
            .inner_size(1280.0, 820.0)
            .min_inner_size(960.0, 640.0)
            .build()
            .map_err(|error| format!("打开 LifeTree 失败：{error}"))?;

        // 主窗口延迟 500ms 显示（axum server 已就绪，页面加载很快）
        let fallback_window = created.clone();
        std::thread::spawn(move || {
            std::thread::sleep(std::time::Duration::from_millis(500));
            let _ = fallback_window.show();
            let _ = fallback_window.set_focus();
        });

        #[cfg(debug_assertions)]
        if devtools {
            created.open_devtools();
        }
    }
    window.close().map_err(|error| error.to_string())
}

fn ensure_bootstrap_window(window: &WebviewWindow) -> Result<(), String> {
    if window.label() != "bootstrap" {
        return Err("当前窗口无权修改桌面运行配置".into());
    }
    Ok(())
}

/// 同步读取并验证已保存的运行时配置。
///
/// 返回 `Ok(Some(config))` 表示有可用配置可恢复，`Ok(None)` 表示无配置，
/// `Err` 表示读取/解析/校验失败（调用方应回退到启动器）。
fn load_saved_runtime_config(app: &AppHandle) -> Result<Option<RuntimeConfig>, String> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let content = fs::read_to_string(&path).map_err(|error| format!("读取配置失败：{error}"))?;
    let config: RuntimeConfig =
        serde_json::from_str(&content).map_err(|error| format!("配置格式错误：{error}"))?;
    let config = validate_config(config)?;
    Ok(Some(config))
}

/// 异步恢复上次使用的运行时：启动 axum 代理 + Python worker（本地模式）并创建主窗口。
///
/// axum 服务器毫秒级启动，Python worker 在后台异步启动。
/// 主窗口立即创建并显示（延迟 500ms 等 webview 加载），不等 worker 就绪。
/// 前端通过轮询 `/api/v1/desktop/ready` 获知 worker 就绪后切换到完整 UI。
async fn restore_runtime_async(app: AppHandle, config: RuntimeConfig) {
    let supervisor_state = app.state::<RuntimeSupervisor>();
    let supervisor = supervisor_state.inner().clone();
    let server_state = app.state::<DesktopServerState>();
    let server_state = server_state.inner().clone();

    let (url, initialization_script) = if config.mode == RuntimeMode::LocalPrivate {
        let endpoint =
            match start_local_runtime_impl(app.clone(), supervisor.clone(), server_state.clone())
                .await
            {
                Ok(ep) => ep,
                Err(e) => {
                    eprintln!("启动本地运行时失败：{e}，回退到启动器");
                    show_bootstrap(&app);
                    return;
                }
            };
        let runtime = match serde_json::to_string(&endpoint) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("序列化运行时端点失败：{e}");
                show_bootstrap(&app);
                return;
            }
        };
        (
            WebviewUrl::App("index.html".into()),
            Some(format!(
                "Object.defineProperty(window, '__LIFETREE_RUNTIME__', {{ value: Object.freeze({runtime}), configurable: false }});"
            )),
        )
    } else {
        match Url::parse(&config.service_url) {
            Ok(u) => (WebviewUrl::External(u), None),
            Err(e) => {
                eprintln!("解析服务地址失败：{e}，回退到启动器");
                show_bootstrap(&app);
                return;
            }
        }
    };

    // 创建主窗口（不显示启动器）
    let devtools = std::env::var_os("LIFETREE_DESKTOP_DEVTOOLS").is_some();
    let bg_script = initial_background_script();
    let mut builder = WebviewWindowBuilder::new(&app, "lifetree", url)
        .devtools(devtools)
        .visible(false)
        .background_color(Color(15, 20, 16, 255))
        .initialization_script(bg_script);
    if let Some(script) = initialization_script {
        builder = builder.initialization_script(script);
    }
    match builder
        .title("LifeTree")
        .inner_size(1280.0, 820.0)
        .min_inner_size(960.0, 640.0)
        .build()
    {
        Ok(created) => {
            let fallback = created.clone();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(500));
                let _ = fallback.show();
                let _ = fallback.set_focus();
            });
            #[cfg(debug_assertions)]
            if devtools {
                created.open_devtools();
            }
        }
        Err(e) => {
            eprintln!("创建主窗口失败：{e}，回退到启动器");
            show_bootstrap(&app);
        }
    }
}

fn show_bootstrap(app: &AppHandle) {
    if let Some(b) = app.get_webview_window("bootstrap") {
        let _ = b.show();
        let _ = b.set_focus();
    }
}

fn focus_existing_window(app: &AppHandle) {
    let window = app
        .get_webview_window("lifetree")
        .or_else(|| app.get_webview_window("bootstrap"));
    if let Some(window) = window {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn initial_background_script() -> &'static str {
    "(function(){try{var t=localStorage.getItem('theme');var d=t==='dark'||(t!=='light'&&window.matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.style.backgroundColor=d?'#0f1410':'#f7f6f2';document.documentElement.style.colorScheme=d?'dark':'light';}catch(_){document.documentElement.style.backgroundColor='#0f1410';}})();"
}

/// Close the main LifeTree window and reopen the bootstrap launcher so the
/// user can switch between local service / self-hosted / cloud instances.
#[tauri::command]
async fn switch_instance(app: AppHandle) -> Result<(), String> {
    // Close the main window if open
    if let Some(main_window) = app.get_webview_window("lifetree") {
        main_window.close().map_err(|e| e.to_string())?;
    }
    // Show or create the bootstrap launcher window
    if let Some(bootstrap) = app.get_webview_window("bootstrap") {
        bootstrap.show().map_err(|e| e.to_string())?;
        bootstrap.set_focus().map_err(|e| e.to_string())?;
    } else {
        WebviewWindowBuilder::new(
            &app,
            "bootstrap",
            WebviewUrl::App("launcher/index.html".into()),
        )
        .title("LifeTree")
        .inner_size(640.0, 760.0)
        .min_inner_size(480.0, 640.0)
        .center()
        .build()
        .map_err(|e| format!("打开启动器失败：{e}"))?;
    }
    Ok(())
}

/// Navigate the main LifeTree window to a given path (e.g. "/settings").
#[tauri::command]
async fn navigate_main_window(app: AppHandle, path: String) -> Result<(), String> {
    let window = app
        .get_webview_window("lifetree")
        .ok_or_else(|| "LifeTree 主窗口未打开".to_string())?;
    let clean = path.trim_start_matches('/');
    let script = format!("window.location.pathname = '/{clean}';");
    window.eval(&script).map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;
    Ok(())
}

/// 检查更新结果
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct UpdateInfo {
    has_update: bool,
    current_version: String,
    latest_version: String,
    release_title: String,
    release_notes: String,
    html_url: String,
    /// 当前平台对应的下载链接（.dmg 或 .msi）
    download_url: Option<String>,
}

/// 通过签名的 Tauri 更新清单检查最新版本。
#[tauri::command]
async fn check_for_updates(app: AppHandle) -> Result<UpdateInfo, String> {
    let current_version = app.package_info().version.to_string();
    let updater = app
        .updater()
        .map_err(|error| format!("初始化自动更新器失败：{error}"))?;
    let update = updater
        .check()
        .await
        .map_err(|error| format!("检查更新失败：{error}"))?;

    Ok(match update {
        Some(update) => UpdateInfo {
            has_update: true,
            current_version,
            latest_version: update.version,
            release_title: "LifeTree 更新".to_owned(),
            release_notes: update.body.unwrap_or_default(),
            html_url: "https://github.com/CaryK753/LifeTree/releases/latest".to_owned(),
            download_url: Some(update.download_url.to_string()),
        },
        None => UpdateInfo {
            has_update: false,
            current_version: current_version.clone(),
            latest_version: current_version,
            release_title: "LifeTree".to_owned(),
            release_notes: String::new(),
            html_url: "https://github.com/CaryK753/LifeTree/releases/latest".to_owned(),
            download_url: None,
        },
    })
}

/// 后台下载并安装已验证的更新；macOS/Linux 安装完成后由宿主重启。
async fn install_available_update(app: AppHandle) -> Result<bool, String> {
    let updater = app
        .updater()
        .map_err(|error| format!("初始化自动更新器失败：{error}"))?;
    let Some(update) = updater
        .check()
        .await
        .map_err(|error| format!("检查更新失败：{error}"))?
    else {
        return Ok(false);
    };

    let version = update.version.clone();
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|error| format!("安装更新 {version} 失败：{error}"))?;
    eprintln!("LifeTree 更新 {version} 已安装，正在重启");

    #[cfg(target_os = "windows")]
    return Ok(true);

    #[cfg(not(target_os = "windows"))]
    app.restart()
}

fn show_update_message(app: &AppHandle, title: &str, message: String, kind: MessageDialogKind) {
    app.dialog()
        .message(message)
        .title(title)
        .kind(kind)
        .buttons(MessageDialogButtons::Ok)
        .show(|_| {});
}

/// Run an explicit update check from the menu/tray and explain every outcome
/// through a platform-native dialog.
fn check_for_updates_from_menu(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        match check_for_updates(app.clone()).await {
            Ok(info) if info.has_update => {
                let install_handle = app.clone();
                let message = format!(
                    "发现 LifeTree {}。下载完成后将自动重启以安装更新。",
                    info.latest_version
                );
                app.dialog()
                    .message(message)
                    .title("发现更新")
                    .kind(MessageDialogKind::Info)
                    .buttons(MessageDialogButtons::OkCancelCustom(
                        "下载并重启".into(),
                        "稍后".into(),
                    ))
                    .show(move |approved| {
                        if !approved {
                            return;
                        }
                        let app = install_handle.clone();
                        tauri::async_runtime::spawn(async move {
                            if let Err(error) = install_available_update(app.clone()).await {
                                show_update_message(
                                    &app,
                                    "更新失败",
                                    format!("无法下载或安装更新：{error}"),
                                    MessageDialogKind::Error,
                                );
                            }
                        });
                    });
            }
            Ok(_) => show_update_message(
                &app,
                "检查更新",
                "当前已是最新版本。".to_owned(),
                MessageDialogKind::Info,
            ),
            Err(error) => show_update_message(
                &app,
                "检查更新失败",
                format!("无法检查更新：{error}"),
                MessageDialogKind::Error,
            ),
        }
    });
}

/// Build the tray context menu shared across platforms.
fn build_tray_menu(app: &AppHandle) -> Result<tauri::menu::Menu<tauri::Wry>, String> {
    let switch = MenuItem::with_id(
        app,
        "switch_instance",
        "切换实例 / 运行模式",
        true,
        None::<&str>,
    )
    .map_err(|e| e.to_string())?;
    let settings = MenuItem::with_id(app, "open_settings", "设置…", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let updates = MenuItem::with_id(app, "check_updates", "检查更新…", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let sep = PredefinedMenuItem::separator(app).map_err(|e| e.to_string())?;
    let show = MenuItem::with_id(app, "show_main", "显示 LifeTree", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let hide = MenuItem::with_id(app, "hide_main", "隐藏 LifeTree", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let sep2 = PredefinedMenuItem::separator(app).map_err(|e| e.to_string())?;
    let quit = MenuItem::with_id(app, "quit", "退出 LifeTree", true, None::<&str>)
        .map_err(|e| e.to_string())?;

    Menu::with_items(
        app,
        &[
            &switch, &settings, &updates, &sep, &show, &hide, &sep2, &quit,
        ],
    )
    .map_err(|e| e.to_string())
}

/// Handle tray menu clicks.
fn on_tray_menu_event(app: &AppHandle, id: &str) {
    match id {
        "switch_instance" => {
            // Directly invoke the switch logic
            let app_clone = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = switch_instance(app_clone).await {
                    eprintln!("switch_instance failed: {e}");
                }
            });
        }
        "open_settings" => {
            let app_clone = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = navigate_main_window(app_clone, "/settings".into()).await {
                    eprintln!("navigate settings failed: {e}");
                }
            });
        }
        "check_updates" => {
            check_for_updates_from_menu(app.clone());
        }
        "show_main" => {
            if let Some(w) = app.get_webview_window("lifetree") {
                let _ = w.show();
                let _ = w.set_focus();
            } else if let Some(w) = app.get_webview_window("bootstrap") {
                let _ = w.show();
                let _ = w.set_focus();
            }
        }
        "hide_main" => {
            if let Some(w) = app.get_webview_window("lifetree") {
                let _ = w.hide();
            }
        }
        "quit" => {
            app.exit(0);
        }
        _ => {}
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(RuntimeSupervisor::default())
        .manage(DesktopServerState::default())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            focus_existing_window(app);
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            local_runtime_status,
            start_local_runtime,
            load_runtime_config,
            save_runtime_config,
            open_runtime,
            switch_instance,
            navigate_main_window,
            check_for_updates,
            load_locale,
            save_locale
        ])
        .setup(|app| {
            // Build and install the system tray with context menu.
            let menu = build_tray_menu(app.handle()).expect("failed to build tray menu");

            // 检测系统主题，选择合适的托盘图标
            let theme = app
                .get_webview_window("bootstrap")
                .and_then(|w| w.theme().ok())
                .unwrap_or(Theme::Light);
            let tray_icon = tauri::image::Image::from_bytes(tray_icon_for_theme(theme))
                .expect("failed to load tray icon");

            TrayIconBuilder::with_id("lifetree-tray")
                .icon(tray_icon)
                .tooltip("LifeTree")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| {
                    on_tray_menu_event(app, event.id.as_ref());
                })
                .on_tray_icon_event(|tray, event| {
                    // Double-click (macOS) / left-click (Windows) shows the main window
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("lifetree") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        } else if let Some(w) = app.get_webview_window("bootstrap") {
                            let _ = w.show();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)
                .expect("failed to build tray icon");

            // 监听窗口主题变化，自动切换托盘图标
            let app_handle = app.handle().clone();
            if let Some(bootstrap) = app.get_webview_window("bootstrap") {
                let theme_handle = app_handle.clone();
                bootstrap.on_window_event(move |event| {
                    if let WindowEvent::ThemeChanged(_) = event {
                        update_tray_icon(&theme_handle);
                    }
                });

                // 同步读取已保存的配置，决定是否需要恢复
                let saved_config = load_saved_runtime_config(&app_handle);
                match saved_config {
                    Ok(Some(config)) => {
                        // 有配置：异步恢复（启动 sidecar / 创建主窗口），
                        // 失败时在 restore_runtime_async 内部回退到启动器
                        let restore_handle = app_handle.clone();
                        tauri::async_runtime::spawn(async move {
                            restore_runtime_async(restore_handle, config).await;
                        });
                    }
                    _ => {
                        // 无配置或读取失败：立即显示启动器
                        if let Some(b) = app_handle.get_webview_window("bootstrap") {
                            let _ = b.show();
                            let _ = b.set_focus();
                        }
                    }
                }

                // 启用 tray-icon 后 Tauri 默认使用 .accessory 激活策略，
                // 导致应用没有 Dock 图标。显式设为 .regular。
                // 放在窗口显示逻辑之后，避免 macOS 激活应用时让 visible:false
                // 的 bootstrap 窗口短暂闪现。
                let _ = app_handle.set_activation_policy(ActivationPolicy::Regular);
            }

            // 等窗口稳定后再检查，网络问题或更新服务不可用不应影响启动。
            let update_handle = app_handle.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(std::time::Duration::from_secs(12)).await;
                if let Err(error) = install_available_update(update_handle).await {
                    eprintln!("后台自动更新检查失败：{error}");
                }
            });

            Ok(())
        })
        .on_window_event(move |window, event| {
            // 主窗口主题变化时也更新托盘图标
            if let WindowEvent::ThemeChanged(_) = event {
                update_tray_icon(window.app_handle());
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to run LifeTree desktop host");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(url: &str) -> RuntimeConfig {
        RuntimeConfig {
            version: 1,
            mode: RuntimeMode::SelfHosted,
            service_url: url.into(),
            model_runtime: ModelRuntime::ServerManaged,
        }
    }

    #[test]
    fn accepts_https_and_loopback_http() {
        assert!(validate_config(config("https://example.com")).is_ok());
        assert!(validate_config(config("http://127.0.0.1:23000")).is_ok());
    }

    #[test]
    fn rejects_insecure_remote_and_credentials() {
        assert!(validate_config(config("http://example.com")).is_err());
        assert!(validate_config(config("https://user:secret@example.com")).is_err());
    }

    #[test]
    fn local_mode_ignores_remote_service_url() {
        let mut value = config("http://localhost:23000");
        value.mode = RuntimeMode::LocalPrivate;
        assert_eq!(validate_config(value).unwrap().service_url, "");
    }
}
