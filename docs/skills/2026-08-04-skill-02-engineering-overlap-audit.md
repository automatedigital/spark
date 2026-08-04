# SKILL-02 engineering skill overlap audit

Date: 2026-08-04

Branch: `skills-library`

Base commit: `4a5f3a67`
Scope: debugging, TDD, planning, review, research, prototyping, grilling, wayfinding, domain modeling, handoff, and subagent workflows.

## Result

No external skill was copied, modified, or vendored. The installed external root is the better home for user-invoked orchestration (`wayfinder`, `grill-me`, `grill-with-docs`, and `handoff`) and for the compact `research` and `prototype` workflows. Spark should keep its own bundled engineering canon, but improve it using the external red-capable debugging loop, pre-agreed TDD seams, and clearer handoffs between planning, delegation, and review.

The immediate library decisions are:

| Area | Decision | Reason |
| --- | --- | --- |
| Debugging | `improve-bundled` | Bundled `systematic-debugging` has stronger phase/checklist coverage; external `diagnosing-bugs` has the sharper first gate: one deterministic, fast, red-capable feedback loop. |
| TDD | `improve-bundled` | Both enforce red-green-refactor. External TDD adds an explicit public-seam agreement and vertical-slice rule; the bundled version has stronger Spark/test integration. |
| Planning | `merge-bundled` for `plan` into the planning family; `improve-bundled` for `writing-plans` | `plan` is a Spark-specific plan-only mode, not a second planning method. Keep its behavior as an alias/mode while presenting one canonical planning family. |
| Review | `merge-bundled` for `review-agent` into the review primitives; `improve-bundled` for Spark pre-commit/GitHub review | External `code-review` contributes a useful standards/spec split. Spark’s local review skills contribute security, tests, GitHub, and commit gates. |
| Research | `keep-external` | The external skill is a small high-trust-primary-source capture workflow. Bundled research skills are specialist tools, not a competing generic workflow. |
| Prototyping | `keep-external` | The external skill has a clear logic/UI branch and throwaway-artifact rules; no bundled generic prototype workflow was found. |
| Grilling / domain modeling | `keep-external`; `merge-bundled` for the duplicate bundled wrapper | External user-only wrappers compose cleanly with the external `grilling` and `domain-modeling` canon. The bundled wrapper is broader but duplicates that orchestration boundary. |
| Wayfinding / handoff | `keep-external` | These are explicit user-invoked orchestration and session-transition workflows with no bundled equivalent. |
| Subagents | `improve-bundled` for Spark’s dispatcher; `merge-bundled` for provider-specific shared guidance only | `subagent-driven-development` is the Spark execution contract. Claude/Codex/OpenCode docs are provider adapters and should share a thin common contract without being replaced by one opaque skill. |
| Broad Spark guide | `archive-bundled` from the default engineering index | `spark-agent` is a large general reference (27,714 bytes) rather than a focused workflow; keep it available as reference/help, but do not charge every engineering turn for it. |

## Evidence and measurement method

- Read the target repository’s `AGENTS.md`, `docs/AGENTS.md`, and the SKILL-02 section of `PLAN.md` before auditing.
- Read every primary comparison document listed in the JSON report. External paths under `/Users/joe/.agents/skills` and `/Users/joe/.codex/skills` were read-only inputs; no files there were changed.
- Spark bundled source was taken from the tracked `skills/` tree. The repository’s catalog confirms the software-development and autonomous-agent categories, but the audit treats the actual `SKILL.md` files as authoritative.
- `skill_md_bytes` is the UTF-8 byte length of the main `SKILL.md`, not a filesystem-block size.
- `index_entry_bytes` is the UTF-8 byte length of the exact prompt-index line `    - name: description` after Spark’s `extract_skill_description()` truncation.
- `estimated_index_tokens` uses the existing `agent.model_metadata.estimate_tokens_rough()` helper (`ceil(character_count / 4)`) on that index line. Provider-reported token usage remains authoritative; these are planning estimates.
- Usage is only the local Spark sidecar snapshot at `/Users/joe/.spark/skills/.usage.json` (last modified 2026-07-29). Missing records mean “not observed in this sidecar,” not proof of zero use in another host.
- Runtime eval coverage is evidenced by existing discovery/metadata/invocation tests. A pre-existing SKILL-08 harness and seven generic synthetic baseline/candidate cases exist under `evals/skills/` and `tests/evals/skills/`, but none targets the audited engineering workflows, so their content quality is not yet measured.

