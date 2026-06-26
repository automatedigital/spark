# 2. Use Project language while preserving workspace API compatibility

Date: 2026-06-25
Status: Accepted

## Context

Spark's glossary deprecates "Workspace" as a user-facing product concept in
favor of "Project" and "Chat". The web UI and docs had already started this
shift, but public routes, persisted source identifiers, SSE topics, and several
client methods still use `workspace` names.

Renaming every layer at once would break existing dashboard clients, saved
session sources, and route tests.

## Decision

Use **Project** and **Chat** in user-facing UI, docs, and new frontend component
names. Keep `/api/workspace/...`, `workspace:*` session sources, workspace SSE
topics, and compatibility client method names until there is a deliberate public
deprecation window.

Internal implementation may introduce canonical project-named routers, services,
and components, but compatibility wrappers remain tested.

## Consequences

- Product language becomes clearer without forcing a breaking API migration.
- Some compatibility names remain in code by design; they are not automatically
  cleanup targets.
- Future deprecation can be planned with route telemetry, migration docs, and
  compatibility tests removed only at the end of the window.
