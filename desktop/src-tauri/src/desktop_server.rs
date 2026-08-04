//! 桌面端内嵌 HTTP 服务器。
//!
//! 使用 axum 实现毫秒级启动的轻量代理，负责：
//! - `/health`：立即返回 ok（不依赖 Python worker）
//! - `/api/v1/desktop/ready`：返回 Python worker 就绪状态
//! - `/api/v1/*`：代理到 Python worker（未就绪时返回 503）
//!
//! 主窗口在 axum server 启动后立即可用，前端通过轮询
//! `/api/v1/desktop/ready` 获知 worker 就绪后切换到完整 UI。

use std::net::SocketAddr;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{Request, State},
    http::{HeaderName, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{any, get},
    Router,
};
use tokio::net::TcpListener;
use tokio::sync::watch;
use tower_http::cors::CorsLayer;

/// Python worker 的连接信息（代理目标）。
#[derive(Clone, Debug)]
pub struct WorkerTarget {
    pub port: u16,
    pub ready: Arc<AtomicBool>,
}

/// axum 共享状态。
#[derive(Clone)]
struct ProxyState {
    target: Arc<tokio::sync::RwLock<Option<WorkerTarget>>>,
    client: reqwest::Client,
}

/// 桌面端 HTTP 服务器句柄，用于控制生命周期。
pub struct DesktopServer {
    pub addr: SocketAddr,
    shutdown_tx: watch::Sender<bool>,
}

impl DesktopServer {
    /// 在指定端口启动 axum HTTP 服务器（非阻塞，后台运行）。
    ///
    /// `worker_target` 是一个 `RwLock<Option<WorkerTarget>>`，允许在运行时
    /// 更新代理目标（切换实例时替换为新 worker）。
    pub async fn start(
        port: u16,
        worker_target: Arc<tokio::sync::RwLock<Option<WorkerTarget>>>,
    ) -> Result<Self, String> {
        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        let listener = TcpListener::bind(addr)
            .await
            .map_err(|e| format!("无法绑定端口 {port}：{e}"))?;

        let actual_addr = listener
            .local_addr()
            .map_err(|e| format!("无法读取本地地址：{e}"))?;

        let state = ProxyState {
            target: worker_target,
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(300))
                .build()
                .map_err(|e| format!("HTTP 客户端初始化失败：{e}"))?,
        };

        let cors = CorsLayer::new()
            .allow_methods([
                axum::http::Method::GET,
                axum::http::Method::POST,
                axum::http::Method::PUT,
                axum::http::Method::PATCH,
                axum::http::Method::DELETE,
                axum::http::Method::OPTIONS,
            ])
            .allow_headers([
                axum::http::header::AUTHORIZATION,
                axum::http::header::CONTENT_TYPE,
                HeaderName::from_static("x-lifetree-desktop-token"),
                HeaderName::from_static("x-retry"),
            ])
            .allow_origin([
                HeaderValue::from_static("tauri://localhost"),
                HeaderValue::from_static("http://tauri.localhost"),
            ]);

        let app = Router::new()
            .route("/health", get(health_handler))
            .route("/api/v1/desktop/ready", get(desktop_ready_handler))
            .route("/api/v1/*path", any(proxy_handler))
            .layer(cors)
            .with_state(state);

        let (shutdown_tx, mut shutdown_rx) = watch::channel(false);

        tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async move {
                    let _ = shutdown_rx.wait_for(|v| *v).await;
                })
                .await
                .ok();
        });

        Ok(Self {
            addr: actual_addr,
            shutdown_tx,
        })
    }
}

impl Drop for DesktopServer {
    fn drop(&mut self) {
        let _ = self.shutdown_tx.send(true);
    }
}

