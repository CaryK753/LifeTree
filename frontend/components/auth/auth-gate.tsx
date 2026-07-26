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
 *   - Single-user mode (``use_mode === "single"``): the app runs without
 *     login. The backend serves data via the default-user fallback, so
 *     we never auto-open the login dialog. Users who want a personal
 *     scope can still sign in via the user menu.
 *   - Multi-user mode (``use_mode === "multi"``): the dialog auto-opens
 *     on first load and is NOT dismissible — the user must authenticate.
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
  const dismissible = !multiUserMode;

  // Auto-open login dialog on first load ONLY in multi-user mode.
  // In single-user mode the app works without login (default-user
  // fallback), so we never prompt — the user can still sign in
  // voluntarily via the user menu.
  useEffect(() => {
    if (multiUserMode && !isLoading && !isAuthenticated && !dismissed) {
      setShowLogin(true);
    }
  }, [multiUserMode, isLoading, isAuthenticated, dismissed]);

  // Sync chat-store's user scope with the current user so conversations
  // are isolated per user in localStorage. When logged out, falls back
  // to the "default" scope (single-user mode / default-user fallback).
  useEffect(() => {
    setChatUserScope(user?.id ?? null);
  }, [user?.id]);

  function handleOpenChange(open: boolean) {
    // In multi-user mode, the dialog can never be closed (no fallback).
    if (multiUserMode && !open) return;
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
