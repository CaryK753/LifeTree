"use client";

import { useEffect, useState } from "react";
import { Bell, BellOff, Loader2, Monitor } from "lucide-react";
import { api, type NotificationChannelStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import {
  isTauriHost,
  notificationPermission,
  requestNotificationPermission,
} from "@/lib/notifications";

export function WebPushControl() {
  const toast = useToast();
  const isDesktop = isTauriHost();
  const [status, setStatus] = useState<NotificationChannelStatus | null>(null);
  const [subscriptions, setSubscriptions] = useState<Array<{ id: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [desktopPerm, setDesktopPerm] = useState<NotificationPermission | "unsupported" | "granted">(
    () => notificationPermission()
  );

  async function refresh() {
    if (isDesktop) {
      setDesktopPerm(notificationPermission());
      return;
    }
    const [channelStatus, rows] = await Promise.all([
      api.getNotificationChannelStatus(),
      api.listPushSubscriptions(),
    ]);
    setStatus(channelStatus);
    setSubscriptions(rows);
  }

  useEffect(() => {
    refresh().catch(() => undefined);
  }, []);

  async function enableBrowser() {
    if (!status?.web_push.public_key) return;
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error("浏览器未授予通知权限");
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: decodeVapidKey(status.web_push.public_key),
      });
      const json = subscription.toJSON();
      await api.upsertPushSubscription({
        endpoint: subscription.endpoint,
        p256dh: json.keys?.p256dh || "",
        auth: json.keys?.auth || "",
        user_agent: navigator.userAgent,
      });
      await refresh();
      toast({ title: "浏览器推送已启用", variant: "success" });
    } catch (error: any) {
      toast({ title: "无法启用浏览器推送", description: error?.message, variant: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function disableBrowser() {
    setBusy(true);
    try {
      await Promise.all(subscriptions.map((row) => api.deletePushSubscription(row.id)));
      const registration = await navigator.serviceWorker.ready;
      const current = await registration.pushManager.getSubscription();
      if (current) await current.unsubscribe();
      await refresh();
      toast({ title: "浏览器推送已停用", variant: "success" });
    } finally {
      setBusy(false);
    }
  }

  async function enableDesktop() {
    setBusy(true);
    try {
      const granted = await requestNotificationPermission();
      setDesktopPerm(granted ? "granted" : "denied");
      if (granted) {
        toast({ title: "桌面通知已启用", variant: "success" });
      } else {
        toast({ title: "未获得通知权限", description: "请在系统设置中允许 LifeTree 发送通知", variant: "warning" });
      }
    } finally {
      setBusy(false);
    }
  }

  // ---------- 桌面端：使用原生 OS 通知（Tauri notification 插件） ----------
  if (isDesktop) {
    const enabled = desktopPerm === "granted";
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            <span className="flex items-center gap-2"><Monitor className="h-4 w-4" />系统通知</span>
            <Badge>{enabled ? "已启用" : desktopPerm === "denied" ? "已拒绝" : "可启用"}</Badge>
          </CardTitle>
          <CardDescription>
            高优先级风险提醒将发送到操作系统通知中心（macOS 通知中心 / Windows 操作中心）。
          </CardDescription>
        </CardHeader>
        <CardContent>
          {desktopPerm === "denied" ? (
            <p className="text-xs text-amber-600 dark:text-amber-400">
              通知权限已被拒绝。请在系统设置 → 通知中允许 LifeTree 发送通知。
            </p>
          ) : (
            <Button
              variant={enabled ? "outline" : "default"}
              disabled={busy}
              onClick={enableDesktop}
            >
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Bell className="mr-2 h-4 w-4" />}
              {enabled ? "已授权通知" : "启用系统通知"}
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  // ---------- 浏览器端：Web Push（VAPID + Service Worker） ----------
  const configured = status?.web_push.credentials_configured ?? false;
  const enabled = subscriptions.length > 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2"><Bell className="h-4 w-4" />浏览器推送</span>
          <Badge>{enabled ? "已启用" : configured ? "可启用" : "未配置"}</Badge>
        </CardTitle>
        <CardDescription>高优先级风险提醒将发送到当前浏览器。</CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          variant={enabled ? "outline" : "default"}
          disabled={
            busy ||
            !configured ||
            typeof navigator === "undefined" ||
            !("serviceWorker" in navigator)
          }
          onClick={enabled ? disableBrowser : enableBrowser}
        >
          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : enabled ? <BellOff className="mr-2 h-4 w-4" /> : <Bell className="mr-2 h-4 w-4" />}
          {enabled ? "停用推送" : "启用推送"}
        </Button>
      </CardContent>
    </Card>
  );
}

function decodeVapidKey(value: string): Uint8Array {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}
