# 1. Preserve the prompt-caching invariant while splitting `run_agent.py`

Date: 2026-06-01
Status: Accepted

## Context

`src/core/run_agent.py` is ~11K LOC and owns the core conversation loop,
including system-prompt assembly and Anthropic prompt-caching cache-control
placement. The project's Critical Rules state: past context must not be altered,
toolsets must not change mid-conversation, and system prompts must not be rebuilt
mid-conversation — doing so invalidates the cache and multiplies cost.

We have decided to split this monolith into a `core/run_agent/` package for
maintainability. The risk is that decomposing the loop accidentally changes the
byte-exact content or ordering of cached message blocks (cache-control markers,
system prompt text, tool schemas), silently breaking caching with no test
failure — only a cost regression visible in production.

## Decision

The split is purely structural and **must preserve byte-exact cache behavior**.
We commit to:

1. **A caching-invariant golden test** added *before* any extraction: it captures
   the exact serialized request (system blocks, cache_control positions, tool
   schema order) for a representative conversation and asserts equality. This test
   gates every refactor commit.
2. **No behavioral edits during the split.** Moving code is allowed; "improving"
   prompt assembly, reordering blocks, or changing cache breakpoints is a separate,
   later change with its own review.
3. The caching-sensitive code (system prompt build, cache_control placement) lands
   in a single, clearly named submodule (e.g. `run_agent/prompt_cache.py`) so the
   invariant has one obvious home.

## Consequences

- The refactor is slower and more conservative than a free-hand reorganization,
  but a cache regression cannot slip through silently.
- The golden test becomes a permanent guardrail for all future loop changes, not
  just this split.
- If the golden test proves too brittle to author cheaply, that is a signal the
  caching logic is too entangled to split safely yet — and we stop and reassess
  rather than proceeding blind.
