# Pete Feedback Remediation Plan

Date: 2026-06-22

Scope: address Pete's feedback that long Spark answers are hard to read, streaming
markdown currently shows raw syntax such as `##`, `###`, `**bold**`, and `-`
bullets during generation, and hyperlinks in rendered answers do not open.

Important implementation constraints:

- Keep active prompt caching stable. Any system prompt / SOUL change only affects
  newly built sessions; do not rebuild active system prompts mid-conversation.
- Only change Spark's built-in agent defaults and Web UI rendering paths, not
  user-created projects under `.spark/workspace/`.
- Preserve the previous markdown performance work: streaming must parse bounded
  committed/tail chunks rather than reparsing the full growing answer on every
  token.
- Treat the provided screenshot as the primary visual regression: assistant
  output should render headings, subheadings, bold text, and bullet lists while
  the answer is still streaming.

## Parallelization Plan

- Lane A, prompt concision, can run independently of the Web UI work.
- Lane B, streaming markdown rendering, can run in parallel with Lane A and Lane C.
- Lane C, hyperlink opening, can run in parallel with Lane A and most of Lane B,
  but final QA should use the same browser smoke run as Lane B.
- Lane D, tests and visual verification, starts after each lane has code ready.
  Unit tests can be added per lane, but browser screenshot verification should
  happen after both Lane B and Lane C land.
- Lane E, graph/docs cleanup, runs last after code changes are complete.

## Lane A - Make Default Answers More Concise

- [ ] Inspect the current system prompt assembly path before editing:
  `src/core/run_agent/prompt_cache.py`, `src/agent/prompt_builder.py`, and
  `src/spark_cli/default_soul.py`. Confirm whether the best durable default is
  the seeded `DEFAULT_SOUL_MD`, a new prompt-builder guidance block, or a small
  platform-neutral addition near existing platform hints.
- [ ] Add concise-answer guidance that asks Spark to prefer short, scannable
  answers by default, avoid repeating obvious context, and expand only when the
  user asks for depth or the task requires it. Keep the guidance specific enough
  to reduce token use but not so terse that coding, legal/financial caveats, or
  implementation reports become incomplete.
- [ ] If changing `DEFAULT_SOUL_MD`, keep `DEFAULT_AGENT_PERSONA` synchronized
  through the existing constant flow in `src/spark_cli/default_soul.py`. Do not
  edit user-owned `~/.spark/SOUL.md` files directly.
- [ ] If changing prompt assembly outside `DEFAULT_SOUL_MD`, add or update a
  focused prompt-building test under `tests/agent/test_prompt_builder.py` or
  `tests/run_agent/test_run_agent.py` that proves the new concision guidance is
  included once and does not duplicate existing memory/tool guidance.
- [ ] Check caching-sensitive expectations. If the rendered system prompt golden
  output changes, update the relevant golden test in `tests/run_agent/` in the
  same implementation commit and document that the change applies to newly
  constructed sessions only.

## Lane B - Restore Markdown While Streaming

- [ ] Reproduce the current bug in the Web UI path: in
  `src/spark_cli/web/src/components/Markdown.tsx`, `Markdown` returns plain
  `whitespace-pre-wrap` text whenever `streaming` is true. This explains the
  screenshot where headings and bold syntax appear raw during a streamed answer.
- [ ] Change `Markdown` so `streaming` no longer disables markdown parsing by
  itself. `safeMode` should still force plain text, and very large completed
  content may still use a fallback if needed, but ordinary streaming assistant
  messages must flow through `ParsedMarkdown`.
- [ ] Preserve the bounded streaming parser design already present in
  `ParsedMarkdown`: `findStableBoundary(content)` splits committed prefix from
  live tail, `parseBlocks(stablePart)` and `parseBlocks(tailPart)` are memoized,
  and only the live tail block should update each frame.
- [ ] Review `SOFT_RENDER_CAP` behavior. Decide whether the cap should apply to
  streaming content at all. If it remains, make sure long answers do not switch
  to raw markdown prematurely in the common case Pete reported.
- [ ] Ensure incomplete streaming constructs degrade gracefully:
  partial headings, partial bold spans, partial links, unclosed code fences,
  lists, blockquotes, and tables should render without throwing and should settle
  into the same output as the final non-streaming render.
- [ ] Add tests in `src/spark_cli/web/src/components/Markdown.test.ts` that lock
  the parser invariants for the screenshot shape:
  `## Heading`, `### 1. Subheading`, `**bold**`, unordered lists, and a streamed
  tail appended after a blank line.
- [ ] Add a test that characterizes the regression directly: a streaming
  assistant message with markdown should be parsed into heading/list/bold block
  data instead of being treated as raw plain text. If this requires a component
  render test, use the existing Vitest setup and keep it narrowly scoped.
- [ ] Confirm syntax highlighting remains deferred while a code block is live:
  `CodeBlock` should render plain code for `live=true` and only call
  `highlight.js` after the block is complete.
- [ ] Verify safe mode still works. When safe mode is active, markdown can remain
  plain text and animations should remain disabled.

## Lane C - Fix Hyperlink Opening

- [ ] Trace rendered links from `parseInline()` in
  `src/spark_cli/web/src/components/markdownParse.ts` through `InlineContent` in
  `src/spark_cli/web/src/components/Markdown.tsx`. Confirm both markdown links
  (`[text](https://example.com)`) and bare URLs produce `link` nodes.
