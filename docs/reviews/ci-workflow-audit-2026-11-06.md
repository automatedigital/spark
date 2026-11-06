# CI reliability audit — 2026-11-06

The failure volume has several causes; the workflows are not uniformly obsolete.

## Demonstrated causes

- Web run 42241269134: pinned Playwright 1.59.1 cannot provision Chromium dependencies on Ubuntu26.04. The browser job must retain ubuntu-24.04, as already corrected on SP01, rather than following ubuntu-latest.
- PR232 Python run42294448153: 12,754 tests passed; the quiet retry-output unit test timed out after successful mocked provider completion in the unrelated post-turn curator state save. Its stack ended in os.replace; this does not prove filesystem latency was the cause. Isolate the curator hook in this output-only test. Dedicated curator coverage remains unchanged.
- PR214/220/232 inspector failures: scroll1000→1410 exceeds the unchanged100px tolerance. No demonstrated production or fixture repair yet; keep blocking. Existing bounded matched runs did not reproduce the hosted failure.
- PR234's old-head pytest job128157078672 reports operation canceled, not an assertion failure. Do not count superseded cancellations as test defects.

## First patch

1. Pin browser e2e to ubuntu-24.04; preserve all browser assertions, timeouts and steps.
2. Add workflow/ref concurrency cancellation to release persistence contracts, retaining Ubuntu and Windows and fail-fast:false.
3. Trigger persistence checks for pyproject.toml dependency changes.
4. Explicitly exclude network tests in Python's offline fast selections, consistently with the repo's offline validation commands. This does not add a network-service gate; intentional external testing remains separately invoked.
5. Mock agent.curator.maybe_run_curator only in the quiet retry-output test; retain completion and output assertions.

Validation: two focused parseable_quiet_mode tests passed,250 deselected,8.75s with this checkout's absolute PYTHONPATH. Source Ruff CI ratchet passed. All five workflow YAML files parse; git diff --check passed. Actionlint is unavailable locally, so YAML parsing is not claimed as full GitHub expression validation. The test file has11 pre-existing Ruff findings under an extra test-file scan; no broad cleanup was included. No timeouts increased, assertions relaxed, checks made advisory, or automatic retry added. No full local suite repeated.

## Further work

- Add a reviewed Python CI constraints file shared across jobs; broad currently resolved ranges create drift risk, although drift did not cause the demonstrated failures above.
- Use job-level frontend change detection and stable required-check aggregation before skipping frontend lint/types/unit tests for backend-only changes. Keep browser coverage for backend changes.
- Separate overlapping backend contracts from the browser job, then remove duplication only with equivalent blocking coverage. Preserve stable required-check names.
- Diagnose inspector restoration with retained keyed geometry around chat switches, under a bounded reproduction. Avoid weakening scroll tolerance.

This PR does not retrofit25 existing feature branch heads or establish their hosted success. Shared fixes need dependency-order integration. GitHub notification preferences were not changed; failure email volume should be reduced by preventing failures, not hiding them.
