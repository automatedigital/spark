# P09 panel ownership changes — 15 October 2026

**Consolidated functional changes; memory release acceptance remains open.**

The reviewed source is integrated into `feat/app-orchestration-upgrade`. Root
validation passes lint, TypeScript, **448 frontend tests**, the canonical build
(**242.40 KiB gzip**) and all **nine production recovery flows**. No experimental
heap helper is included in the application changes.

The diagnostic navigation batch retains its original outcomes: original exit 0,
candidate exit 1 on a tree request aborted during the driver's deliberate reload.
Neither continuing-owner control ran. Offline snapshots show collection of the
candidate's specific cycle-2 generations, but later pending model requests still
retain render contexts. This is not complete memory/performance acceptance.
Further diagnostics were stopped during consolidation following the user's scope
correction. Native packaging, installed-platform QA and rollout remain unfinished.

The remainder records historical implementation checkpoints and evidence. Their
failures are preserved; earlier preparation-only statements describe those checkpoints.

Implementation base is
`e8d6713ddd59c029f6dcd6d915df9ca42b4c71eb`, isolated branch
`fix/p09-panel-ownership`. No release, package, canonical bundle, backend,
gateway, lockfile or PLAN change is included.

The two narrow callback ablations in the retained-contexts report were rejected:
both retained identical timeline object growth despite rerouted strong paths.
This candidate instead ends the whole ChatPanel view lifetime on real thread
navigation. ChatPage owns one current navigation token, and a return to a thread
gets a fresh token. It retains only bounded primitive scroll bookmarks outside
the panel, keyed by backend/profile scope and session. Inactive panels,
controllers, DOM nodes and transcripts are never stored in that map.

Acknowledged send-ID continuation is separate from navigation and fork. Its
adoption carries owner token, scope, request generation, previous ID, next ID
and reason. A still-current request must validate before selection and local
controller adoption; a continuation preserves the mounted view and buffered
stream. A fork gets a fresh view. Hero/project creation keeps its existing
pending-message flow and does not migrate or repost the null-thread draft.

Successful sends continue to acknowledge the exact originating draft revision
after navigation. Edits after submission still prevent that acknowledgement
from clearing newer work. Upload setters retain their initiating draft key.
Exact loaders capture the rendering session instead of resolving a mutable
replacement session at invocation. Originating copy/brief effects may complete;
retired responses cannot select or mutate a replacement view. Existing Web
approval action-ID guards remain intact.

Controller delayed timers and nested prepend RAFs are cancelled on unmount;
history/recovery/fork/retry callbacks are owner-fenced, and stream bridge callback
refs are retired. Existing listener, observer, event-bus, poll and virtualizer
cleanup runs with keyed unmount. Unmount never issues backend Stop.

Before the root's search diagnostic hold: own `npm ci` completed with verified
Node **22.22.1**, executable
`/Users/joe/.nvm/versions/node/v22.22.1/bin/node`; TypeScript passed; 20 focused
tests passed; a production build completed under
`/tmp/spark-panel-ownership-422f1487/build`. Lint had zero errors and one missing
effect dependency warning, corrected afterward. At an earlier candidate checkpoint, TypeScript and
lint passed cleanly, all **440 frontend tests** passed, and a temporary
production build completed under `final-build/` in the same artifact directory.
Those build/production-browser receipts precede the later scope and streaming repairs.
Neither temporary build is the canonical release bundle.

The actual ChatPage held-response driver passes six flows in `behavior-1/`:
late accepted/rejected sends, edits after send, uploads after navigation,
same-mounted-node acknowledged ID continuation and fresh-owner fork. Its extended
`behavior-2/` attempt completes a seventh late-fork check, then fails waiting for
an exact-copy loader request: the 56,022-character stimulus was below the existing
128 KiB completed-message window, so it used ordinary copy. This is a fixture
mistake, not an app exact-loader failure. `behavior-3/` increases the source
fixture to 168,022 characters, above that window, then passes all **nine** checks,
including a retired exact copy and retired promote-to-origin-brief. Original
failed logs/screenshot/result remain unchanged. No assertion or timeout was relaxed.

Unchanged chat contracts pass, including active-stream switching/revisit,
copy/retry/fork, prepend-anchor preservation and stop/redirect behavior.
Production draft recovery passes all **nine** checks using an independently built
temporary bundle and real isolated backend. No external provider or messaging
send is used. The final browser screenshot was inspected; the selected fork's
transcript, sidebar and composer render correctly in that sample.

The production inspector records all **eleven behavior checks** and zero page
errors, including child selection, stream switching, detached scroll
**1,000 -> 1,000 px**, restart and project-create failure preservation. Its
**aggregate exit is 1**: the final asset assertion requires every response to be
200, while some reloads received 304. The response list contains earlier 200s
for the same URLs but lacks ETag/body/cache-request receipts. Valid revalidation
is therefore not established, the assertion is unchanged, and this is not an
aggregate inspector pass. Logs and `inspector/report.json` retain the failure.

