"use client";

import { useEffect, useState } from "react";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { LoginDialog } from "@/components/auth/login-dialog";
import { setChatUserScope } from "@/lib/chat-store";
import { Loader2 } from "lucide-react";

/**
 * AuthGate: wraps the app, shows a login dialog when unauthenticated.
 *
 * Strategy:
 *   - **First-run setup** (``has_users === false``): no real users exist
 *     yet, so the dialog auto-opens in "first admin" mode and is NOT
 *     dismissible. The user must create the first admin account to
 *     continue. This applies to BOTH single and multi mode — even in
 *     single mode, at least one account must exist so the user can
 *     access profile/settings/admin features.
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
  // fallback). The frontend shows a non-dismissible "create admin" setup
  // screen in that case, regardless of use_mode.
  const hasUsers = authConfig?.has_users ?? true; // default true to avoid flashing setup on slow loads
  const needsFirstAdmin = !hasUsers;

  // The dialog is dismissible only when:
  //   - real users already exist (not first-run setup), AND
  //   - we're in single-user mode (anonymous access allowed)
  const dismissible = !needsFirstAdmin && !multiUserMode;

  // Auto-open login dialog when:
  //   1. First-run setup (no users yet) — must create admin account, OR
  //   2. Multi-user mode + not authenticated — must log in.
  // In both cases the dialog is non-dismissible.
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
    if (!open && (needsFirstAdmin || multiUserMode)) return;
    setShowLogin(open);
    if (!open) setDismissed(true);
  }

  return (
    <>
      {children}
      <LoginDialog
        open={showLogin}
        onOpenChange={handleOpenChange}
        dismissible={dismissible}
        firstAdminSetup={needsFirstAdmin}
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
