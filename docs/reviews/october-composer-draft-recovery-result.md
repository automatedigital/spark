Implemented and committed the PR #176 P2 composer draft recovery fix.

Commit: `bf2f6a4f742f47b37b0941261cb1067e31bfb60d`
Branch: `fix/composer-draft-recovery`
Worktree: `/Users/joe/.t3/worktrees/spark/t3-89b6583e`
Base: `2695192f` via successful `git merge --ff-only 2695192`.
Lead cherry-pick: `git cherry-pick bf2f6a4f742f47b37b0941261cb1067e31bfb60d`.

The assigned checkout was already a clean isolated worktree on the requested branch. Only that checkout was changed. The lead integration checkout `/tmp/spark-review-release-20261022` and the dirty root checkout were never edited.

Behavior and ownership:

- Before recall overwrites input, the original text is synchronously flushed into a namespaced recovery entry in the existing draftStore. It reuses the existing storage version, revision/conflict detection, subscriptions, flushing and failure handling. No second persistence engine or draft schema was added.
- Recovery is keyed by the captured, confirmed draft scope (backend/profile/project/thread). PromptBar receives that exact key plus the panel owner token; browse/menu/caret state retires when this identity changes. There are no cleanup writes and no cleanup invocation of a replacement thread setter. Existing application backend/profile remount/reload semantics remain in place.
- The current recalled or edited text stays in the normal draft; the original remains accessible through Restore draft after navigation, unmount, reload, rejected send, and accepted send. Navigation does not automatically replace the visible edited recall. Restore draft swaps current and recovery text, preserving edited recall too. Down at the end of active history uses the same swap.
- Starting another browse when an existing recovery would be replaced requires explicit confirmation; cancellation leaves both texts intact. Moving from an edited recall to another history entry also requires explicit replacement confirmation. This is one recovery slot per draft identity, not an unbounded edit archive.
- A failed recovery write/conflict/corrupt recovery blocks the destructive history operation and shows an error. The current input stays unchanged. Existing unresolved cross-tab recovery conflicts fail closed; no new conflict resolution UI or multiwindow transaction guarantee is claimed.
- Accepted send acknowledges only the normal submitted draft revision. It does not consume the recovery entry. Rejected sends keep the current text and recovery. Attachments/context remain on the existing draft path and are not recalled or swapped.
- Stash restore retires active history/caret state. Down cannot overwrite the newly restored stash before or after navigation. An open stash modal guards keyboard history. Existing no-auto-send, caret, selection, modifier, IME, slash-menu, history picker focus and Escape behavior are retained.

Scoped files (five):

- `src/spark_cli/web/src/components/chat/PromptBar.tsx`
- `src/spark_cli/web/src/components/ChatPanel.tsx` (two props only)
- `src/spark_cli/web/src/lib/composerPromptHistory.ts`
- `src/spark_cli/web/src/lib/composerPromptRecovery.test.ts`
- `src/spark_cli/web/e2e/composer-history.mjs`

Exact before/after evidence:

- Pinned integration-base reproduction: `/tmp/composer-draft-recovery-baseline-exact/result.json` and `failure.png`. The three modified implementation files were temporarily supplied from `git show 2695192:<path>` in this isolated worktree, then restored byte for byte in a finally block. Nonempty A -> recall -> B with its own nonempty draft -> A returned `Recall Alpha latest` with `recoveryActions: 0`; assertion `original unsent draft recovery must survive A/B/A` failed, exit 1 as expected, with no page errors or sends.
- Final real Chromium/real ChatPanel/SQLite/replay-backend acceptance: `/tmp/composer-draft-recovery-final/result.json`, exit 0, no page errors. It proves nonempty A/B/A, original and edited recall recovery through full reload, edited-recall Down swapping, canceled replacement, history picker focus/filter/Escape, IME/slash/caret/selection/modifier guards, failed explicit send + reload, accepted explicit send + reload, recall -> stash restore -> Down -> B/A -> Down, modal keyboard guard, and quota-failed recall + reload.
- The final browser run made exactly two explicit message requests, both to `f01_a` with `edited recall survives reload` and no context items: one fixture rejection and one accepted fake stream. There were no automatic sends. Real providers were not called; the send boundary is intercepted and the configured model endpoint is loopback port 1.
- Screenshots: `/tmp/composer-draft-recovery-final/history-picker.png`, `original-recovered-2-0.png`, `original-recovered-3-1.png`, `original-recovered-3-2.png`, and `final.png`. The original recovery screenshot after successful send/reload was visually inspected (same verified source as the final run).
- Existing independent stash browser flow: `/tmp/composer-draft-recovery-stash.log`, exit 0, all six flows pass and `providerCalls: 0` (reload/cancel, exact replacement, empty restore, quota save/delete, deletion across reload, compact viewport/Escape).

Executed checks, all terminal successful unless explicitly identified as the expected baseline failure:

- `npm ci --ignore-scripts`: exit 0, nested lockfile unchanged, 399 packages, audit reported zero vulnerabilities.
- `npx vitest run src/lib/composerPromptHistory.test.ts src/lib/composerPromptRecovery.test.ts src/lib/draftStore.test.ts src/lib/promptStashStore.test.ts src/hooks/useChatComposerActions.test.ts src/lib/chatComposerController.test.ts src/components/chat/composerContracts.test.ts`: exit 0, 7 files / 45 tests. Includes real draft-store reload, exact submission revision acknowledgement, backend/profile/thread isolation, empty originals, edited text swapping, quota failure, conflict and malformed recovery boundaries. Log: `/tmp/composer-draft-recovery-focused.log`; final repeat also passed.
- `npx tsc -b --pretty false`: exit 0. `/tmp/composer-draft-recovery-types-final.log`; final repeat passed.
- `npm run lint`: exit 0, full frontend ESLint. `/tmp/composer-draft-recovery-lint-final.log`; final repeat passed after final e2e edits.
- `PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python COMPOSER_HISTORY_OUTPUT=/tmp/composer-draft-recovery-final node e2e/composer-history.mjs`: exit 0. `/tmp/composer-draft-recovery-final.log`.
- `PYTHON=/Users/joe/Developer/github/spark/.venv/bin/python STASH_OUTPUT=/tmp/composer-draft-recovery-stash node e2e/prompt-stash.mjs`: exit 0.
- `git diff --check`: exit 0. Post-commit `git status --short`: empty.

All checks used the activated `/Users/joe/Developer/github/spark/.venv`. Python backend fixtures imported this checkout's `src` via PYTHONPATH and synthesized HOME/USERPROFILE/SPARK_HOME before import. Focused unit/type/lint acceptance also used `/tmp/spark-composer-recovery-check-home` and its isolated profile. Actual Node was verified as `v22.22.1`, executable `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`.

The first expanded browser probes caught test-harness mistakes (reopening an already-open picker after canceled confirmation; a hardcoded caret one character before the end). Those were corrected; the final evidence above is a complete terminal pass. The exact pinned-base probe independently confirms the source regression.

Constraints and unexecuted checks: no full Python/frontend suite, Python Ruff/mypy, hosted required CI/longthread gate, production bundle generation, packaging, installed macOS/Windows acceptance, publication or release was executed. There is no claim that the other 19 PRs or release gates are complete. No packages/lockfiles, generated bundles/manifests, PLAN or workflow files were modified. No delegation, PR creation, push, PR merge, release or watcher was used. PR #176 was registered with this T3 thread as required; no GitHub comment or PR mutation was made.