The expanded held-response fixture established a real scope defect before repair:
`scope-before-4/` attributes the retired originating `owner_exact` brief GET and
PUT to the replacement profile, including the exact 168,062-byte payload. The
global API/profile routing behavior is pre-existing; this evidence does not prove
retention. Primitive profile and connection generations now fence before invoking
an exact loader, after each await, and immediately before brief reads/writes.
The epoch covers genuine profile, mode, base and credential changes, including
A -> B -> A; identical setters do not invalidate work. Same-scope retired-origin
copy/promote and exact original-draft revision acknowledgements remain allowed.
Settings reloads 600 ms after connection setters; App token save reloads immediately.
No additional listeners or stored credentials were introduced by the epoch.

`buffer-before-2/` proved loss of an actually buffered token on acknowledged ID
adoption. Explicit reducer adoption now preserves messages, buffered token and
reasoning state, revision and recovery identity. Subsequent ordinary unbuffered
handoff failed with React maximum update depth (`handoff-diagnostic-1/` and
`handoff-trace-before-1/`). Trace indices 18–22 show a stale config effect resetting
B back to A, followed by a stale reducer-to-panel bridge publishing the opposite
ID. The virtualizer measure amplified this feedback; it was not an ID writer.
Both mirror effects were unchanged in the base, but the candidate introduced the
imperative adoption/order path. A base behavioral failure is **not** established.
There was no render-ref-overwrite entry proving that separate assignment triggered it.

The repair keeps measure and buffer-preserving adoption. A config effect skips
when an explicit later adoption/recovery replaced its render's config identity;
setSession publishes config before committing. The panel bridge skips every
publication from a superseded reducer snapshot. `handoff-after-1/` passes the
actual ordinary ChatPage handoff and mounted actual-virtualizer regression for
pending A effects -> B adoption with zero buffer and with one token. Both record
one stale snapshot, commit/measure/publish B without post-ack A, then intentional
compression C and fresh CURRENT_STATUS. Fresh reducer commits schedule projection;
there is no observed permanent status/identity stall.

Final frozen-source correctness receipts, all under
`/tmp/spark-panel-ownership-422f1487/`:

- `stable-type.log`: TypeScript exit 0; `stable-lint.log`: zero errors/warnings.
- `stable-tests.log`: **444 tests / 77 files pass**.
- `stable-buffer-backend-aba/result.json`: **14 checks pass**, including real
  one-token buffered adoption, null-draft hero handoff without migration/repost,
  superseding same-owner forks, backend-only ABA, and mounted regressions.
- `stable-profile-aba/`, `stable-copy-backend/`, `stable-brief-boundary/`, and
  `stable-credential-aba/`: **10 checks pass each**, including ordinary unbuffered
  adoption and the named held-response boundary.

Each final result has errors=[] and failure=null, with an explicit assertion
against React maximum-depth/error-boundary console errors. Each retains one
HTTP resource console error; the receipt attributes it to the deliberately
rejected **POST /api/conversations/owner_a/messages, status 400**. This is not a
zero-console-error claim. Earlier exact-fixture failure (`behavior-2/`), incomplete
scope fixtures (`scope-before-1/`, `scope-before-2/`), RAF-polling fixture failure
(`buffer-before-1/`), actual scope/buffer failures, and failed ordinary handoff
attempts (`final-profile-aba/`, `final-copy-backend/`, diagnostic/trace) remain
preserved. The inspector aggregate exit 1/304 limitation remains unresolved.

The pre-P2 freeze of 13 source/helper/test paths is preserved in
`frozen-source-manifest.json`, `frozen-source.patch` and
`source-freeze-v1-before-refresh-p2/`; no commit or retention acceptance has been made. Original
frontend source SHA256 is
`a8a34541c17dd07c104503729c1f63c4d1b822165c31fed74417a1ccf116692c`;
candidate is
`a0c4459c5f5b05af54a260789c4da477927ec37b1a0a2a3764ce6172857e3427`.
The independently proved separate search fence is applied identically to original
and candidate (four-line hash
`512b49d27e625824934749c499bb4efe64a301048a66042e7dba85b9f22da5cd`).
Prior original search failures remain failures; this candidate claims no search repair.

At the first source-freeze checkpoint, all owned groups were closed and no heap
capture had run. The later diagnostic batch is summarized above. Correctness
checks do not establish a performance result.

