# 4. Split the web dashboard behind compatible entrypoints

Date: 2026-06-25
Status: Accepted

## Context

`src/spark_cli/web_server.py` accumulated dashboard auth, settings, OAuth,
sessions, chat, cron, project files, preview control, admin actions, and SPA
mounting. It is a high-risk user-facing module, but downstream commands and docs
still import it as the dashboard app entrypoint.

## Decision

Split dashboard behavior into explicit routers and services while keeping
`web_server.py` import-compatible until downstream scripts and docs fully move.
The canonical shape is:

- `spark_cli/web_app.py` for app construction, middleware, lifespan, and SPA
  mount.
- `spark_cli/web/events.py` for SSE event queues and drop accounting.
- Route modules for chat, config, OAuth, admin, and project/workspace
  compatibility surfaces.
- Service modules for active web turns, agent lifecycle, persistence, and project
  file operations where extraction reduces risk.

Each extraction must be behavior-pinned with route/service tests before code is
moved.

## Consequences

- The dashboard can be changed in smaller slices without a breaking import
  migration.
- `web_server.py` may remain as a compatibility facade longer than ideal, but it
  should stop accumulating new endpoint logic.
- New dashboard functionality should land in the extracted router/service shape
  and be re-exported only when compatibility requires it.
