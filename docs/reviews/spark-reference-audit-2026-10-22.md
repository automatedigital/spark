# Spark research audit — 2026-10-22

## Scope and source pins

Research only. No source edits, issue creation, PR creation, delegation, provider calls, live profile access, or live Spark server. Read AGENTS.md, CONTEXT.md, STRUCTURE.md and accepted ADRs 0001, 0012, 0013. Spark HEAD verified as `64af0d26976714b747dd4f1cc5b495c47c7f7567` on the supplied checkout. The unrelated dirty move remains exactly ` D HANDOFF_100826.md` / `?? docs/HANDOFF_100826.md`.

Upstream default-branch HEADs independently resolved through GitHub API and verified against shallow clones:

- T3 Code: `f054d1b8018721bd997d99cbb918a7b17bf098a4`, commit date 2026-10-22, `feat(web,mobile): messages from other agents fold into one-line rows (#23135)`.
- Hermes: `8237c7f8ec179c88857f24a174509d985af704b7`, commit date 2026-10-22, `fix(config): config set/get still recognise terminal.singularity_image`.
- Clones: `/tmp/spark-audit-t3-20261022`, `/tmp/spark-audit-hermes-20261022`. Historical PLAN.md pins were not treated as current upstream.
- Both repositories use MIT licenses. Retain applicable notices for copied substantial code; recommendations below favor adapting behavior to Spark's existing modules.

All Spark path:line references refer to the verified HEAD. Source-confirmed gaps mean absent from the inspected complete user-facing path, not a claim that no similarly named primitive exists anywhere. Existing asynchronous delegation, child inspection, durable sidebar organization, draft recovery, project creation, search, notification policy, skills restore, and worktree isolation are deliberately excluded from the feature count.

## Confirmation and validation performed

- `source .venv/bin/activate && PYTHONPATH=src python /tmp/spark-audit-repro-20261022.py` — exit 0. Imports occurred after assigning a temporary SPARK_HOME. Temporary Git repositories had synthetic commits; no provider was contacted. Reproduced seven backend conditions when counting the additional export check below.
- `node /tmp/spark-audit-frontend-repro-20261022.mjs` — exit 0, Node v22.22.1. Executes callback bodies extracted from current production source with controlled API promises and mock setters. This establishes the three frontend defects' response-order mechanisms; it is not a mounted React or browser acceptance run. A first harness run lacked its slug binding; corrected the temporary harness and reran successfully.
- Separate isolated log-route check — exit 0; `lines=0` returned all three fixture lines, `lines=-1` returned two. Kept as a reserve finding rather than inflating the requested ten.
- Separate synthetic export check — exit 0; a fake `sk-` token was removed from ordinary content but remained in nested tool arguments. No actual credential was used or printed.
- No full test suite, manual browser flow, package build, installed app check or performance benchmark was run. Each packet below states the meaningful implementation acceptance still required.

## Ten confirmed issue-fix candidates

These are proposed PR packets, not created PRs. Priority is local to this audit. Shared-file ownership makes some packets sequential even when their behavior is independent.

### B01 — Redact nested tool arguments in shareable session exports (P1)

- Evidence: `src/spark_cli/session_export.py:26` copies each message and only redacts string `content`/`reasoning`; nested `tool_calls` survives unchanged. `src/core/spark_state.py:3269` exports actual get_messages records, including decoded tool_calls (`:2786`). `/export --publish` uses this helper at `src/core/cli/session_ops_mixin.py:25`.
- Trigger/impact: an assistant tool call includes a credential in JSON arguments; the advertised redacted export, potentially publicly published by explicit user action, retains it. Synthetic reproduction: content token removed=True; same token survives tool arguments=True.
- Narrow fix: recursively copy/redact string values in the session export structure, including serialized JSON argument strings, while preserving arrays, nulls, numbers and IDs. Keep raw DB export/backup semantics separate. Review export redaction's opt-out policy explicitly; do not silently rely on log redaction settings for a shareable artifact.
- Owned paths: `src/spark_cli/session_export.py`, focused export tests. Touch `src/agent/redact.py` only if a force-redaction API is necessary, with its own tests.
- Meaningful validation: nested Chat Completions and Responses-style tool payloads, reasoning and tool output; input object remains unchanged; fake secrets absent in JSON bytes; ordinary text/IDs intact. Mock the publisher and verify it receives only the sanitized file, without contacting GitHub.
- Dependencies: prerequisite for F03 Markdown export. Independent of Git/frontend fixes.