- [ ] Reproduce the click failure in both browser dashboard and Tauri desktop if
  possible. Check whether the problem is missing link parsing during streaming,
  browser default navigation inside the React app, Tauri external-open behavior,
  or event handling inside a virtualized chat row.
- [ ] For normal browser dashboard links, ensure clicking opens the target in a
  new tab/window with `target="_blank"` and `rel="noreferrer"` without React
  Router intercepting it.
- [ ] For Tauri desktop links, inspect `src/spark_cli/web/src/lib/desktop.ts`
  and the Tauri bridge in `src/spark_cli/web/src-tauri/src/lib.rs`. If needed,
  route external `http://` and `https://` links through the native shell/open
  API instead of attempting in-webview navigation.
- [ ] Keep local media/file previews working. Do not break `MediaPreview`,
  `mediaFileUrl()`, image/video/audio previews, or file-link styling while
  fixing ordinary web links.
- [ ] Harden URL parsing edge cases in `parseInline()` if needed: trailing
  punctuation, parentheses, query strings, fragments, and `https://` URLs next
  to markdown punctuation should not produce broken `href` values.
- [ ] Add unit tests for `parseInline()` covering markdown links, bare URLs,
  trailing punctuation, and parentheses.
- [ ] Add a browser smoke test or manual QA note that clicks a rendered answer
  hyperlink and confirms a new page/tab or native browser open occurs.

## Lane D - Verification And Regression Coverage

- [ ] Run focused Web tests from `src/spark_cli/web`:
  `npm run test -- Markdown.test.ts` if supported by Vitest, otherwise
  `npm run test`.
- [ ] Run full Web checks from `src/spark_cli/web`: `npm run test`,
  `npm run lint`, and `npm run build`.
- [ ] Run focused Python prompt tests after Lane A:
  `source venv/bin/activate && python -m pytest tests/agent/test_prompt_builder.py tests/run_agent/test_run_agent.py -q`
  or a narrower subset if only one test file changed.
- [ ] Manually verify the screenshot scenario in the Web UI with a long answer
  containing headings, bold text, bullets, and a hyperlink. The answer should be
  readable while streaming, not only after completion.
- [ ] Manually verify a very long response still avoids render freezes. Watch for
  safe-mode activation, long-task counters, scroll jank, and syntax-highlight
  delays on large code blocks.
- [ ] Manually verify link clicks in browser dashboard and, if the desktop app is
  available, in Tauri desktop.
- [ ] Confirm no unrelated files are modified. This plan was requested as a
  narrow remediation; implementation commits should stay scoped to prompt
  guidance, markdown rendering, link handling, and tests.

## Lane E - Graph And Documentation Cleanup

- [ ] After code changes, run `graphify update .` from the repo root so
  `graphify-out/` stays current. Dirty graph files are expected, but include
  them only if this repo normally commits updated graph output.
- [ ] Update user-facing docs only if behavior or settings changed. Likely
  candidates are `docs/web-dashboard.md` and
  `src/spark_cli/web/README.md`; skip docs if the fix is purely restorative and
  existing docs already describe the intended behavior.
- [ ] Add a short implementation note to the final commit or PR description
  explaining the intended default: concise answers by default, markdown rendered
  during streaming, links open externally, and safe mode remains the fallback for
  pathological render cost.

## Suggested Agent Assignment

- [ ] Agent 1 can take Lane A only. It touches Python prompt/default-soul files
  and Python tests, and does not need to coordinate with Web UI code except for
  final verification.
- [ ] Agent 2 can take Lane B only. It touches `Markdown.tsx`,
  `markdownParse.ts` only if parser behavior needs adjustment, and
  `Markdown.test.ts`.
- [ ] Agent 3 can take Lane C only. It touches link parsing/rendering and
  desktop/browser external-open code if needed.
- [ ] Agent 4 can take Lane D after Agents 1-3 have branches or patches ready.
  This agent should run the combined checks and perform browser/Tauri QA.
- [ ] One agent should own final integration to avoid merge churn in
  `Markdown.tsx` and `Markdown.test.ts`, because Lane B and Lane C may both
  touch inline rendering.

## Acceptance Criteria

- [ ] New Spark sessions include explicit concise-answer guidance without
  duplicating existing prompt blocks or breaking prompt-cache invariants.
- [ ] While an assistant answer is streaming, headings, bold text, lists,
  blockquotes, code fences, tables, and paragraphs render as markdown whenever
  safe mode is not active.
- [ ] The raw-markdown screenshot case no longer reproduces for ordinary
  streaming answers.
- [ ] Hyperlinks in assistant answers open successfully from the browser Web UI.
- [ ] Hyperlinks in assistant answers open successfully from the macOS desktop
  app or have a documented fallback if desktop cannot be tested locally.
- [ ] Markdown render performance remains bounded for long responses; completed
  blocks do not re-render on every token, and code highlighting remains deferred
  for live code blocks.
- [ ] Focused tests cover prompt guidance, streaming markdown parsing, and link
  parsing/open behavior.
- [ ] `npm run test`, `npm run lint`, `npm run build` in
  `src/spark_cli/web`, and the relevant Python prompt tests pass before pushing
  implementation changes.
