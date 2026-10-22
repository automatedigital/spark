# Git filename boundaries implementation

Commit: `2adc85159964c27e119acba8b10ff068f7fcac0b`
Branch: `fix/git-filename-boundaries`
Worktree: `/tmp/spark-git-filename-boundaries-20261022` (macOS canonical `/private/tmp/...`).
Base: `a9bb2a7b`, installed with the requested `git merge --ff-only a9bb2a7` before implementation.
Ready for lead cherry-pick. No PR, push, main merge, release, provider calls, or delegation.

## Scope and contract

Only four files changed: `src/spark_cli/workspace_routes.py` (Git section only), `tests/spark_cli/test_workspace_git.py`, `src/spark_cli/web/src/components/workspace/WorkspaceChangesPanel.tsx`, and its new `.test.ts`.
No upload helpers or imports changed. Read AGENTS/CONTEXT/STRUCTURE and all three accepted ADRs; used review probes and baseline comparison.

Normal rows retain their exact existing path and shape, including Unicode, tabs, CR/LF, quotes, literal arrows, spaces and backslashes. NUL parsing and `--untracked-files=all` remain intact.
For non-UTF-8 Git names, status now returns a disabled row with `path: ""`, a display-only `display_path` containing the original byte repr, and `unsupported_reason: "Filename is not valid UTF-8; use Git directly"`. No escaped or replacement filename is actionable. The panel displays the reason, prevents expansion/diff and disables discard. Distinct React keys include both actual path and display label. Backend discard rejects empty, surrogate-containing, NUL, absolute, traversal and directory paths. Empty diff remains the existing whole-worktree read-only API.

All pathspec-taking per-file Git diff/list/checkout calls use global `--literal-pathspecs`. `--no-index` continues to receive filenames directly. Discard validates lexical file paths without resolving the final symlink: untracked links (including dangling, directory and external targets) are unlinked; tracked links are restored at the link itself. Symlink directory traversal is rejected, while linked project roots remain supported. Status no longer reads symlink target contents for line counting. Invalid bytes in read-only diff/branch output are escaped for JSON display, never reused as path arguments.

## Validation

- Python checkout source: `.venv` activated (temporary symlink to existing dev/web environment), explicit `PYTHONPATH=$PWD/src`, isolated HOME and SPARK_HOME, no provider.
- Final focused real-Git/HTTP + file-operation neighbors: **67 passed** (`git-filename-tests.log`). Covers raw non-UTF-8 tree entry with valid and escaped-label neighbors; exact normal path round trips; literal wildcard/magic filenames with unrelated sentinel; tracked/untracked symlink targets, dangling links, directory links, external targets; linked project roots; normal diff/discard.
- Broader workspace/upload neighbors: **96 passed, 7 failed, 11 skipped** before the final linked-root test addition (`git-filename-neighbors.log`). All seven failures belong to existing upload identity contracts. Exact committed base workspace module replay reproduces **7 failed, 30 passed, 11 skipped** for the upload pair (`git-filename-upload-baseline.log`, harness `baseline_git_filename.py`). Base lacks `_save_new_upload`, repeats filenames, and omits expected response paths. Upload fixes intentionally left to their owner.
- Focused Ruff: pass. Full CI selected Ruff families: pass (`git-filename-ci-ruff.log`). Full `ruff check src/`: 298 findings, **exact base also 298** (source extracted from `git archive a9bb2a7`, logs `git-filename-ruff.log` and `git-filename-ruff-baseline.log`). No changed-file Ruff failures.
- `mypy src/agent/ src/spark_cli/`: **137 source files clean** (`git-filename-mypy.log`).
- Node verified: **v22.22.1**, `/Users/joe/.nvm/versions/node/v22.22.1/bin/node`. Homebrew `node@22` actually points to Node 25, so it was not used for acceptance. Nested lockfile `npm ci` completed with Node 22.
- Frontend lint and `tsc -b`: pass (`git-filename-web-lint.log`, `git-filename-tsc.log`).
- Full Vitest: **87 files, 550 tests passed**, including two row-contract tests (`git-filename-all-vitest.log`).
- Local React/Vite browser fixture: **PASS** (`git-filename-browser.log`, screenshot `git-filename-ui.png`). Unsupported row click produced zero API calls and discard was disabled. Valid Unicode/tab neighbor expanded its diff and confirmed discard; both calls retained exact filename. Collaborative preview snapshot twice failed with `Preview automation snapshot timed out after 15000ms.`; switched to local Playwright/Chrome after those failures. Fixture stubs Git APIs only; no provider used. Temporary fixture removed, Vite stopped and preview closed.
- `git diff --check`: pass. No generated production bundle or package claim.

The non-UTF-8 regression uses a real Git index/tree entry, rather than requiring macOS to create an unsupported byte filename on disk. Direct actions on such entries intentionally remain unsupported in the UI; use Git directly.
