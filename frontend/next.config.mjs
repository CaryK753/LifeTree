import { dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // The cytoscape-fcose type definitions bundle a conflicting version of
  // @types/cytoscape, causing irreducible type errors in knowledge-graph.tsx.
  // These are dependency-level conflicts, not code bugs. Type checking is
  // still available via `npm run type-check` (tsc --noEmit) in local dev.
  typescript: {
    ignoreBuildErrors: true,
  },
  turbopack: {
    root: __dirname,
  },
  async rewrites() {
    // Server-side proxy target: prefer BACKEND_URL (a server-only env var,
    // safe to use container-internal hostnames like http://backend:18000).
    // Fall back to NEXT_PUBLIC_API_BASE_URL for backward compatibility
    // (but note that localhost won't work inside a container — the backend
    // is in a separate container).
    const apiBase = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:18000";
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBase}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
