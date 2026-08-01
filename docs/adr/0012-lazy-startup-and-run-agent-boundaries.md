# ADR 0012: Lazy startup and run-agent boundaries

## Status

Accepted.

## Decision

Built-in tool schemas are generated into a lightweight manifest. Importing
`core.run_agent` registers schema-only entries; the registry imports a handler
module once, under a per-module lock, when a tool is first invoked. Configured
MCP profiles retain eager discovery, while unconfigured MCP, plugins, browser,
voice, image, messaging, cron, connector, and desktop feature modules remain
behind their owning route.

`from core.run_agent import AIAgent` remains the public contract. Internally,
provider payload validation, response normalization, retry policy, persistence
transformations, turn initialization, prompt caching, scheduling, sanitization,
and stdio safety live in responsibility-specific modules. The large orchestration
loop remains in the facade until each provider's golden transcript coverage is
strong enough to move it mechanically.

## Cache contract

The generated manifest is deterministic and CI validates it by importing each
handler module in an isolated subprocess. Schema order and content therefore do
not depend on which handlers happened to run earlier in a process. Dynamic
per-host schema descriptions operate on cloned definitions and never mutate the
manifest or an active conversation's toolset.

## Rollback

Restore eager imports in `core.model_tools` while retaining manifest validation.
No saved session format, public import, tool name, or handler signature changes.
