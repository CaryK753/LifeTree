import { Suspense } from "react";
import { OAuthCallbackHandler } from "../oauth-callback-handler";

export function generateStaticParams() {
  return [{ provider: "_" }];
}

export default async function OAuthCallbackProviderPage({
  params,
}: {
  params: Promise<{ provider: string }>;
}) {
  const { provider } = await params;
  return (
    <Suspense fallback={null}>
      <OAuthCallbackHandler provider={provider} />
    </Suspense>
  );
}
