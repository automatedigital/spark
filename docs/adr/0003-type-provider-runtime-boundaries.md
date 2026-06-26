# 3. Type provider runtime boundaries

Date: 2026-06-25
Status: Accepted

## Context

Provider/model selection affects the agent loop, CLI setup, gateway sessions,
auxiliary model calls, fallback chains, credential refresh, and API-mode
selection. Historically, these paths passed loose dictionaries around, which made
fallback and provider-specific behavior easy to regress.

## Decision

Provider runtime resolution returns typed runtime records at the boundary:
provider id, model id, API mode, base URL, credential source, timeout policy, and
request overrides. Downstream code should consume those records instead of
guessing from loosely shaped dictionaries.

The migration is incremental: typed seams are required at resolver and auxiliary
client boundaries first, then expanded where they reduce mypy and behavioral
risk.

## Consequences

- Fallback, credential refresh, and provider-specific API-mode selection become
  easier to test directly.
- New providers must fit the typed runtime contract instead of adding ad hoc
  dict keys.
- Some legacy dict inputs remain accepted for compatibility, but they should be
  normalized before crossing runtime boundaries.
