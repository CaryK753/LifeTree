/**
 * 统一的系统通知工具。
 *
 * 三种运行环境下的行为：
 *  1. **浏览器 PWA**：使用 `Notification` API。需要用户先在设置页授权
 *     （`WebPushControl` 已经会调 `Notification.requestPermission()`）。
 *  2. **Tauri 桌面端 webview**：通过 Tauri webview 天然注入的
 *     `window.__TAURI_INTERNALS__.invoke` 调用 `tauri-plugin-notification`
 *     插件的 IPC 命令，将通知投递到操作系统通知中心。
 *     检测方式：`window.__TAURI_INTERNALS__` 存在即认为是 Tauri 宿主。
 *  3. **既非 PWA 也非 Tauri**（普通浏览器标签页）：仍尝试 `Notification` API，
 *     未授权则静默回退到应用内 toast（由调用方负责）。
 *
 * 通知点击行为：
 *  - 浏览器：`notification.onclick` → 聚焦窗口并跳转到 `url`。
 *  - Tauri：点击跳转由宿主端处理（如果接入了的话）；否则仅显示通知。
 */

/** Tauri webview 内部 invoke 句柄签名（仅用到的部分）。 */
interface TauriInternals {
  invoke(cmd: string, args?: Record<string, unknown>): Promise<unknown>;
}

/** 是否运行在 Tauri 桌面宿主中（通过 webview 天然注入的 internals 检测）。 */
export function isTauriHost(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof (window as unknown as { __TAURI_INTERNALS__?: TauriInternals })
      .__TAURI_INTERNALS__ !== "undefined"
  );
}

/** 获取 Tauri invoke 句柄（仅在 isTauriHost() 为 true 时调用）。 */
function tauriInvoke(): TauriInternals {
  return (window as unknown as { __TAURI_INTERNALS__: TauriInternals })
    .__TAURI_INTERNALS__;
}

/** 浏览器 Notification API 是否可用。 */
function browserNotificationAvailable(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

/** 当前通知权限状态（同步快查，不阻塞）。 */
export function notificationPermission(): NotificationPermission | "unsupported" | "granted" {
  if (isTauriHost()) {
    // Tauri 端：capability 已静态授予，前端视作 "granted"。
    // 首次启动时 macOS 可能弹出系统授权弹窗，但一旦授权后状态恒为 granted。
    return "granted";
  }
  if (browserNotificationAvailable()) {
    return Notification.permission;
  }
  return "unsupported";
}

/**
 * 异步检查 Tauri 通知权限的真实状态。
 * 在 Tauri 环境下调用 notification 插件的 is_permission_granted 命令。
 * 非 Tauri 环境返回 browser Notification.permission。
 */
async function tauriNotificationGranted(): Promise<boolean | null> {
  if (!isTauriHost()) return null;
  try {
    const result = await tauriInvoke().invoke(
      "plugin:notification|is_permission_granted"
    );
    return Boolean(result);
  } catch {
    // 插件不可用或命令未授权 — 视作未授权
    return false;
  }
}

/**
 * 请求通知权限。
 *
 * - Tauri 环境：先检查是否已授权，未授权时调用 notification 插件的
 *   request_permission 命令触发系统授权弹窗（macOS/Windows 首次启动时）。
 * - 浏览器环境：调用 `Notification.requestPermission()`。
 *
 * @returns 是否已获得权限。
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (isTauriHost()) {
    // 先检查是否已授权，避免重复触发系统弹窗
    const granted = await tauriNotificationGranted();
    if (granted) return true;
    try {
      await tauriInvoke().invoke("plugin:notification|request_permission");
      // request_permission 后再次检查实际状态
      const nowGranted = await tauriNotificationGranted();
      return nowGranted ?? false;
    } catch {
      // 插件调用失败 — 可能是用户拒绝或 capability 未配置
      return false;
    }
  }
  if (!browserNotificationAvailable()) {
    return false;
  }
  if (Notification.permission === "granted") {
    return true;
  }
  if (Notification.permission === "denied") {
    return false;
  }
  try {
    const result = await Notification.requestPermission();
    return result === "granted";
  } catch {
    return false;
  }
}

export interface SystemNotificationOptions {
  /** 通知标题。 */
  title: string;
  /** 通知正文。 */
  body?: string;
  /** 点击通知后跳转的相对 URL（如 "/notifications"）。 */
  url?: string;
  /** 通知图标 URL（仅浏览器环境生效）。 */
  icon?: string;
  /** 通知标识 tag，相同 tag 会覆盖旧通知。 */
  tag?: string;
}

/**
 * 发送一条系统通知。
 *
 * 静默失败策略：任何环境下的失败都不会抛出异常，调用方负责应用内 toast 回退。
 *
 * 在 Tauri 环境下，首次发送通知前会自动请求权限（macOS/Windows 首次
 * 启动时弹出系统授权对话框）。用户授权后通知将投递到操作系统通知中心。
 *
 * @returns 是否成功投递。
 */
export async function sendSystemNotification(opts: SystemNotificationOptions): Promise<boolean> {
  // 1. Tauri 桌面端：通过 __TAURI_INTERNALS__.invoke 调用 notification 插件。
  if (isTauriHost()) {
    // 先确保权限已授予（首次会触发系统弹窗）
    const granted = await tauriNotificationGranted();
    if (granted === false) {
      // 尝试请求权限
      const requested = await requestNotificationPermission();
      if (!requested) return false;
    }
    try {
      await tauriInvoke().invoke("plugin:notification|send_notification", {
        options: {
          title: opts.title,
          body: opts.body ?? "",
        },
      });
      return true;
    } catch {
      // 插件调用失败，回退到浏览器 API（如果可用）。
    }
  }

  // 2. 浏览器 Notification API。
  if (!browserNotificationAvailable()) {
    return false;
  }
  if (Notification.permission !== "granted") {
    return false;
  }
  try {
    const notification = new Notification(opts.title, {
      body: opts.body,
      icon: opts.icon,
      tag: opts.tag,
      data: opts.url ? { url: opts.url } : undefined,
    });
    notification.onclick = () => {
      window.focus();
      if (opts.url) {
        try {
          window.location.href = opts.url;
        } catch {
          // 跨域或被拦截，忽略。
        }
      }
      notification.close();
    };
    return true;
  } catch {
    return false;
  }
}

/** 默认通知图标（manifest 里的 192px icon）。 */
export const DEFAULT_NOTIFICATION_ICON = "/media/icon-192.png";
