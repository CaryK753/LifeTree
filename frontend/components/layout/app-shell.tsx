"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { AuthGate } from "@/components/auth/auth-gate";
import { SSEProvider } from "@/components/sse/sse-provider";

/**
 * AppShell: top-level layout wrapper that decides whether to render the
 * full app chrome (Sidebar + AuthGate) or a bare standalone layout.
 *
 * Standalone routes (no sidebar, no auth gate):
 *   - /auth/*          — the independent login/register page
 *   - /auth/callback/* — OAuth callback handler
 *   - /terms, /privacy — public legal documents
 *
 * All other routes get the full Sidebar + AuthGate treatment.
 *
 * This is a client component because ``usePathname`` is needed to
 * distinguish standalone routes from app routes, and the pathname is
 * only available on the client (or via ``next/headers`` in a server
 * component, which would add an extra async boundary for no benefit).
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  // Standalone auth pages: render bare, no sidebar, no auth gate.
  // The /auth page handles its own redirect-if-already-logged-in logic.
  if (
    pathname.startsWith("/auth") ||
    pathname === "/terms" ||
    pathname === "/privacy"
  ) {
    return <>{children}</>;
  }

  // Full app layout: Sidebar + AuthGate + main content area.
  return (
    <AuthGate>
      <SSEProvider>
        <div className="flex h-dvh min-h-0 overflow-hidden">
          <Sidebar />
          <main className="main-shell min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain safe-top safe-bottom">
            {children}
          </main>
        </div>
      </SSEProvider>
    </AuthGate>
  );
}
