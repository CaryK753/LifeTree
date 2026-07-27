"use client";

import { Suspense } from "react";
import { OAuthCallbackHandler } from "./oauth-callback-handler";

/**
 * Legacy OAuth callback route: ``/auth/callback?provider=...&code=...&state=...``.
 *
 * Kept for backwards compatibility with redirect_uri values that point at
 * the bare ``/auth/callback`` path. The provider id must be supplied via
 * the ``?provider=`` query param — the OAuth 2.0 standard does not pass
 * it automatically.
 *
 * New deployments should prefer ``/auth/callback/[provider]`` (see
 * ``[provider]/page.tsx``) so the provider id is encoded in the path and
 * the redirect_uri hint ``{origin}/auth/callback/{provider}`` matches the
 * actual route.
 */
export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      {/* Empty string means "fall back to ?provider= query param" —
          see OAuthCallbackHandler. */}
      <OAuthCallbackHandler provider="" />
    </Suspense>
  );
}
