"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, useAuthConfig } from "@/lib/hooks";
import { setChatUserScope } from "@/lib/chat-store";
import { Loader2 } from "lucide-react";

/**
 * AuthGate: wraps the app, redirects unauthenticated users to /auth.
 *
 * Strategy:
 *   - **First-run setup** (``has_users === false``): no real users exist
 *     yet. Redirect to ``/auth`` with ``?first_admin=1`` so the auth
 *     page shows the "create first admin" setup screen. The user can
 *     also switch to single mode from the auth page.
 *   - **Both runtime modes** require a registered, authenticated account.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading, isAuthenticated } = useAuth();
  const { data: authConfig } = useAuthConfig();
  const router = useRouter();
  // Mount gate: ``useAuth`` derives ``hasToken`` from ``typeof window``,
  // which differs between SSR (false) and client (maybe true). That makes
  // ``isLoading`` differ across the boundary and triggers a hydration
  // mismatch on the loading overlay below. We delay rendering the overlay
  // until after mount so SSR and client first-render agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  // ``has_users``: False when no real users exist (excluding the default-user
  // fallback). The frontend redirects to /auth?first_admin=1 in that case.
  const hasUsers = authConfig?.has_users ?? true; // default true to avoid flashing setup on slow loads
  const needsFirstAdmin = !hasUsers;

  // Sync chat-store's user scope with the current user so conversations
  // are isolated per user in localStorage. When logged out, falls back
  // to an empty scope until authentication completes.
  useEffect(() => {
    setChatUserScope(user?.id ?? null);
  }, [user?.id]);

  // Redirect to /auth when authentication is required but the user is
  // not authenticated. Two cases:
  //   1. First-run setup (no users yet) — go to /auth?first_admin=1
  //   2. Multi-user mode + not authenticated — go to /auth
  // We wait until ``isLoading`` is false so we don't redirect while the
  // token is still being verified from localStorage.
  useEffect(() => {
    if (isLoading || isAuthenticated) return;
    if (needsFirstAdmin) {
      router.replace("/auth?first_admin=1");
    } else {
      router.replace("/auth");
    }
  }, [needsFirstAdmin, isLoading, isAuthenticated, router]);

  // Hide children in both modes when the user is not authenticated. This
  // prevents SWR hooks in protected pages from firing
  // API requests that the backend would 401 anyway, and avoids any chance
  // of stale default-user data leaking into the DOM while the redirect
  // to /auth is pending.
  //
  // First-run setup briefly keeps the shell mounted until redirect.
  const renderChildren = isAuthenticated || needsFirstAdmin;

  return (
    <>
      {renderChildren ? children : null}

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