/// `/health` — 始终返回 ok，用于 Tauri 端健康检查。
async fn health_handler() -> impl IntoResponse {
    (StatusCode::OK, r#"{"status":"ok"}"#)
}

/// `/api/v1/desktop/ready` — 返回 Python worker 就绪状态。
async fn desktop_ready_handler(State(state): State<ProxyState>) -> impl IntoResponse {
    let target = state.target.read().await;
    let (ready, port) = match target.as_ref() {
        Some(t) => (t.ready.load(Ordering::Relaxed), t.port),
        None => (false, 0),
    };
    let body = if ready {
        format!(r#"{{"ready":true,"workerPort":{port}}}"#)
    } else {
        r#"{"ready":false}"#.to_string()
    };
    (StatusCode::OK, [("content-type", "application/json")], body)
}

/// `/api/v1/{*path}` — 代理到 Python worker。
///
/// worker 未就绪时返回 503；就绪时将请求转发到
/// `http://127.0.0.1:{worker_port}/api/v1/{path}`，支持流式响应（SSE）。
async fn proxy_handler(State(state): State<ProxyState>, req: Request<Body>) -> Response {
    let target = state.target.read().await;
    let worker = match target.as_ref() {
        Some(t) if t.ready.load(Ordering::Relaxed) => t.clone(),
        _ => {
            return (
                StatusCode::SERVICE_UNAVAILABLE,
                [("content-type", "application/json")],
                r#"{"error":"worker_not_ready","message":"本地服务正在启动，请稍候..."}"#,
            )
                .into_response();
        }
    };
    drop(target);

    let method = req.method().clone();
    let path_query = req
        .uri()
        .path_and_query()
        .map(|p| p.as_str())
        .unwrap_or("/");
    let url = format!("http://127.0.0.1:{}{}", worker.port, path_query);

    // 转发请求头（跳过 host / content-length，让 reqwest 自动设置）
    let mut forward_headers = reqwest::header::HeaderMap::new();
    for (name, value) in req.headers().iter() {
        if name == "host" || name == "content-length" || name == "transfer-encoding" {
            continue;
        }
        if let (Ok(n), Ok(v)) = (
            HeaderName::from_bytes(name.as_str().as_bytes()),
            HeaderValue::from_bytes(value.as_bytes()),
        ) {
            forward_headers.insert(n, v);
        }
    }

    // 读取请求体（桌面端请求体通常较小，直接 buffer）
    let body_bytes = match axum::body::to_bytes(req.into_body(), 256 * 1024 * 1024).await {
        Ok(b) => b,
        Err(e) => {
            return (StatusCode::BAD_REQUEST, format!("读取请求体失败：{e}")).into_response();
        }
    };

    let builder = state.client.request(method, &url).headers(forward_headers);

    let response = if body_bytes.is_empty() {
        builder.send().await
    } else {
        builder.body(body_bytes).send().await
    };

    match response {
        Ok(resp) => {
            let status = resp.status();
            let resp_headers = resp.headers().clone();

            // 流式转发响应体（支持 SSE / 大文件下载）
            let stream = resp.bytes_stream();
            let body = Body::from_stream(stream);

            let mut response = Response::new(body);
            *response.status_mut() = status;
            // 复制响应头（跳过 transfer-encoding，axum 会自动处理）
            for (name, value) in resp_headers.iter() {
                if name == "transfer-encoding" || name == "content-length" {
                    continue;
                }
                if let Ok(v) = HeaderValue::from_bytes(value.as_bytes()) {
                    response.headers_mut().insert(name.clone(), v);
                }
            }
            response
        }
        Err(e) => {
            let status = if e.is_connect() {
                StatusCode::BAD_GATEWAY
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            };
            (
                status,
                [("content-type", "application/json")],
                format!(r#"{{"error":"proxy_failed","message":"{e}"}}"#),
            )
                .into_response()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_proxy_catch_all_route() {
        let result = std::panic::catch_unwind(|| {
            let _ = Router::new().route("/api/v1/*path", any(proxy_handler));
        });
        assert!(result.is_ok());
    }
}
