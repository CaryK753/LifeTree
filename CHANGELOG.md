# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-08-03

### Added

- Local-private desktop runtime: bundled SQLite, encrypted local storage,
  embedded graph/vector adapters, in-process jobs, and an on-demand Python
  sidecar with a lightweight Rust proxy.
- Signed desktop updater: GitHub Release now publishes updater archives,
  signatures, and `latest.json`; the desktop host verifies, downloads, and
  installs new versions on restart.
- Native update dialogs from the macOS menu bar and Windows tray for no
  update, available update, and update-check failure states.
- Decision-tree and goal detail workspaces, plus dedicated presentation routes
  for a lower-friction navigation flow.

### Changed

- macOS menu-bar LifeTree icon is now white; Windows keeps its theme-aware
  notification-area icon.
- AI advisor tool-call budget is now 128 per turn; its LangGraph recursion
  budget scales with that limit.
- The advisor's existing action-calendar tools are verified and remain part of
  the built-in tool set: list, reschedule, unschedule, set recurrence, and
  update action status.
- New goals default to `active`, and the advisor reuses an equivalent existing
  goal instead of repeatedly creating duplicates.

### Fixed

- Local desktop startup no longer exposes business pages before the worker is
  ready, and sidecar processes exit when their desktop host exits.
- Local SSE no longer attempts to connect to deployment-only Redis.
- Route transitions no longer animate from transparency, eliminating the
  desktop black/white flash caused by the WebView background showing through.
- Desktop proxy routing, token reuse, CORS, and release CI dependency setup
  are hardened for packaged local operation.

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

## [0.2.0] - 2026-07-29

Second tagged release. Expands LifeTree with user-runtime extensibility
(personal tools, skills, MCP), legal consent flow, scenario evolution
tracking, per-source cron-style refresh, personal model/service
configuration, and a redesigned `/auth` ASCII scene.

### Added

#### User Runtime: Tools, Skills, MCP
- `user_runtime` model + API (`/users/me/runtime/*`): per-user
  external tool definitions (name, endpoint, auth, schema) that the AI
  advisor can call like built-in tools. Stored in `user_runtime_tools`.
- `user_skills` API: user-authored Python skills uploaded and imported
  via `skill_import` service (AST-checked, sandboxed imports).
- MCP settings card on `/settings`: configure Model Context Protocol
  servers per user; advisor can invoke MCP-provided tools.
- Skill settings card on `/settings`: upload / enable / disable user
  skills with a managed import pipeline.
- Personal service keys card: per-user API keys for OpenAI / Anthropic /
  Alibaba / DeepSeek / etc., stored encrypted and scoped to the user's
  own advisor runs (not shared with other users in multi-user mode).
- Personal model settings card: per-user default model selection and
  per-task overrides (chat / extraction / reasoning).
- User service policy card: per-user rate limits and allowed provider
  lists (admin-configurable defaults, user-overridable within bounds).
- Alembic migration `a6b8d0f2c4e6_add_user_runtime_tools`.

#### Legal Consent & Privacy
- `legal` core module + `legal_consent` migration: versioned Terms of
  Service and Privacy Policy documents; users must consent before first
  use. Consent records stored per user with document version + timestamp.
- `/terms` and `/privacy` frontend pages rendering the current documents
  via the `legal-document` component.
- `legal-consent` dialog shown on first visit post-registration.

#### Scenario Evolution Tracking
- `evolution` service + `scenario-evolution` component: records each
  scenario state transition (draft → active → dormant → merged/closed)
  with timestamp, trigger, and delta, rendering a timeline view in the
  scenario detail panel.
- `reasoning/evidence` + `reasoning/factor_model` modules: structured
  evidence ledger and per-factor model used by the Bayesian + Monte
  Carlo engines for auditable scenario reasoning.

#### Source Cron Refresh + Risk Alerts
- Per-source auto-refresh schedule: `auto_refresh`,
  `refresh_interval_minutes` (default 1440 = 24h, user-configurable down
  to 1 minute), `next_refresh_at`, `last_refreshed_at` on
  `InformationSource`.
- Celery beat task `refresh_due_sources` (runs every minute) re-fetches
  due source URLs via Tavily Extract, ingests new events through the
  structuring pipeline, and advances `next_refresh_at`. High-risk
  events extracted during refresh trigger the standard risk-propagation
  + notification flow.
- `PATCH /sources/{id}/schedule` and `POST /sources/{id}/refresh` API
  endpoints.
- Frontend `source-schedule-dialog` with 1m / 5m / 30m / 1h / 6h / 12h /
  24h / 7d presets and custom minute input; manual "refresh now" button.
- Alembic migration `e4f6a8b0c1d2_add_source_refresh_schedule`.

#### Auth Page ASCII Scene
- Redesigned `/auth` background: forest of randomly grown ASCII trees
  with wind sway, day/night themes.
- Day theme: ASCII sun, drifting clouds, randomly flying birds with
  flapping wings.
- Night theme: crescent moon, twinkling stars, meteors flying
  right-to-left at an angle above the treetops, fading as they travel.
- Ground layer with grass line + 3-row dense ASCII soil (`#`/`%`/`&`/`@`).
- Victorian-style street lamp (small lantern nested between twin iron
  rods, ~32-row tall pole, base plate) placed beside a park bench and
  a seated person, grouped on the left side to avoid the centered login
  dialog.
- Lamp glow halo in dark mode.
- `prefers-reduced-motion` static fallback.

#### Chat & AI Advisor
- `chat-model-selector`: per-conversation model picker in the chat
  toolbar.
- `ai-elements` component overhaul: richer tool-call rendering with
  proper icons (no emojis), inline placement within the main content.
- AI avatar uses `@lobehub/icons` CDN to show the current model's brand
  icon (e.g. DeepSeek icon when model name contains "deepseek").

### Changed
- Chat history sidebar defaults to collapsed on first visit; expands
  only when the user explicitly opens it (preference persisted).
- `/auth` ASCII art extracted into `ascii-scene-art.ts` for reuse and
  easier editing.
- README documentation updated across all 7 language variants.

### Fixed
- `structuring.py` undefined `user_id` variable in multi-user scenarios
  (NameError under certain ingestion paths).
- OAuth callback routing: dynamic `[provider]` path parameter added so
  provider-specific callbacks resolve correctly.
- AuthGate no longer renders children when unauthenticated in
  multi-user mode, preventing spurious SWR API requests.
- `DEFAULT_USER` role is now `user` (not `admin`); admin privileges
  applied dynamically via `_apply_admin_override`.
