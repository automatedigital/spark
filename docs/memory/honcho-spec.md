# Honcho Integration Spec

Design comparison between Spark and openclaw-honcho, plus porting notes for other Honcho integrations.

## Two Integrations, One Backend

Both Spark (Python, runner-integrated) and openclaw-honcho (TypeScript hooks) use the same Honcho peer API — `session.context()` and `peer.chat()` — but they make different tradeoffs around latency and caching.

| Dimension | Spark | openclaw-honcho |
|-----------|-------|-----------------|
| Context fetch | Once per session (cached system prefix); no Honcho HTTP on the hot path after turn 1 | Blocking `before_prompt_build` on every turn |
| Dialectic | Prefetched async via daemon threads | On-demand via tools |
| Memory modes | `user_memory_mode` / `agent_memory_mode` | Honcho-only |
| Multi-agent | Single-agent | Parent/child via hooks |
| Tool surface | `query_user_context` + config | Multiple Honcho tools |

## What to Bring Forward

### Port from Spark
- Async prefetch at turn end (caches context for the next turn)
- Dynamic reasoning level adjustment
- Per-peer memory modes (`user_memory_mode` / `agent_memory_mode`)
- AI peer identity seeding (`seed_ai_identity` / SOUL)
- Session naming
- CLI hints in the system prompt

### Port from openclaw
- Message deduplication via `lastSavedIndex`
- Metadata stripping before submission
- `peerPerspective` field on context responses
- Workspace `agentPeerMap` for multi-agent coordination
- Tiered tool access model

## User-Facing Docs

For setup and daily use, see [Honcho](./honcho.md) and [Memory Providers](./providers.md).

Implementation lives in `src/plugins/memory/honcho/`.