### B02 — Prevent project/global uploads following out-of-root destination symlinks (P1)

- Evidence: `src/spark_cli/workspace_routes.py:866` validates the destination directory but constructs `dest_dir / filename` at `:882` and writes through it at `:885`. Global uploads repeat this at `:894-906`. `_safe_path` at `:253` already supplies the containment policy used by ordinary file writes.
- Trigger/impact: an existing upload filename is a symlink to a file outside the project; upload follows it and overwrites that target. Reproduced with a temporary outside file: original became `overwritten`.
- Narrow fix: validate the final file target against the owning root for both upload APIs; reject external symlinks. Prefer a bounded atomic/no-follow write strategy that does not reopen a checked path unsafely. Continue allowing intentional project-root links to local folders; the project root itself is the boundary.
- Owned paths: upload handlers/helpers in `workspace_routes.py`, focused upload tests.
- Meaningful validation: normal upload, nested directory, in-root/external/broken symlinks, both APIs, rejected writes leave outside bytes unchanged; multipart API response is actionable. Include platform-appropriate symlink tests.
- Dependencies: serializes with B03/B04/B05 in the same Python module; no schema changes.

### B03 — Parse Git filenames losslessly (P2)

- Evidence: `workspace_routes.py:1214` parses newline/tab numstat output; `:1228` parses human-quoted porcelain and strips quotes at `:1236`. Git quoting is not decoded.
- Trigger/impact: create `café.txt` under normal Git quotePath settings. API returned path `caf\\303\\251.txt`, adds=null/dels=null. That path cannot open the real file. Tabs, newlines and literal ` -> ` filenames/renames create further parsing ambiguity.
- Narrow fix: use NUL-delimited machine output for status and numstat; correctly consume rename/copy records. Keep original path characters and represent old/new paths deliberately, rather than splitting display text. Do not globally change users' Git configuration.
- Owned paths: Git status parsing/helpers in `workspace_routes.py`, real temporary-repository tests.
- Meaningful validation: Unicode, spaces, quotes, tabs/newlines, literal arrow, rename and binary files; API paths resolve to exact files and add/delete counts match Git. Open the returned Unicode path in Changes/Files browser fixture.
- Dependencies: B04/B05 share source module; F05 benefits from this first.

### B04 — Show staged initial files before the first commit (P2)

- Evidence: `workspace_routes.py:1262` runs `git diff HEAD`; on empty output it falls back only to `ls-files --others`. With an unborn HEAD and a staged file, both paths yield no displayed diff. Status numstat at `:1214` has the same HEAD assumption.
- Trigger/impact: `git init`, write/add `new.txt`, inspect Changes before first commit. Reproduced diff is `''` despite staged content.
- Narrow fix: detect unborn HEAD, compare index/working tree against the empty tree as appropriate, preserve staged plus unstaged content, and surface genuine Git errors. Do not synthesize a parent commit in the user's repository.
- Owned paths: Git diff/status helpers in `workspace_routes.py`, temporary Git tests.
- Meaningful validation: unborn tracked text/binary, untracked files, first commit then modifications, invalid repository errors; browser fixture shows initial staged content.
- Dependencies: integrate after B03's parser changes; otherwise behavior independent.

### B05 — Make Revert work for newly staged files (P2)