## Decision rules

`keep-external` means retain the installed skill as read-only and integrate discovery/invocation; it does not mean vendor it. `improve-bundled` means Spark owns a canonical bundled behavior and should close a documented gap. `merge-bundled` means reduce duplicate bundled entry points while preserving distinct references or modes. `archive-bundled` means remove a broad/default bundled entry from ordinary engineering discovery in a later change while retaining a recoverable source/reference.

The four decisions are recommendations only. This SKILL-02 change adds reports and validation; it does not alter any skill runtime, skill document, external root, PLAN, UI, branch, or commit.

## Capability findings

### Debugging

External `diagnosing-bugs` is compact (8,536 bytes) and starts with the strongest missing contract: build one tight, deterministic, agent-runnable command that can go red on the user’s exact symptom before theorising. It then minimises the repro, ranks 3–5 falsifiable hypotheses, instruments one variable at a time, writes a seam-correct regression test, and requires cleanup/post-mortem. Its weakness is lack of Spark metadata, license, related-skill links, and repo-specific test commands.

Bundled `systematic-debugging` is longer (10,534 bytes), MIT-declared, and more explicit about four phases, evidence gathering, root-cause discipline, regression verification, and Spark tools. It should remain canonical, but its first phase should gain the external red-capable loop and its final architecture handoff should link to the repository’s actual architecture guidance. Decision: `improve-bundled`.

### TDD

External `tdd` is 3,213 bytes and is unusually dense: public interfaces, pre-agreed seams, anti-tautology/anti-mocking guidance, vertical slices, and red-before-green. It references `tests.md` and `mocking.md`, both present beside the skill. It has no declared license or provenance metadata.

Bundled `test-driven-development` is 9,622 bytes, MIT-declared, and supplies the full red-green-refactor loop, checklist, Spark test commands, delegation integration, and troubleshooting. Keep the bundled document as the Spark canon, but add the external “agree seams before writing tests” and vertical-slice rule. Decision: `improve-bundled`.

### Planning and wayfinding

External `wayfinder` is 11,900 bytes and user-only. It is not an implementation planner: it creates an issue-tracker map, decision tickets, blockers/frontier, fog-of-war, HITL/AFK boundaries, and resolves at most one ticket per session (apart from research tickets). This is unique enough to keep external and directly supports the GitHub issue conventions in `docs/agents/issue-tracker.md` and `docs/agents/triage-labels.md`.

Bundled `writing-plans` is 7,305 bytes and gives exact paths, bite-sized tasks, code examples, verification, and handoff to subagent-driven development. Bundled `plan` is only 2,061 bytes and is Spark-specific plan-only behavior that writes `.spark/plans/` and stops. The two should not remain as competing planning concepts: merge `plan` as a mode/alias under one visible planning family, while improving `writing-plans` with clearer “decision map versus implementation plan” boundaries. Decisions: `keep-external` for `wayfinder`, `merge-bundled` for `plan`, `improve-bundled` for `writing-plans`.

### Review

External `code-review` is 6,740 bytes and reviews a fixed-point diff on separate Standards and Spec axes using parallel subagents. It has a clear empty-diff/spec-missing stop condition and a compact finding format, but no declared license or Spark-specific safety boundary.

Spark’s `requesting-code-review` is 8,604 bytes and is the pre-commit gate: added-line security scan, baseline tests/lint, self-review, independent reviewer, bounded auto-fix loop, and commit boundary. `github-code-review` is 13,629 bytes and adds local/PR review plus `gh`/REST fallback. `.codex/skills/.system/review-agent` is 2,661 bytes and is a read-only defect-first review primitive with strict actionable-finding criteria. Merge the latter primitive into the review family, preserve the GitHub and pre-commit modes, and borrow the external two-axis vocabulary. Decisions: `keep-external` for external `code-review`, `merge-bundled` for `review-agent`, `improve-bundled` for Spark review skills.

