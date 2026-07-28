"use client";

import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/sidebar";
import { AuthGate } from "@/components/auth/auth-gate";

/**
 * AppShell: top-level layout wrapper that decides whether to render the
 * full app chrome (Sidebar + AuthGate) or a bare standalone layout.
 *
 * Standalone routes (no sidebar, no auth gate):
 *   - /auth/*          — the independent login/register page
 *   - /auth/callback/* — OAuth callback handler
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
  if (pathname.startsWith("/auth")) {
    return <>{children}</>;
  }

  // Full app layout: Sidebar + AuthGate + main content area.
  return (
    <AuthGate>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 min-w-0 overflow-y-auto overflow-x-hidden safe-top main-shell">
          {children}
        </main>
      </div>
    </AuthGate>
  );
}
