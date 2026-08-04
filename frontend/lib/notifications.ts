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

/** 当前通知权限状态。 */
export function notificationPermission(): NotificationPermission | "unsupported" | "granted" {
  if (isTauriHost()) {
    // Tauri 端的权限由 capability 控制，前端视作 "granted"。
    return "granted";
  }
  if (browserNotificationAvailable()) {
    return Notification.permission;
  }
  return "unsupported";
}

/**
 * 请求通知权限。
 *
 * - Tauri 环境：调用 notification 插件的 request_permission 命令
 *   （capability 中已静态授予，通常直接成功）。
 * - 浏览器环境：调用 `Notification.requestPermission()`。
 *
 * @returns 是否已获得权限。
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (isTauriHost()) {
    try {
      await tauriInvoke().invoke("plugin:notification|request_permission");
      return true;
    } catch {
      // 静默失败：capability 已授予时不应走到这里
      return true;
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
 * @returns 是否成功投递。
 */
export async function sendSystemNotification(opts: SystemNotificationOptions): Promise<boolean> {
  // 1. Tauri 桌面端：通过 __TAURI_INTERNALS__.invoke 调用 notification 插件。
  if (isTauriHost()) {
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
