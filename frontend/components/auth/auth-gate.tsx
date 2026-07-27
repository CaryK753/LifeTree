"use client";

import { useEffect, useState } from "react";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { LoginDialog } from "@/components/auth/login-dialog";
import { setChatUserScope } from "@/lib/chat-store";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";

/**
 * AuthGate: wraps the app, shows a login dialog when unauthenticated.
 *
 * Strategy:
 *   - **First-run setup** (``has_users === false``): no real users exist
 *     yet. In multi mode the dialog auto-opens in "first admin" mode and
 *     is NOT dismissible — the user must create the first admin account
 *     OR switch to single mode via the link on the dialog. In single
 *     mode the dialog is dismissible so the user can skip registration
 *     and use anonymous access (the default-user fallback has admin
 *     rights, so all features work without logging in).
 *   - **Single-user mode** (``use_mode === "single"``, has users): the
 *     app runs without login. The backend serves data via the
 *     default-user fallback. Users who want a personal scope can still
 *     sign in via the user menu.
 *   - **Multi-user mode** (``use_mode === "multi"``, has users): the
 *     dialog auto-opens on first load and is NOT dismissible — the user
 *     must authenticate.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading, isAuthenticated } = useAuth();
  const { data: authConfig } = useAuthConfig();
  const [showLogin, setShowLogin] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  // Mount gate: ``useAuth`` derives ``hasToken`` from ``typeof window``,
  // which differs between SSR (false) and client (maybe true). That makes
  // ``isLoading`` differ across the boundary and triggers a hydration
  // mismatch on the loading overlay below. We delay rendering the overlay
  // until after mount so SSR and client first-render agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // ``use_mode``: "single" (default, no login required) | "multi" (login required).
  // ``multi_user_mode`` is kept as a legacy alias.
  const useMode = authConfig?.use_mode ?? (authConfig?.multi_user_mode ? "multi" : "single");
  const multiUserMode = useMode === "multi";

  // ``has_users``: False when no real users exist (excluding the default-user
  // fallback). The frontend shows a "create admin" setup screen in that case.
  const hasUsers = authConfig?.has_users ?? true; // default true to avoid flashing setup on slow loads
  const needsFirstAdmin = !hasUsers;

  // The dialog is dismissible only when:
  //   - in single-user mode (anonymous access allowed), OR
  //   - first-run setup (admin can dismiss to switch to single mode)
  // In multi mode with existing users, the dialog is NOT dismissible —
  // the user must authenticate. Closing it would otherwise expose
  // unauthenticated API requests to the default-user fallback.
  const dismissible = !multiUserMode || needsFirstAdmin;

  // Auto-open login dialog when:
  //   1. First-run setup (no users yet) — must create admin account, OR
  //   2. Multi-user mode + not authenticated — must log in.
  // In multi mode + first-run, the dialog is non-dismissible.
  useEffect(() => {
    if (isLoading || isAuthenticated) return;
    if (needsFirstAdmin && !dismissed) {
      setShowLogin(true);
    } else if (multiUserMode && !dismissed) {
      setShowLogin(true);
    }
  }, [needsFirstAdmin, multiUserMode, isLoading, isAuthenticated, dismissed]);

  // Sync chat-store's user scope with the current user so conversations
  // are isolated per user in localStorage. When logged out, falls back
  // to the "default" scope (single-user mode / default-user fallback).
  useEffect(() => {
    setChatUserScope(user?.id ?? null);
  }, [user?.id]);

  function handleOpenChange(open: boolean) {
    // Non-dismissible modes: the dialog can never be closed (no fallback).
    if (!open && !dismissible) return;
    setShowLogin(open);
    if (!open) setDismissed(true);
  }

  async function handleSwitchToSingle() {
    try {
      await api.setUseMode("single");
      // Reload so the new use_mode takes effect everywhere.
      window.location.reload();
    } catch (err) {
      // If the switch fails (e.g. server-side validation), just reload —
      // the user will see the same dialog again.
      console.error("Failed to switch to single mode:", err);
      window.location.reload();
    }
  }

  // In multi-user mode, hide the children entirely when the user is not
  // authenticated. This prevents SWR hooks in protected pages from firing
  // API requests that the backend would 401 anyway, and avoids any chance
  // of stale default-user data leaking into the DOM while the login
  // dialog is showing.
  //
  // Single-user mode always renders children (default-user fallback is
  // intended behaviour there). First-run setup also renders children so
  // the user can switch to single mode via the dialog link if they prefer.
  const renderChildren = !multiUserMode || isAuthenticated || needsFirstAdmin;

  return (
    <>
      {renderChildren ? children : null}
      <LoginDialog
        open={showLogin}
        onOpenChange={handleOpenChange}
        dismissible={dismissible}
        firstAdminSetup={needsFirstAdmin}
        useMode={useMode}
        onSwitchToSingle={handleSwitchToSingle}
      />

      {/* Loading overlay while verifying token.
          Gated on ``mounted`` so SSR and client first-render agree —
          ``isLoading`` depends on ``hasToken`` which reads localStorage
          and differs across the SSR/client boundary. */}
      {mounted && isLoading && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/30 backdrop-blur-sm">
          <Loader2 className="h-6 w-6 animate-spin text-white" />
        </div>
      )}
    </>
  );
}