### Research and prototyping

External `research` is only 799 bytes but has a precise contract: use a background agent, prefer primary sources, write one cited Markdown artifact, and follow the repository’s storage convention. No generic bundled research workflow competes with it. The 103,542-byte bundled `research-paper-writing` document is a specialist ML paper pipeline and is not a replacement.

External `prototype` is 2,799 bytes and distinguishes logic/state prototypes from UI prototypes, requires one runnable command, in-memory state, visible state, and a throwaway/decision capture boundary. No generic bundled prototype workflow was found. Decisions: `keep-external` for both.

### Grilling and domain modeling

External `grilling` is 843 bytes and requires one question at a time, recommended answers, environmental fact lookup instead of asking, and explicit confirmation before acting. `grill-me` (147 bytes) and `grill-with-docs` (245 bytes) are user-only wrappers. External `domain-modeling` is 3,427 bytes and adds glossary/CONTEXT, edge-case scenarios, code cross-checks, and sparingly-created ADRs.

Bundled `grill-with-docs` is 3,717 bytes and includes Spark’s context/ADR format files, but its invocation is legacy `both`, so it is a duplicate model-visible orchestration entry point. Keep the external user-only wrappers and domain-modeling behavior; merge or retire the duplicate bundled wrapper after an explicit compatibility decision. Decisions: `keep-external` for external grilling/domain modeling and `merge-bundled` for the bundled wrapper.

### Handoff

External `handoff` is 879 bytes and user-only. It writes to the OS temporary directory, asks for the next session’s focus, includes suggested skills, references existing artifacts instead of duplicating them, and redacts secrets/PII. No bundled equivalent was found. Decision: `keep-external`.

### Subagent workflows

Bundled `subagent-driven-development` is 9,841 bytes and is the Spark implementation contract: parse a plan once, dispatch a fresh implementer per task, run spec-compliance review before code-quality review, fix/re-review until clean, then perform integration verification. It should remain canonical and gain links to the external handoff/wayfinder boundaries.

Bundled `claude-code` (34,362 bytes), `codex` (4,097 bytes), and `opencode` (7,351 bytes) are provider adapters with install/auth/PTY/background/parallel-worktree guidance. They overlap in orchestration mechanics but differ in provider CLI contracts; merge only their shared invocation safety and lifecycle metadata, not their command examples. The broad `spark-agent` guide is 27,714 bytes and overlaps the repository docs/runtime contract; archive it from ordinary engineering discovery while preserving reference access. Decisions: `improve-bundled` for the dispatcher/provider adapters, `archive-bundled` for the broad guide.

## Eval and provenance gaps

Current tests cover plumbing, not skill outcomes: external discovery and read-only behavior (`tests/agent/test_external_skills.py`), slash command behavior (`tests/agent/test_skill_commands.py`), prompt indexing (`tests/agent/test_prompt_builder.py`), provenance/identity (`tests/tools/test_skills_metadata.py`), and skill tool behavior (`tests/tools/test_skills_tool.py`). The report JSON records these links per skill where applicable.

The existing SKILL-08 harness is generic: its synthetic cases cover discovery, direct invocation, isolation, provenance, prompt-index cost, destructive safety, and persistent stop behavior, not debugging/TDD/planning/review/research/prototype/grilling/wayfinding/domain modeling/handoff/subagent outcomes. Before any `improve-bundled` or `merge-bundled` content ships, add scoped cases with identical prompts/toolsets, pinned model/effort, isolation, cost cap, blinded judging, and correctness/autonomy/actionability/safety/concision gates.

## Reproduction and validation

The machine-readable report is [2026-08-04-skill-02-engineering-overlap-audit.json](2026-08-04-skill-02-engineering-overlap-audit.json). Its structure is described by [skill-audit.schema.json](skill-audit.schema.json). Validate it with:

```bash
python scripts/validate_skill_audit_report.py docs/skills/2026-08-04-skill-02-engineering-overlap-audit.json
python -m pytest tests/skills_audit/test_validate_report.py -q
git diff --check
```