The prospective matched production navigation pair requires 13 forced-GC
checkpoints 0–12, snapshots at 2 and 12, and strong object-ID census excluding
weak/ephemeron-value edges. Old-owner timeline generations must be collectible;
a lower heap slope alone is insufficient. The paired continuing-owner control
never navigates: 2,000 existing backend rows, one reuse-existing turn adding
exactly one user and one assistant row (2,002 total), 32 token updates at 80 ms
when released. Identical temporary producer gates release three tokens at each
checkpoint 0–9, final two at 10, with turn_done/history recovery settled before
11/12. Samples record actual producer/token progress, live row/turn counts,
owner/node identity and bounded registrations. A successful final-token history
GET **started after actual turn_done**, in the same server monotonic clock,
is required before both final checkpoints; earlier historyReads are context only.
This bounded one-turn control is not repeated unbounded multi-turn proof and
does not require zero heap slope. Surviving IDs can be shared live transcript
rows and are not automatically leaks or repairs.

Protocol v2 preserves the original frozen helper bytes and pins the transitive
strong-edge classifier, source transforms, backend/driver templates and generated
attempt drivers in `protocol-v2-manifest.json` (SHA256
`015955716ed4728df31c2826411ed6171bc46813748b88147afe39dd0df23b8d`).
All four production prepare-only paths and syntax/seam/regex checks pass, without
starting builds/servers/browsers. An initial outdated callback seam preparation
failure is preserved in `prepare-v2-original-control/`; the pinned adapter retains
the existing streamNavigations diagnostic and assertions. The broad `.current`
ref union is labelled **candidateRefTimeline**, untrusted for active identity,
and is never used to classify older generations. All-strong census, live counts
and retaining paths remain primary. No retention fix, package, release or full
inspector acceptance is claimed.

The subsequent independent source review found one P2 in `refreshTurnSurfaces`:
its three API reads began before the owner check and lacked scope fencing.
`refresh-before-1/` proves the candidate runtime path with real pending approval
UI/current action ID: a held tray submission response is released after backend
change, while ownerCurrent=true and scopeCurrent=false; the old owner launches
GETs to replacement `/scope-refresh-b/api/conversations/owner_a/turn-outcomes`,
`plan`, and `pending-actions`. The same-scope positive runs first and publishes
SAME_SCOPE_REFRESH after reading all three real surfaces. A second before proof,
`refresh-read-before-1/`, starts those reads in the original scope, holds their
responses across an epoch change, and then observes FOREIGN_SURFACE_SENTINEL
published once. These are candidate runtime proofs; base behavior was not run.

The app-only repair is two lines: reject non-current owner/scope before launching
reads, and include scope currency alongside the existing owner/session-ID/refresh-
generation check after all awaits. Caller error/finally behavior is unchanged;
there are no new listeners, backend Stops, replays or action-ID changes.
`refresh-p2-app-only.patch` records the exact delta from the preserved v1 freeze.

The first after attempt failed before the P2 flow at an existing forced exact-copy
click outside the viewport. Its result/screenshot are preserved without attributing
an app cause. A fixture edit command then used a wrong relative path; the shell
continued before that correction. Partial `refresh-after2-*` receipts and the
interrupted inline attempt are retained with `aborted-preparation.json`, excluded
from final corrected-fixture evidence. Detached backend 61694 was explicitly
closed. The actual correction uses normal Playwright actionability waits for the
same copy/promote targets and retains all assertions/timeouts.

Authoritative corrected `refresh-after3-tray-launch/`,
`refresh-after3-tray-reads/`, and `refresh-after3-inline-launch/` each pass **11
checks**, including the original nine ownership checks and the same-scope
positive. Both callers and the held-read publication boundary are covered:
retiredReads=[] and foreignPublished=0, errors=[], failure=null. The intentional
POST rejection's HTTP400 console entry remains attributed and preserved.
`refresh-after-type.log` passes; `refresh-after-lint.log` has zero warnings/errors;
`refresh-after-tests.log` passes **20 focused tests / four files**. The earlier
444-test full frontend receipt predates this two-line repair; it is not a new
full-suite claim.

The new freeze still owns the same 13 paths; only ChatPanel.tsx and the existing
correctness driver changed from v1. Source bytes are archived in
`source-freeze-v2-after-refresh-p2/`. `frozen-source-v2-manifest.json` SHA256 is
`88fef8effbc184aa36de578136ad49826fb185444018ccd3cfb449665cc3ec85`, with full
`frozen-source-v2.patch` and fixture-only delta separately recorded. Candidate
frontend source aggregate is now
`3a191ae41f3eab4cc67a461fe054bbd8892eeed7f3688c932daa87d9fbea840e`;
original/search-fence/lock hashes remain unchanged. Immutable protocol v2's 29
inputs were reverified. `protocol-v3-manifest.json` SHA256
`794d209d067031769fa3aa8993fb5684e01e4f5bca880fd954b9cab5a1528ae3` references
those unchanged core helpers/classifier and pins new source, candidate prepare-only
drivers and P2 receipts. Both candidate production preparation paths pass without
starting builds, servers or browsers. `refresh-final-commands-closed.json` and
`refresh-final-process-inventory.txt` record all owned groups closed, including
61694 absent. These bytes were frozen for the subsequent independent response review, which
accepted the scope guard for measurement. At that checkpoint no integration, package or retention
acceptance has occurred.
