"use client";

import { Suspense, useEffect, useState } from "react";
import { OAuthCallbackHandler } from "../oauth-callback-handler";

/**
 * Dynamic OAuth callback route: ``/auth/callback/[provider]?code=...&state=...``.
 *
 * This is the recommended route — the OAuth 2.0 standard only returns
 * ``code`` and ``state`` in the callback URL, so encoding the provider id
 * in the path (via the redirect_uri configured at the provider) is the
 * most reliable way to know which provider the user authenticated with.
 *
 * The admin should configure the provider's redirect_uri as:
 *   ``{origin}/auth/callback/{provider_id}``
 * e.g. ``https://lifetree.example.com/auth/callback/github``.
 *
 * Next.js 16 passes ``params`` as a Promise — we unwrap it in an inner
 * component so the parent can stay under a Suspense boundary (required
 * by ``useSearchParams()`` in the handler).
 */
export default function OAuthCallbackProviderPage({
  params,
}: {
  params: Promise<{ provider: string }>;
}) {
  return (
    <Suspense fallback={null}>
      <ProviderBody params={params} />
    </Suspense>
  );
}

function ProviderBody({
  params,
}: {
  params: Promise<{ provider: string }>;
}) {
  const [provider, setProvider] = useState<string>("");
  useEffect(() => {
    let cancelled = false;
    params.then((p) => {
      if (!cancelled) setProvider(p.provider);
    });
    return () => {
      cancelled = true;
    };
  }, [params]);
  if (!provider) return null;
  return <OAuthCallbackHandler provider={provider} />;
}