- Evidence: `workspace_routes.py:1286` identifies a path as tracked using ls-files, then always checks it out from HEAD at `:1296`. A staged addition exists in the index but not HEAD.
- Trigger/impact: commit a base, `git add new.txt`, press Revert. Reproduced HTTPException 500: pathspec did not match files known to Git. The UI promises to discard all uncommitted changes but cannot do so.
- Narrow fix: distinguish HEAD-tracked paths from index-only additions; remove the staged addition and its working copy when the explicit discard is confirmed, without affecting neighboring files. Handle unborn repositories too. Preserve current confirmation wording/semantics unless changed deliberately.
- Owned paths: revert helper/route in `workspace_routes.py`, temporary Git tests.
- Meaningful validation: staged addition, ordinary modified/deleted file, staged+unstaged modifications, unborn branch, unrelated dirty/staged files unchanged. Browser test confirms discard then refresh.
- Dependencies: B04 provides shared unborn-HEAD predicate; serial source ownership with B02-B04.

### B06 — Keep artifact scans within their project roots (P2)

- Evidence: `src/spark_cli/artifacts_routes.py:116` follows directory symlinks and file stat at `:123`; `:126` checks lexical relative paths only. `_collect_artifacts` at `:157` intentionally sees symlinked project roots too, so root-link support must remain.
- Trigger/impact: project contains a symlink to an external directory or an ancestor. Reproduction listed `outside-directory/outside.txt` and repeated it deeper through a cycle. Unrelated metadata consumes artifact budget; external .url/.webloc files can also have targets read. This does not establish arbitrary raw-file download: that endpoint has its own containment check.
- Narrow fix: canonicalize the project root; reject entries resolving outside it and track visited directories to break cycles. Permit the top-level linked project root itself. Decide/document whether internal aliases are deduplicated.
- Owned paths: `artifacts_routes.py`, focused artifact scan tests.
- Meaningful validation: normal files, external file/directory links, ancestor cycle, broken links, internal link and intentionally linked project root. Verify bounded scan and no external metadata/URL target in response.
- Dependencies: independent module; shares containment expectations with B02 but needs no shared migration/helper.

### B07 — Fence late Changes-panel status responses (P2)

- Evidence: `WorkspaceChangesPanel.tsx:142-153` calls setStatus after every response with no owner/request-generation check. The parent right panel at `pages/ChatPage.tsx:1222` is not keyed per project; `:838` mounts this component with mutable slug.
- Trigger/impact: A status request starts; switch to B; B resolves then A resolves. Extracted callback reproduction leaves status `{project:'a'}` while the active slug is B. The action row uses current slug with stale paths; a subsequent revert can target a same-named B file.
- Narrow fix: request generation plus slug/owner fence on success/error/finally; clear obsolete status/requestedPath on slug change, and invalidate pending timers. Do not rely exclusively on remounting to fix same-project out-of-order refreshes.
- Owned paths: `web/src/components/workspace/WorkspaceChangesPanel.tsx`, focused tests.
- Meaningful validation: mounted component deferred A/B and same-project reverse-order refresh; old rejection cannot clear B loading state; stale rows disappear before any destructive action. Browser flow switches projects while status is delayed.
- Dependencies: B08 shares this component; integrate B07 first, then B08.

### B08 — Invalidate cached file diffs after refresh/edit (P2)

- Evidence: `WorkspaceChangesPanel.tsx:48-61` caches diff for the row lifetime and fetches only when diff===null. Rows keyed only by file.path at `:232` retain state across status refreshes. Reload changes status but supplies no diff revision.
- Trigger/impact: open diff v1, close it, edit file, refresh status, reopen. Extracted toggle reproduction returned `version1`, calls=1 after underlying source became version2. Error strings are cached the same way and cannot be retried by reopening.
- Narrow fix: pass a refresh revision/owner identity into rows; invalidate/refetch on that revision and prevent late previous diff responses from winning. Keep expanded row behavior stable and allow explicit retry on failure.
- Owned paths: same component plus tests, or extracted small diff hook.
- Meaningful validation: open/edit/refresh sees v2; unchanged line counts still invalidate; failure then retry; same filename in different project; old request cannot overwrite latest. Real browser fixture should modify the underlying temp repo.
- Dependencies: B07 first; F05 adds row controls afterward.

