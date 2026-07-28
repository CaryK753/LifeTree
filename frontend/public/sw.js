/**
 * LifeTree Service Worker
 *
 * Strategy:
 *  - Precache the app shell + icons on install.
 *  - Navigation requests: network-first, fall back to cached shell (offline support).
 *  - Static assets (_next/static, media): cache-first with background revalidation.
 *  - API calls (/api/v1/*): network-only so authenticated data never crosses users.
 *  - LLM streaming (chat/stream): bypass cache entirely.
 *
 * Versioned via SW_VERSION — bump to invalidate old caches on next activation.
 */

const SW_VERSION = "lifetree-v3";
const APP_SHELL = [
  "/",
  "/auth",
  "/terms",
  "/privacy",
  "/dashboard",
  "/goals",
  "/graph",
  "/chat",
  "/scenarios",
  "/sources",
  "/notifications",
  "/ingest",
  "/plugins",
  "/profile",
  "/settings",
  "/offline",
  "/manifest.webmanifest",
  "/media/logo.png",
  "/media/icon-192.png",
  "/media/icon-512.png",
  "/media/apple-touch-icon.png",
];

const STATIC_CACHE = `${SW_VERSION}-static`;
const RUNTIME_CACHE = `${SW_VERSION}-runtime`;

// ---------- Install: precache app shell ----------
self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      // Use addAll with tolerance — if any single URL fails (e.g. /offline
      // doesn't exist yet), still install so activation can proceed.
      await Promise.all(
        APP_SHELL.map(async (url) => {
          try {
            const res = await fetch(url, { cache: "reload" });
            if (res.ok) await cache.put(url, res.clone());
          } catch (_) {
            /* ignore individual failures */
          }
        })
      );
      await self.skipWaiting();
    })()
  );
});

// ---------- Activate: clean up old caches ----------
self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (k) =>
              k !== STATIC_CACHE && k !== RUNTIME_CACHE
          )
          .map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

// ---------- Fetch routing ----------
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Same-origin only — let cross-origin (fonts, analytics) go straight to network.
  if (url.origin !== self.location.origin) return;

  // Next dev reuses chunk URLs while their contents change. Caching those
  // files can mix incompatible builds and leave the page as an inert SSR
  // shell, so localhost development always goes straight to the network.
  if (
    self.location.hostname === "localhost" ||
    self.location.hostname === "127.0.0.1" ||
    self.location.hostname === "[::1]"
  ) {
    return;
  }

  // LLM streaming must never be cached.
  if (url.pathname.startsWith("/api/v1/chat/stream")) return;

  // Never cache API responses. In multi-user mode, URL-only cache matching
  // can otherwise serve one account's protected data to another account.
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // Navigations: network-first, fall back to cached shell, then offline page.
  if (req.mode === "navigate") {
    event.respondWith(handleNavigation(req));
    return;
  }

  // Static assets: cache-first with background revalidation.
  if (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/media/")
  ) {
    event.respondWith(cacheFirst(req, RUNTIME_CACHE));
    return;
  }
});

// ---------- Strategies ----------

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) {
    // Revalidate in background.
    fetch(req)
      .then((res) => {
        if (res && res.ok) cache.put(req, res.clone());
      })
      .catch(() => {});
    return cached;
  }
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (_) {
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

async function handleNavigation(req) {
  try {
    const res = await fetch(req);
    // Cache latest shell HTML for offline use.
    const cache = await caches.open(STATIC_CACHE);
    cache.put(req, res.clone()).catch(() => {});
    return res;
  } catch (_) {
    const cache = await caches.open(STATIC_CACHE);
    // Try the exact URL first, then fall back to "/" app shell.
    const cached =
      (await cache.match(req)) || (await cache.match("/"));
    if (cached) return cached;
    return new Response(OFFLINE_HTML, {
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }
}

// ---------- Message: skipWaiting on user prompt ----------
self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

const OFFLINE_HTML = `<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>离线 · LifeTree</title>
  <style>
    :root { color-scheme: dark; }
    body {
      margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
      background: #0b0d12; color: #d4d4d8;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
      padding: 1.5rem;
    }
    .card {
      max-width: 28rem; text-align: center; padding: 2rem;
      border: 1px solid rgba(255,255,255,0.06); border-radius: 1rem;
      background: linear-gradient(180deg, rgba(255,255,255,0.025), rgba(255,255,255,0.01));
    }
    .icon {
      width: 56px; height: 56px; margin: 0 auto 1rem; border-radius: 12px;
      background: rgba(59, 141, 97, 0.15); display: flex; align-items: center; justify-content: center;
      font-size: 28px;
    }
    h1 { font-size: 1.125rem; margin: 0 0 0.5rem; color: #fafafa; }
    p { font-size: 0.875rem; color: #71717a; line-height: 1.6; margin: 0 0 1.25rem; }
    button {
      font: inherit; padding: 0.5rem 1rem; border-radius: 0.5rem; cursor: pointer;
      background: rgba(59, 141, 97, 0.2); color: #bbf7d0; border: 1px solid rgba(59, 141, 97, 0.3);
    }
    button:hover { background: rgba(59, 141, 97, 0.3); }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🌳</div>
    <h1>当前处于离线状态</h1>
    <p>LifeTree 已缓存关键页面与最近数据，你仍可查看部分内容。重新联网后即可恢复完整功能。</p>
    <button onclick="location.reload()">重试连接</button>
  </div>
</body>
</html>`;
