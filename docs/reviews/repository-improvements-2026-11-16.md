# Repository improvement research — 2026-11-16

Baseline: Spark `a2f1bad3`; source checkout clean. This review extends the existing
PLAN.md rather than replacing its product/performance acceptance obligations.
Scope: root packaging metadata, contributor entry points, GitHub workflows,
dependency policy, and existing runtime ownership/documentation. No runtime
performance gains or missing-feature parity are claimed.

## Inspected comparisons

- A1: [Aider hooks](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/.pre-commit-config.yaml): staged contributor checks.
- A2: [Aider contribution guide](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/CONTRIBUTING.md): discoverable setup and test instructions.
- O1: [OpenHands dependency automation](https://github.com/OpenHands/OpenHands/blob/bbb2845b8b20ff73eede57905d54f2c184050f63/.github/dependabot.yml): separate ecosystem updates.
- O2: [OpenHands PR template](https://github.com/OpenHands/OpenHands/blob/bbb2845b8b20ff73eede57905d54f2c184050f63/.github/pull_request_template.md): structured reviewer evidence.
- H1: [Hermes security policy](https://github.com/NousResearch/hermes-agent/blob/e2fb450adcf74421fe9514f048319dfcbb5af6c1/SECURITY.md): private reports and explicit boundary context.
- H2: [Hermes license](https://github.com/NousResearch/hermes-agent/blob/e2fb450adcf74421fe9514f048319dfcbb5af6c1/LICENSE): distributable licensing text.
- G1: [GitHub private reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository).
- G2: [GitHub workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax): explicit token permissions and job timeouts.
- T1: [actionlint](https://github.com/rhysd/actionlint/tree/v1.7.7): workflow static validation.
- T2: [pip-audit](https://github.com/pypa/pip-audit): advisory checking for resolved Python distributions.
- T3: [EditorConfig specification](https://spec.editorconfig.org/): shared editor conventions.

These references supply ideas; no upstream implementation is copied. Aider,
OpenHands and Hermes have different architectures and license scopes. Spark's
existing MIT metadata is the basis for adding its root license text.

## Ranked recommendations

The first ten prioritize concrete repository-wide gaps with small, independently
verifiable changes. This is a delivery ranking for repository maintenance, not a
claim that editor settings outweigh runtime reliability. Existing PLAN.md packets
retain their acceptance gates. Rows 11–25 require a separate scoped follow-up;
several extend existing implementations rather than add new systems.

| Rank | Improvement and Spark evidence | Inspiration | Acceptance |
| --- | --- | --- | --- |
| 1 | Supply root MIT text: pyproject declares MIT but no root LICENSE ships. | H2 | License agrees with metadata; preserve third-party notices. |
| 2 | Add private reporting policy: no SECURITY.md; private reporting initially disabled. | H1, G1 | Enable and read back reporting setting; link correct repository; avoid invented response guarantees. |
| 3 | Automate dependency proposals: no Dependabot config for Actions, nested npm or Python. | O1 | Parse config, cover real manifest directories, keep npm exact pins and review major updates separately. |
| 4 | Bound CI privileges and execution: three quality workflows lack explicit permissions; two jobs lack timeouts. | G2 | Read-only contents; positive timeouts; preserve commands and triggers; hosted jobs pass. |
| 5 | Validate workflow edits: no actionlint gate; existing inline JS produces SC2016 false positive. | T1 | Gate all workflow files; suppress only the specific JS command, demonstrate other errors still fail. |
| 6 | Add opt-in staged checks: no root pre-commit config. | A1 | Validate YAML/TOML, large files, conflicts, private keys, secrets and generated manifest; injected failures are rejected. |
| 7 | Audit Python dependencies: npm audit exists but no Python advisory gate. | T2 | Fresh core/web environment audit on PR, schedule and manual trigger; no blanket advisory ignores. |
| 8 | Structure issue/PR evidence: no templates. | O2, A2 | Unique required form fields, existing triage labels, reproduction/version/surface fields and verification checklist. |
| 9 | Share editor defaults: no EditorConfig. | T3 | Match current Python/Rust versus frontend indentation; preserve Markdown hard breaks. |
| 10 | Add discoverable contributor entry: rules exist in AGENTS.md but no CONTRIBUTING.md. | A2 | Setup commands retain cwd, use .venv/Node 22 and isolated SPARK_HOME; links resolve. |
| 11 | Add CI secret scanning alongside local hooks, without exposing findings in public logs. Local hook alone is bypassable. | A1, H1 | Seeded synthetic key fails CI; historical baseline handled explicitly. |
| 12 | Pin third-party Actions to audited SHAs with update automation. Existing workflows use movable version tags. | O1, G2 | Resolve every action, preserve version comments, verify runners. |
| 13 | Publish a tested Python constraints snapshot for release builds. pyproject uses ranges. | O1, A2 | Clean install reproduces release dependency graph on supported platforms. |
| 14 | Include Cargo and root npm in dependency automation after confirming their release ownership. Initial draft covers only web/npm, pip and Actions. | O1 | Discover manifests, avoid overlapping lockfile writers, test Rust/Tauri compatibility. |
| 15 | Add SBOM and provenance to release artifacts. Desktop packaging has distinct source/build/install claims. | H2, G2 | Tie artifact digest to exact source and dependency graph. |
| 16 | Exercise installed wheel/sdist in CI. Editable installs can hide missing packaged files. | A2 | Clean environment imports and doctor work without repository cwd. |
| 17 | Expand Python compatibility coverage beyond the 3.11 quality job. Metadata permits >=3.11. | A2 | Supported version matrix passes focused startup/profile contracts. |
| 18 | Ratchet more Ruff families after measuring current debt. python-quality intentionally enforces a subset. | A1 | Baseline count falls without broad ignores or unrelated rewrites. |
| 19 | Reduce incremental mypy exclusions using small module batches. Existing ratchet documents remaining overrides. | A2 | Remove each override only after relevant checks pass. |
| 20 | Formalize dependency-advisory triage with affected runtime scope and expiry. Audit failure alone is not remediation. | H1, T2 | Reproduce affected usage; fix or record narrowly justified dated exception. |
| 21 | Run ownership/reconnect replay contracts on a periodic schedule. Existing release-contracts workflow is PR/manual. | G2, existing PLAN.md | Same persistence fixtures; no live providers or user profile writes. |
| 22 | Gate root license and bundled third-party notices in release archives. Bundled skills already carry independent licenses. | H2 | Wheel, sdist and desktop archives retain applicable notices. |
| 23 | Verify dependency update PRs against cache/lazy-startup invariants. Tool SDK changes may alter imports or payloads. | O1, existing ADRs | Cache goldens, minimal startup and manifest checks on matching head. |
| 24 | Document safe rollback per release artifact and profile schema. Installed package evidence is separate from compilation. | H1, existing PLAN.md | Restore binary without overwriting newer profile data; rehearse on isolated home. |
| 25 | Add review ownership for shared schemas, migrations and generated artifacts. AGENTS.md already requires a single writer. | O2, existing AGENTS.md | Maintainer-approved ownership mapping routes review without blocking unrelated changes. |

## Verification boundaries

The ten delivery PRs change repository policy, automation and documentation;
they do not change app runtime or regenerate frontend bundles. Validate formats,
negative hook/linter cases, clean dependency resolution and affected hosted jobs.
No browser or native app behavior claim follows from these changes. Record each
PR head and hosted result in the tracking issue before closing the work.
