# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-26

First tagged release of LifeTree — the "life decision tree" intelligent
decision support system. This version ships the MVP foundations: goal
management, knowledge graph, scenario branching, AI advisor, plugin
system, PWA support, multi-user auth, and i18n.

### Added

#### Authentication & Multi-user
- Email + password auth with JWT access/refresh tokens, plus optional
  email-verification (send-code / register-with-code) flow.
- OAuth login (Google / GitHub / Microsoft) with `/auth/oauth/{id}/start`
  and `/auth/oauth/{id}/callback`.
- Two use modes: `single` (default, no login required) and `multi`
  (login required, admin role gated by `LIFETREE_ADMIN_USER_IDS`).
  Toggleable via `PUT /settings/use-mode`.
- Admin endpoints: `GET/PATCH/DELETE /admin/users`, `GET /admin/stats`.
- AuthGate: in single-user mode the app runs without prompting login;
  in multi-user mode the login dialog is non-dismissible.
- User data isolation by `user_id` (events, sources, plugins, chat
  conversations partitioned in localStorage by `lifetree.chat.conversations.v2.<userId>`).

#### Plugins
- User-uploaded plugin system: `POST /plugins/upload` with AST syntax
  check, contract validation, and import blacklist (`os`, `subprocess`,
  `socket`, `ctypes`, `pickle`, `importlib`, …). Stored under
  `plugins/user_uploaded/{plugin_id}.py` with metadata in the
  `user_plugins` table.
- `DELETE /plugins/{id}` (soft-delete) and `PATCH /plugins/{id}/enabled`.
- Docker named volume for `/app/plugins/user_uploaded/` so custom
  scripts persist across container restarts.
- Built-in sample plugins: `sample_rss_feed`, `sample_web_scraper`.

#### Notifications & SMTP
- Notifications API with `severity` (urgent/warning/info), `status`
  (read/unread), `channel` filters; bulk mark-read and unread-count.
- SMTP configuration in settings (server, port, username, password,
  sender email/name, TLS/SSL), with send-test-email functionality
  (permission-checked before sending).
- Real-time SSE push for new notifications.

#### i18n
- Six locales: 简体中文 (default), 繁體中文, English, Español, Deutsch,
  Français. Cookie-driven (`lifetree.locale`, 1-year validity) with
  `navigator.language` auto-detection. Fallback to `zh-CN` for missing
  keys.

#### PWA
- Installable PWA with manifest, service worker, and offline support.
- Drawer-mode sidebar: in PWA mode (or viewport < 1024px) the sidebar
  hides by default and is opened as a slide-in drawer via the per-page
  `SidebarToggleButton`. CSS pre-hydration fallback via inline script +
  `html.pwa` / `html.drawer-mode` classes prevents rail flash.
- Safe-area padding for notch / home indicator.
- iOS `navigator.standalone` detection (covers cases the `display-mode`
  media query misses).

#### AI Advisor & Chat
- Streaming SSE chat (`POST /chat/stream`) with token-by-token
  rendering and Markdown support. Direct backend connection bypasses
  the Next.js dev proxy (which buffers SSE).
- Conversation history sidebar with rename, new-conversation, and
  per-user scoping. Per-page `SidebarToggleButton` toggles the drawer
  in PWA / narrow viewport; persistent rail (w-16 ↔ w-60) otherwise.
- File upload on the chat page (`POST /ingest/upload`) with auth-token
  attachment via the shared `request` helper.
- Tool-call UI rendered inline within the main content (not at the
  start or end of the message).

#### Graph & Scenarios
- Knowledge graph with nodes/edges, minimap (`!w-64 !h-40`), and
  non-overlapping node/label layout.
- Scenario branching, merging, and running (`POST /scenarios/{id}/branch`,
  `/merge`, `/run`); scenario comparison tree view (color bars above
  nodes removed) and detail panel.
- Dashboard handles undefined `goalId` by returning null instead of
  calling the API with undefined.

#### Settings & Platform Config
- Settings page with SMTP config, send-test-email, API-key reveal
  (plaintext when eye button clicked — no "configured, enter new value
  to overwrite" stub), and deeply-nested colored capsule UI adapted
  for light theme.
- Admin-only platform configuration page for model and service
  APIs/keys (visible only to admin users).

#### Infra & CI/CD
- GitHub Actions `build-and-push.yml`: builds `lifetree-backend` and
  `lifetree-frontend` Docker images on `main` and `v*` tags, pushed
  to `ghcr.io`. Restricted to `linux/amd64` (arm64 frontend build
  fails in CI).
- GitHub Actions `release.yml`: on `v*` tags, creates a GitHub Release
  with notes pulled from this CHANGELOG.
- Alembic migrations: initial schema, LLM config tables, user auth
  fields, user plugins table, `user_id` added to events/sources/plugins.
- DB-based app config with auto-migration on startup; `use_mode` stored
  in `app_config`.

### Fixed
- Streaming SSE responses fail when routed through the Next.js dev
  proxy — direct connection to the backend is now used for SSE.
- `qwen3-rerank` connection failure caused by incorrect URL routing;
  fixed by using the native endpoint
  (`/api/v1/services/rerank/text-rerank/text-rerank`) for DashScope,
  while `gte` / `qwen3-vl-rerank` use the compatible endpoint.
- GitHub Actions CI/CD for Docker image builds fails when building
  the frontend for arm64 — restricted to `linux/amd64`.
- Next.js 16 requires Node.js 22; older Node versions caused frontend
  build failures.
- SMTP connection unexpectedly closing due to incorrect SSL/TLS
  configuration — proper port (465 for SSL, 587 for STARTTLS) and
  option selection.
- Goal detail page `undefined 'dashboard.title'` due to missing API
  fields — added `goal_title`/`goal_scenario`/`goal_target_date`/
  `goal_status` to the dashboard API response.
- Dropdown menu in the expanded sidebar was unclickable: the parent
  `<aside>` `backdrop-blur-sm` created a stacking context that scoped
  the menu's `z-index`. Fixed via React Portal to `document.body`.
- Conversation page attachment upload returned 500: `ingestUpload`
  used a raw `fetch` without the auth token. Refactored to use the
  shared `request` helper (auto-attaches `Authorization: Bearer` and
  supports 401 refresh-and-retry).
- Duplicate brand row in the PWA sidebar drawer — consolidated into
  a single `SidebarContent` brand row with optional close button.

### Changed
- README split into per-language files (zh-CN, zh-TW, en, es, de, fr).
- Chat history sidebar toggle button uses a `history` icon instead of
  the previous chat icon; chat history entries no longer display chat
  icons.
- Information entry page sliders adapted for light theme.
- PWA mode no longer renders a mobile top bar — the sidebar toggle
  lives in each page's heading instead.
- `ThemeSliderRow` in the user menu no longer closes the dropdown on
  click (user can preview multiple themes).
- Logout now surfaces a native LifeTree `ConfirmDialog` instead of
  logging out immediately.
- `/notifications` page: removed the "实时连接已就绪" pulse indicator;
  unread count badge retained.
- Use mode configured via `LIFETREE_USE_MODE` env var (default
  `single`), stored in `app_config.use_mode`.
- Minibar dropdown menu positioning: bottom edge at avatar's top edge
  with 4px gap, clamping to top viewport edge (minimum 8px margin) if
  overflow occurs; auto-closes on outside click.
- All browser native dialogs/popups replaced with LifeTree's existing
  dialog/popup components.
- Toast notifications allow text selection and copying.
