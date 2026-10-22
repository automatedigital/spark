# Storage/backend independent re-review

**BLOCKED** — reviewed `3a3e2005f1988c80bf870ed44c1be35f61592358` in a new detached worktree `/tmp/spark-storage-r2-review-20261022`.

## P1: case aliases split the new canvas lock identity

`src/spark_cli/canvas_routes.py:125-132`, specifically line 128, hashes `os.path.normcase(str(path.parent.resolve() / path.name))`. On macOS `normcase` leaves case unchanged. On this host's actual case-insensitive filesystem, `board.canvas.json` and `Board.canvas.json` are the **same inode**, but hash to **different lock files**. Canvas IDs explicitly allow both spellings.

A controlled two-thread probe uses the real writer, filesystem and flock. It pauses writer A immediately before the real `Path.replace`, after A has acquired its real lock and passed its expectedRevision check. Writer B addresses `Board` with the same expectedRevision. B completes successfully while A still holds its lock; after release A also succeeds and overwrites B's acknowledged save. Both returned `ok:true`; final name is `A`. This is silent lost-update/data-loss behavior introduced by the new lock namespace, not a hypothetical security scenario or a claim inferred from skipped tests.

Reproduce with active shared venv, this checkout's `src` on PYTHONPATH, and synthetic HOME/USERPROFILE/SPARK_HOME:

`python /tmp/spark-merge-review-20261022/storage-r2-case-probe.py`

**Exit 1** at the safety assertion. Exact output: `storage-r2-case-probe.log`. The probe checks actual samefile identity before performing the contention flow. It wraps only the timing of `Path.replace`, calls the real replacement, and does not replace the locks or persistence. No sleep-based success inference.

Minimum repair: derive stable lock identity according to the owning filesystem's filename equivalence rules, including not-yet-created and deleted canvases, and add a real case-insensitive alias contention regression requiring exactly one success and one 409. Preserve independent case-distinct files on case-sensitive filesystems. Review both supported macOS case modes rather than assuming OS name implies filesystem case behavior.

## Prior findings and composition

- **Resolved `155-search-only-ancestor`:** workspace_routes.py:969-975 opens selected root directly and verifies fstat identity; permission regression passes.
- **Resolved `171-utf8-collision-budget`:** workspace_routes.py:1080-1086 bounds generated names to 240 UTF-8 bytes; exclusive descriptor/handle creation composes with immutable paths.
- **Resolved `168-nonutf8-status`:** workspace_routes.py:1526-1537 returns display-only disabled rows with empty action paths; UI blocks diff/discard, ordinary exact paths retained.
- **Resolved `173-symlink-discard`:** workspace_routes.py:1428-1446,1576-1587 validates lexical path and unlinks final links; literal Git pathspecs preserve neighboring files; real symlink discard regressions pass.
- **Resolved `177-final-symlink`:** canvas_routes.py:85-122,360-361,386 reject final links and retain lexical replace/unlink; global/project final-link route regressions pass.
- **Resolved `177-project-sidecar-removal`:** canvas_routes.py:125-142 moves lock inodes outside project to profile canvas-locks; real alias/Git-removal process test passes. New case-alias identity regression remains below.
- **Resolved `182-object-numeric-export`:** session_export.py:39-42 applies whole-field redaction before type dispatch; both real SQLite publisher-byte regressions pass.

The original project-sidecar deletion flow is fixed: Git/Files can no longer remove the metadata lock through the project tree. That does not discharge the newly demonstrated case-alias identity split. Existing exact-canvas contention tests use the same spelling and therefore miss it.

Read AGENTS.md, CONTEXT.md, STRUCTURE.md, accepted ADRs, original workspace/backend reviews and the four requested repair reports. Inspected actual five repair diffs and the integrated memory, cron, permission and skill-history implementations. SQLite recovery retains the confirmed-corruption guard; cron retains stable profile-local read/modify/write locks; permission copying remains in both atomic writers and shared history save still uses the validated helper. No additional blocking source finding in those bounded paths. The Git repair retains NUL parsing and expanded untracked rows together, rejects invalid action identities, uses literal pathspecs and removes final links themselves. The upload repair retains exclusive anchored creation and both actual allocated response paths; byte trimming and ancestor permission repair are composed rather than selecting the old pathname writer.

## Checks and gates

- `targeted repaired boundaries`: exit **0**. 18 passed, 161 deselected in 5.87s
- `case-alias CAS probe`: exit **1**. Expected safety assertion fails: two same-revision writers succeed on same inode
- `git diff --check 97fb8373^ HEAD`: exit **0**. 
- `git status --short`: exit **0**. clean detached worktree

Exact targeted pytest command and structured findings are in `storage-r2.json`. Targeted pytest output is in `storage-r2-targeted.log`. These 18 tests are independent boundary verification, not a duplicate full runtime run.

- Bounded review covers the ten assigned storage/backend PRs in the combined SHA; no claim about the other ten PRs.
- Full runtime suite is lead-owned and was not duplicated. Lead-reported upload 51/11 skipped, neighbors 118/11 skipped and canvas 38 were not independently rerun wholesale.
- Native Windows containment/locking remains unexecuted here. release-contracts.yml adds native Windows/Linux suites but existence of workflow, skipped macOS cases and static typing are not native proof. Require successful exact release-candidate CI results.
- No browser acceptance, frontend build, generated web_dist, installed package, signing/notarization or publication evidence produced here; require lead release gates independently.
- Canvas repair hardens final component, not hostile canonical ancestor directory replacement; no parent descriptor is held. Generic external/File/Git writers do not honor canvas CAS locks. Stop old servers using legacy sidecar locks before adoption.
- No edits to repository source, commits, push, merge, release, external publication, agents or watchers. Only review files outside source were written; all ten scoped PRs T3-linked and final inventory watching=false.
- First probe wrapper used zsh read-only variable status and exited 1 after the Python assertion; bounded rerun corrected wrapper to probe_exit and independently confirmed Python exit 1. This setup error is not a source finding.

All prior concrete failure cases are repaired at source; this combined SHA remains blocked by STORAGE-R2-001. After that repair, require native CI and platform package/release gates before release approval.
