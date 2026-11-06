# Upgrade integration candidate — 2026-11-06

Main base: `93447f64a1bacd7d298f7647ab49ec765ef0dd47` (merged CI repair #238).
All current feature heads are preserved by merge ancestry, not squashed or cherry-picked.
Foundation `702d1ca9` was merged after current SP01; its shared foundations and fixture repairs were retained.
No PLAN acceptance boxes, lockfiles or generated production bundle are changed.

## Exact input graph

| PR | Head | Published base |
| --- | --- | --- |
| #213 | `4d9ad7f3637adbef13b03a871bee7b9334dcabf0` | `main` |
| #214 | `53d527d7f61a094ae258ac5afc6c4f8c61c2e3a5` | `feat/sp01-submission-acceptance` |
| #215 | `61a37907c8fdbc23afd5a6d2e5816f0fc1b06c58` | `feat/sp01-submission-acceptance` |
| #216 | `9c04091e4c62ad0edaf717ae564c3f18e7d51c13` | `feat/sp01-submission-acceptance` |
| #217 | `9acb185aeba859fade1b83b8171db85bf5b0b6c0` | `fix/sp09-chat-bundle-budget` |
| #218 | `805f98dcd072a4d70d001ba914b57637af109174` | `feat/cron-schedule-preview` |
| #219 | `88097547172754d8eb953c7f604a6bd51ad12e23` | `feat/sp10-provider-catalogue` |
| #220 | `3d71089ea4fb5f33596ebe4be119195ba372f49a` | `feat/sp01-submission-acceptance` |
| #221 | `ae027cef24f3b3480259c31907ae76bb02518284` | `feat/sp10-provider-catalogue` |
| #222 | `42ab3cc91f44d5edaa00820c7eea296f49d01cd8` | `feat/sp10-provider-catalogue` |
| #223 | `1c2c74954fab875ebf97c5d66429f16fe6f7ab04` | `feat/sp10-provider-catalogue` |
| #224 | `95fd191c62ad1501538071a4ba46ad230fc1ab1d` | `feat/sp01-submission-acceptance` |
| #225 | `3224c032a542900edc79ada36e9aaf24d82d1a42` | `feat/sp21-memory-browsing` |
| #226 | `8e59333ea015f3023a4e8a06e7491ea67a0dfed3` | `feat/sp02-recovery-snapshot-final` |
| #227 | `0057bccf2e24d70076caafe9bc7c94a38ddcf314` | `feat/sp01-submission-acceptance` |
| #228 | `4a19f40b8d3e3687ee0668b4fd44d6a12ab67c38` | `feat/sp02-recovery-snapshot-final` |
| #229 | `1ef4d97cc946e8b91a4781d9c2e107c5b83ce0e1` | `integration/sp-foundations-20261106` |
| #230 | `b76eeef4ecc2fb1b9238bd73e7fc7779fc431d46` | `feat/sp02-recovery-snapshot-final` |
| #231 | `76cf5a72e8bc235e10fd50ab9ac2271e47f3e6f3` | `integration/sp-foundations-20261106` |
| #232 | `8ea835487584fc6090861cf405a128cd037b0d72` | `feat/sp21-memory-browsing` |
| #233 | `87885af0096c99d201e408e5b4864607c306d409` | `feat/sp02-recovery-snapshot-final` |
| #234 | `5f371d7cd41b3c525da42adcd974522151594ceb` | `integration/sp-foundations-20261106` |
| #235 | `c489b507f23cf92b96898d5a1acbb25ea7adb0a5` | `integration/sp-foundations-20261106` |
| #236 | `6a44110a19b3c313f2fe8f1061eeae82bb6001f7` | `integration/sp-foundations-20261106` |
| #237 | `2edaa11132e38693a724410e5bfefaabe8ff1fe2` | `feat/sp22-skill-selection` |
| #238 | `f67d88a9064ac50fcac9438b79ddcab33540f956` | `main` |

## Integration decisions

- Foundation retains SP02/03/04/09/10/12 ancestry; exact final SP04 head merged separately to preserve its graph. SP17 is retained through SP18.
- Settings imports retain model discovery, MCP readiness, searchable destinations and Auto roles. Role editor is common and has a focusable field identity.
- Palette keeps bounded scoped SP12 reads and SP13 exact message IDs while using SP25 destinations. No eager all-session loading is restored.
- Model API preserves all endpoints plus optional cancellation signals, including conversation models.
- Chat callbacks retain retry ownership and first-token timing state together. SP14 typed context and SP15 execution marks coexist.
- SP24 durable route endpoint tests now use the actual SP15 TurnTiming serializer rather than a copied wire fixture.
- SP25 search explicitly targets SP14 compression threshold, SP23 readiness and SP24 role mappings. Empty readiness lists remain focusable.
- SP19 terminal cleanup and SP20 paged tree merged without textual conflicts in workspace_routes.py; both focused suites passed.
- Added two mixin attribute declarations for the new retry paths; runtime behavior is unchanged.
- Main curator isolation, PR236 resolver keyword compatibility, and PR234 idle fake-child cleanup retained.

## Validation

- Node v22.22.1 at `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`; nested npm ci.
- Frontend: 647 tests / 107 files pass with `--maxWorkers=2`. A concurrent default-worker run timed out the unchanged 10k-message replay at 5 seconds; bounded rerun passed without changing assertions/timeouts.
- ESLint: zero errors; two existing App.tsx hook dependency warnings. TypeScript build passes.
- Production build in `/tmp/spark-integration-final-built` passes; initial gzip 261.57 KiB / 600 KiB budget. Generated repository output restored and new remnants removed.
- Backend: 152 primary contracts + 135 neighbors + 6 quiet/retry cases passed. Final route/retry selection: 44 passed. These selections overlap; totals are not unique test counts.
- Clean Ruff CI families and manifest check pass. Full Ruff retains 298 baseline findings.
- Inspector built-browser: 11 flows pass, including three live chat switches, draft/attachment/child retention, restart/reconnect, project compose and detached scroll 1000 -> 1000 px. No inspector fix justified; original assertion preserved.
- Cold mypy (`--cache-dir=/tmp/spark-integration-mypy-cold`) passes all 157 source files. Initial imported-module diagnostics were rechecked against main and resolved by the two explicit mixin declarations; no suppression was added.
- Combined settings browser passes: search reaches and focuses actual Auto roles, compression threshold and MCP readiness containers. Added this regression to the hosted browser job. Initial fixture attempts lacked routing/memory response shapes; corrected fixtures passed without weakening destination assertions.

## Limits

No 12k full local Python suite, real provider inference, native package, release or hosted acceptance claim. Full hosted CI is reserved for this single integration PR. Original PRs/main remain unmerged by this work. Browser fixtures use isolated state and synthetic provider boundaries.