### B09 — Stop terminal runs acknowledged after their UI owner retires (P2)

- Evidence: `WorkspaceTerminalPanel.tsx:117-118` returns immediately if cancelled after a start response; cleanup at `:173` only stops an already-recorded run ID. A pending request has no ID available during cleanup.
- Trigger/impact: start shell, navigate/unmount before POST acknowledgement. Server starts a PTY; late result is discarded, no stop request is sent. Extracted connect reproduction: stopped=[], adopted=null for returned `orphan`. Repeated reconnect also clears run ownership at `:113` before adopting another; keep generation ownership explicit.
- Narrow fix: generation-bound start ownership; on a late acknowledgement stop exactly the newly returned owned run, without touching the replacement. Fence stream handlers and repeated connect responses. Define reconnect separately from restart so it cannot silently abandon a running PTY.
- Owned paths: `web/src/components/workspace/WorkspaceTerminalPanel.tsx`, lifecycle tests. Backend changes only if explicit reconnect/reattach is selected.
- Meaningful validation: deferred start -> unmount -> late response stops old ID once; mount replacement survives; out-of-order restart responses; stream failure reconnect never silently duplicates shell. Browser with temporary project, process fixture verifies cleanup.
- Dependencies: F04 project script execution and F06 terminal selection should follow this ownership fix.

### B10 — Reject zero-duration recurring schedules (P2)

- Evidence: `src/cron/jobs.py:98-116` accepts numeric zero; `:142-150` creates interval minutes=0. `compute_next_run` at `:318` adds that interval, producing now/past rather than a future run.
- Trigger/impact: create `every 0m`, `every 0h`, or `every 0d`. Reproduced schedule `{kind:'interval',minutes:0}` and immediate next_run_at. Each scheduler tick can treat it as due, causing repeated unintended execution/cost.
- Narrow fix: reject duration <1 minute in the shared duration/schedule boundary and validate structured interval updates too. Preserve intended immediate one-shot trigger behavior. Invalid existing stored records should be paused/reported rather than executed repeatedly.
- Owned paths: `src/cron/jobs.py`, cron validation tests; route mapping only if needed for consistent 400.
- Meaningful validation: zero forms fail with actionable error through create/update; positive intervals compute strictly future times; legacy malformed record is not dispatched. Freeze time and mock dispatch; no provider calls.
- Dependencies: F02 advanced cron fields can integrate afterward; no new persistence schema.

### Reserve B11 — Bound log line counts

`logs_routes.py:24,61,71` allows zero/negative lines and Python negative-zero slicing returns all scanned matches. Isolated route call with three matching fixture lines returned all three for 0 and two for -1. Use Query bounds (1..500) or explicit documented zero behavior and test filtered/unfiltered cases. Independent low-priority alternative if a main candidate is not chosen; not part of the ten above.

## Fourteen absent feature candidates; ten ranked choices

Ranking favors a complete, small user path, useful payoff, and existing Spark primitives. Each upstream URL is commit-pinned. F01-F10 are the recommended ten feature PRs; F11-F14 are reserves. They are not ten claims of architectural parity.

### F01 (rank 1) — Recall sent prompts with composer history

