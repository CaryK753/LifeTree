"use client";

import { useEffect, useState } from "react";
import { Spinner } from "@/components/ui/spinner";
import { apiUrl, getDesktopHeaders } from "@/lib/api";

/**
 * DesktopRuntimeGate: 桌面端本地模式启动门控。
 *
 * 当检测到 `window.__LIFETREE_RUNTIME__` 时（桌面端本地服务模式），
 * 轮询 `/api/v1/desktop/ready` 直到 Python worker 就绪，然后渲染子组件。
 * 未就绪时显示全屏 loading。
 *
 * 非桌面端或远程模式直接渲染子组件。
 */
export function DesktopRuntimeGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [runtimeChecked, setRuntimeChecked] = useState(false);
  const [isDesktopLocal, setIsDesktopLocal] = useState(false);

  useEffect(() => {
    const runtime = window.__LIFETREE_RUNTIME__;
    if (!runtime?.apiBaseUrl) {
      setRuntimeChecked(true);
      return;
    }
    setIsDesktopLocal(true);
    setRuntimeChecked(true);

    let cancelled = false;
    const check = async () => {
      try {
        const resp = await fetch(apiUrl("/desktop/ready"), {
          headers: getDesktopHeaders(),
        });
        if (resp.ok) {
          const data = await resp.json();
          if (data.ready && !cancelled) {
            setReady(true);
          }
        }
      } catch {
        // 忽略错误，继续轮询
      }
    };

    check();
    const interval = setInterval(check, 500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (runtimeChecked && (!isDesktopLocal || ready)) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-dvh items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-4">
        <Spinner className="size-8" />
        <div className="text-center">
          <p className="text-foreground text-sm font-medium">正在启动本地服务</p>
          <p className="text-muted-foreground mt-1 text-xs">首次启动可能需要数秒，请稍候…</p>
        </div>
      </div>
    </div>
  );
}
