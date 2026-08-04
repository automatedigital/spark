# Adaptive routing compatibility — 2026-08-04

## Decision

Enable **Auto** as the default web routing policy. Keep explicit account models
available as thread pins. Resolve `lead`, `balanced`, `fast`, and `subagent`
against the account catalog; fall back to the next configured role or the
current primary model when a target is unavailable.

## Account and transport evidence

The account-scoped Codex catalog was refreshed at `2026-08-04T21:54:16Z`.
Spark's real `openai-codex` / `codex_responses` transport returned
`COMPATIBLE` for these minimal probes:

| Role probe | Model | Effort | API calls | Result |
| --- | --- | --- | ---: | --- |
| Lead | `gpt-5.6-sol` | low | 1 | Pass |
| Balanced | `gpt-5.6-terra` | medium | 1 | Pass |
| Subagent | `gpt-5.6-luna` | high | 1 | Pass |

The catalog reported a 272,000-token context window for all three. Sol and
Terra reported native multi-agent metadata `v2`; Luna reported `v1`. Spark does
not treat that metadata as proof of child-agent compatibility: Spark children
are separate `AIAgent` sessions with independent credentials, model, effort,
iteration limits, and lifecycle records.

## Deterministic compatibility gates

- Live account results are authoritative; cache and offline fallback results
  are visibly stale and non-authoritative.
- Unsupported reasoning effort resolves to an account-supported effort.
- Missing role targets follow the configured fallback chain without inventing
  model availability.
- Explicit model choice bypasses Auto and remains pinned.
- High-risk, destructive, ambiguous, recovery, code-edit, attachment, and
  long-context signals cannot silently select the fast role.
- Hysteresis keeps equivalent adjacent turns stable.
- Delegated work resolves the `subagent` role independently and permits no
  more than one retryable policy escalation.

## Pinned quality, cost, and latency matrix

The synthetic matrix at `tests/evals/routing/routing_matrix_v1.json` fixes the
prompt, context, and expected policy outcome for direct answers, UI work,
debugging, planning, research, long children, safety, recovery, explicit pins,
hysteresis, and unavailable fallbacks. It makes no paid calls and contains no
private prompts.

The release rule is safety and correctness first. Among role mappings that pass
that floor, Auto prefers the least expensive configured role; latency is only a
tie-break. The initial account mapping is Sol/high for `lead`, Terra/medium for
`balanced`, Luna/low for `fast`, and Luna/high for bounded `subagent` work.

## Scope note

This report validates the web release contract. Desktop packages were not
rebuilt. No claim is made that Codex native multi-agent `v1` and `v2` behavior
is equivalent to Spark child sessions.