- Upstream: [T3 composerPromptHistory.ts:125-145](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/composerPromptHistory.ts#L125), entries, stepping and safe recall.
- Spark gap: `web/src/components/chat/PromptBar.tsx:726` only routes submit/menu/Escape; `ChatPanel.tsx:154` restores the current draft, not selectable sent prompts.
- User path/trigger: at an empty composer press Up or use History, choose a previous user prompt, edit and send; Down restores the unsent draft. No automatic resend.
- Owned paths: new `lib/composerPromptHistory.ts`, `PromptBar.tsx`, narrow ChatPanel history prop, tests. History comes from loaded user messages; explicit UI indicates loaded scope rather than claiming whole-thread recall.
- Validation: multiline/caret/menu key guards, duplicate prompt IDs, edited recalled draft, never recall tool/system context, switching thread while browsing, browser recall+send using replay backend. No migration.
- Dependencies/overlap: serialize shared composer integration with F07 and F06; helper work otherwise independent.

### F02 (rank 2) — Per-job model/provider and skills in Schedule

- Upstream: [Hermes web_server_cron.py:244](https://github.com/nousresearch/hermes-agent/blob/8237c7f8ec179c88857f24a174509d985af704b7/hermes_cli/web_server_cron.py#L244), model/provider/skills passed through dashboard create.
- Spark gap: `cron/jobs.py:390` and `cron/scheduler.py:483,610` already support these fields, but `cron_routes.py:21` only exposes prompt/schedule/name/deliver on create; `web/src/lib/api_cron.ts:12`, `apiTypes.ts:406` and `pages/CronPage.tsx:122` omit advanced fields.
- User path: open Advanced in create/edit, choose existing resolved provider/model and ordered installed skills, save; job card displays overrides; clearing restores profile default.
- Owned paths: `cron_routes.py`, `web/src/lib/api_cron.ts`, CronJob type, `pages/CronPage.tsx`, tests. Add only model/provider/skills for this PR; defer executable scripts and custom URLs to keep scope bounded.
- Validation: round-trip create/edit/clear; existing jobs remain default; fake scheduler asserts selected fields reach runtime resolution and skill prompt building. Browser select/save/reopen. Never hardcode provider names or call them.
- Dependencies: B10 first recommended. Shared cron UI/routes with reserve F14; integrate separately.

### F03 (rank 3) — Human-readable redacted Markdown session export

- Upstream: [Hermes session_export_md.py:127](https://github.com/nousresearch/hermes-agent/blob/8237c7f8ec179c88857f24a174509d985af704b7/hermes_cli/session_export_md.py#L127), renderer, plus nested redaction at :169.
- Spark gap: `session_export.py:74-95` always writes .json; `/export` dispatch is `core/cli/session_ops_mixin.py:25`, command definition `spark_cli/commands.py:104`. JSON export exists and is not a new feature.
- User path: `/export --format markdown` writes a local readable .md with roles/timestamps and folded/plain tool sections; default remains JSON. Include CLI help and useful success/error output. No automatic publishing.
- Owned paths: new small renderer `spark_cli/session_export_markdown.py`, existing export helper/CLI handler/help and tests.
- Validation: synthetic multi-role/tool messages, structured content, Unicode, fenced code containing backticks, compression lineage as represented by existing export, redaction in final bytes; format errors. No provider/Gist call.
- Dependencies: B01 mandatory first; no DB migration. Runtime cache is untouched.

### F04 (rank 4) — Run package.json project scripts from the terminal

- Upstream: [T3 ProjectScriptsControl.tsx](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/ProjectScriptsControl.tsx), [projectScripts.ts:21](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/projectScripts.ts#L21).
- Spark gap: `WorkspaceTerminalPanel.tsx:108` launches a plain shell; `ChatPage.tsx:826` mounts it without script controls. Existing backend `workspace_routes.py:1397` accepts command-based terminal runs but does not provide a script chooser.
- Narrow user path: read current project's package.json scripts, show Run menu, explicitly select one, display live stdout/exit state in existing terminal/run surface, allow Stop. No lifecycle auto-run, arbitrary saved-script editor or DB-backed catalog.
- Owned paths: new small project-script listing route/module and tests, `WorkspaceTerminalPanel.tsx`, `api_workspace.ts`, run-menu component. Use existing run API with server-validated script names and detected package manager, no string interpolation of unchecked names.
- Validation: npm/pnpm/yarn lockfile selection, missing/invalid scripts, exact cwd, selected script output and stop, failed command, project switch; run harmless temporary fixture script only.
- Dependencies: B09; serialize terminal component with F06. This is deliberately a small subset of T3's richer project scripts.

### F05 (rank 5) — Open a changed file directly in Files

- Upstream: [T3 diffFileActions.ts:82](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/diffFileActions.ts#L82), owned file navigation from diff.
- Spark gap: `WorkspaceChangesPanel.tsx:84-112` rows only expand/revert; `ChatPage.tsx:794` already has SimpleFileViewer and FileTreePane. No row action opens the current changed file in that surface.
- User path: click Open file on a change, Files tab shows that exact project file; deleted files show an explanatory unavailable state and keep diff accessible. Add Copy path only if needed for small coherent affordance.
- Owned paths: ChangesPanel, narrowly typed right-panel callback in ChatPage, tests; reuse existing file APIs.
- Validation: project owner preserved, nested/Unicode paths, deleted/binary files, keyboard activation, no accidental revert/expand bubbling; real temporary Git browser fixture.
- Dependencies: B03, B07, B08 first. No new backend/schema.

### F06 (rank 6) — Attach selected terminal output as one-turn context

- Upstream: [T3 terminalContext.ts:7](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/lib/terminalContext.ts#L7), [ComposerPendingTerminalContexts.tsx](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/ComposerPendingTerminalContexts.tsx).
- Spark gap: `WorkspaceTerminalPanel.tsx:198` only copies selection to clipboard; `web/src/lib/context.ts:7` already supports excerpts/tool_output with scope/content/label, but no terminal capture button connects it to chat.
- User path: select terminal error, Attach to chat, see labeled removable context chip with project/run provenance, send once through existing context submission. Capture immutable text at click time, with size cap.
- Owned paths: terminal panel, new small capture helper, narrow ChatPage/ChatPanel handoff using existing ContextItem and ContextTray. Avoid adding another context schema merely to label terminal text.
- Validation: CRLF/ANSI handling, empty/oversized selection, stale project event rejected, byte content reaches only intended prompt, draft recovery does not fabricate lost selection, browser select+attach+send fixture.
- Dependencies: B09; shared terminal/composer integration with F04/F01/F07. Cache-safe user-message injection only.

### F07 (rank 7) — Save and restore a bounded text prompt stash

- Upstream: [T3 promptStashStore.ts:11-34](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/promptStashStore.ts#L11), persistence and quota behavior at :112,176.
- Spark gap: `ChatPanel.tsx:154` and `lib/draftStore.ts:15` store one current scoped draft; there is no list of explicitly saved reusable prompts or stash/restore chooser.
- User path: Save prompt, browse bounded saved text prompts, restore into editable draft after handling nonempty-draft replacement, delete saved item. Initial PR is text-only and explicitly says attachments/context are not captured.
- Owned paths: new `lib/promptStashStore.ts`, small chooser, ComposerMoreMenu/PromptBar integration, tests. Backend/profile-scoped storage key; no cross-profile leakage or migration.
- Validation: limits, storage denied/quota failure, versioned corrupt input, no silent draft replacement, cross-profile/backend scope, reload and restore browser test. Never label unsaved storage as persisted.
- Dependencies: F01 integration first recommended; no dependence on runtime tool manifests.

### F08 (rank 8) — Render safe Mermaid chat code blocks

- Upstream: [T3 MarkdownMermaidCodeBlock.tsx:11](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/MarkdownMermaidCodeBlock.tsx#L11), [MermaidDiagram.tsx](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/MermaidDiagram.tsx).
- Spark gap: `markdownParse.ts:83-93` emits all fences as code; `Markdown.tsx:31-55` registers syntax languages, with no Mermaid diagram component in chat.
- User path: assistant's completed mermaid fence shows diagram with Source toggle/copy and readable error fallback. Lazy-load renderer; keep unfinished streaming code as code and honor safeMode/large-content fallback.
- Owned paths: new chat diagram component/helper, `Markdown.tsx`, focused tests; one designated writer changes nested package.json/package-lock.json if dependency needed.
- Validation: completed/partial/invalid diagrams, theme switch, unmount cancellation, malicious links/HTML directives blocked by strict renderer configuration, large-diagram cap, browser rendered SVG vs source. No arbitrary HTML enablement.
- Dependencies: renderer owner must coordinate F09/F10/F11. No runtime migration or manifest regeneration.

### F09 (rank 9) — GitHub-style Markdown callouts

- Upstream: [T3 ChatMarkdown.tsx:975](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/ChatMarkdown.tsx#L975), backed by markdownGithubAlerts.test.tsx.
- Spark gap: `markdownParse.ts:19,124-132` models generic blockquotes; there is no NOTE/TIP/IMPORTANT/WARNING/CAUTION presentation.
- User path: a response starting `> [!WARNING]` becomes an accessible labeled callout; ordinary blockquotes stay ordinary.
- Owned paths: markdown parser/render component and tests. Use a small explicit block variant or safe quote recognizer rather than a wholesale Markdown engine replacement.
- Validation: all five types, unknown marker fallback, multiline/stream-split/nested content, literal marker in code fence, theme contrast and accessible label; browser fixture.
- Dependencies: F10 same parser files; single writer/integrate serially. No dependencies or migrations.

### F10 (rank 10) — Safe collapsible details in chat Markdown

- Upstream: [T3 MarkdownDetails.tsx:14](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/MarkdownDetails.tsx#L14), [ChatMarkdown.tsx:1481](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/ChatMarkdown.tsx#L1481).
- Spark gap: `markdownParse.ts:14-20` has no details node; raw detail/summary tags are currently plain text, while long agent responses often benefit from hidden supporting explanation.
- User path: assistant emits a supported details/summary block; user expands with keyboard or pointer, content remains copyable and discoverable. Support an intentionally narrow tag grammar, not arbitrary HTML attributes/events.
- Owned paths: parser, small Details block renderer, Markdown switch and tests.
- Validation: open/default closed, missing summary/closing tag, streaming partial, nested fences, escaped tags, malicious attributes never applied; expansion does not re-render the entire transcript, browser find/reveal if supported.
- Dependencies: integrate after F09 through one parser writer. Avoid widening raw HTML rendering globally.

### F11 (reserve) — LaTeX inline/block math rendering

- Upstream: [T3 MarkdownMath.tsx:12](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/chat/MarkdownMath.tsx#L12).
- Gap: `markdownParse.ts:23-30` inline variants contain no math. User path is copyable source plus rendered equations, respecting code fences and literal currency.
- Owned paths: parser/Markdown, lazy math component, nested lockfile only if needed. Validation: currency, escaped delimiters, malformed/streaming equations, no HTML injection, overflow/accessibility. Overlaps F08-F10; choose later if math is more useful than details.

### F12 (reserve) — Notification sounds with a user-controlled preview

- Upstream: [T3 threadNotifications.ts:89-111](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/threadNotifications.ts#L89), [NotificationSettings.tsx:15](https://github.com/pingdotgg/t3code/blob/f054d1b8018721bd997d99cbb918a7b17bf098a4/apps/web/src/components/settings/NotificationSettings.tsx#L15).
- Gap: `lib/notificationPolicy.ts:2-10` has class toggles, quiet hours and project mute, but no sound setting; NotificationBell.tsx:70 invokes nativeNotify only. Sound is additive; notifications themselves already exist.
- User path: opt into sound per input/completion class and test sound after gesture. Centralize dedupe and reuse quiet/project rules; never audio per token. Owned paths: notificationPolicy, small sound helper/assets and existing settings UI. Validate autoplay denial, concurrent completions, cooldown, preference off, quiet hours, project mute and desktop/web behavior. Independent of migrations; no need to copy upstream MP3 assets.

### F13 (reserve) — Read-only skill change history

- Upstream: [Hermes skill_ledger.py:298](https://github.com/nousresearch/hermes-agent/blob/8237c7f8ec179c88857f24a174509d985af704b7/tools/skill_ledger.py#L298), append-only mutation evidence; snapshots at :158.
- Gap: `tools/skill_manager_tool.py:364,588` keeps immediate backups, `SkillsToolsPage.tsx:391` restores an archived skill; neither is a browsable version history. PLAN.md already treats expanded history as follow-on scope.
- Small useful slice: bounded local before/after content history for dashboard edits only, exposed in a History drawer; state the coverage. Do not promise rollback, package completeness or coverage of external editors/agent mutations.
- Owned paths: new small skill-history helper/file store, dashboard save seam and SkillsToolsPage drawer/tests. Validate atomic bounded append, two saves, concurrent save, external-editor gap label, profile isolation, no timestamp-as-ownership assumption. More shared skill ownership than top ten; defer full ledger/rollback and shared migrations.

### F14 (reserve) — Browse saved scheduled-job output

- Upstream: [Hermes web_routers/cron.py:351](https://github.com/nousresearch/hermes-agent/blob/8237c7f8ec179c88857f24a174509d985af704b7/hermes_cli/web_routers/cron.py#L351), output-backed history.
- Gap: `cron/jobs.py:759` already saves per-job timestamped Markdown; `cron_routes.py:31-126` and CronPage have no output-list/read UI. The stored outputs exist; surfacing them is the feature.
- User path: job card -> Outputs -> newest saved document -> read/copy. Label this saved output history, not authoritative per-attempt execution/delivery history; old files lack such evidence.
- Owned paths: cron routes or separate output route module, API client/types, CronPage drawer. Validate canonical job ID, exact safe filename, no traversal/symlink escape, size/paging, missing/pruned outputs, profile isolation, browser read. No migration or provider call. Overlaps F02 cron UI; integrate after it.

## Delivery grouping and ownership

The request for independent work is best met by feature areas, not ten simultaneous editors of shared files:

1. Export: B01 then F03. One writer owns export sanitation/format helper seam.
2. Workspace Git/upload: B02, B03, B04, B05 integrate sequentially in workspace_routes.py. Tests may use separate fixtures but route source has one writer. Do not add DB migrations.
3. Changes UI: B07 then B08 then F05; B03 before filename acceptance. One row/status owner.
4. Terminal: B09 then F04 then F06. One terminal component owner. No ambient command execution or setup auto-run.
5. Composer: F01 then F07; coordinate F06's narrow context handoff with that owner. New helper/components can be implemented independently but shared prop integration is serial.
6. Markdown: F09 then F10; F08 rendering can be prepared separately but merge with a single Markdown/parser writer. One lockfile writer. Keep streaming, safeMode and large-response fallback tests.
7. Cron: B10 then F02; reserve F14 afterward. One create/edit API/type writer.
8. Artifacts: B06 is independent of the above.

No selected feature requires a SessionDB numbered migration, tool manifest update, new provider adapter, execution-graph rewrite, or production-bundle rewrite during development. Regenerate the tracked production bundle once from verified integrated source at the existing web release gate; do not give every PR a concurrent bundle writer. If release policy requires individual artifacts, serialize that generation explicitly.

Recommended implementation gates: focused regressions per packet, Ruff for changed Python plus required `ruff check src/`, appropriate non-integration pytest with `-n 0` for shared state, frontend lint/tests/build under verified Node 22, and the specifically listed temporary-profile browser flows. Runtime/caching/lazy startup goldens are necessary if an implementation expands into those boundaries; these proposed narrow features deliberately avoid changing prompt assembly, toolsets and manifest semantics. Record browser evidence and unresolved platform/build checks separately; none are marked complete by this research.

## Non-selected scope

Do not turn this into a new orchestration engine, provider parity project, mobile port, broad raw HTML renderer, shared DB migration program, or wholesale import of upstream code. Snooze was considered but excluded from this small batch: it needs durable wake/attention semantics and new metadata, while Spark settlement is already implemented. PR monitoring/webhooks/secret-request tooling are also larger end-to-end contracts and are not justified by a UI-only button.

Current upstream is pinned at inspection time; neither repository is assumed to remain at these commits. This report confirms source behavior and bounded reproductions, not production incidents or browser/package readiness.
