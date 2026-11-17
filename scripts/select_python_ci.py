"""Choose the Python PR suite from the actual checkout diff.

Only paths with a maintained test boundary opt into a smaller suite. Shared,
mixed backend, or unclassified changes retain full coverage.
"""

import argparse
import subprocess
from pathlib import Path, PurePosixPath

SMOKE = (
    "tests/test_minimal_startup.py",
    "tests/test_model_tools_lazy_imports.py",
    "tests/tools/test_lazy_manifest.py",
    "tests/test_packaging_metadata.py",
    "tests/agent/test_prompt_caching.py",
    "tests/run_agent/test_caching_golden.py",
    "tests/run_agent/test_primary_runtime_restore.py",
    "tests/test_spark_state.py",
    "tests/test_web_turn_persistence.py",
    "tests/test_chat_recovery_snapshot.py",
)
CRON = (
    "tests/cron",
    "tests/test_cron_output_routes.py",
    "tests/test_palette_routes.py",
    "tests/test_model_tools.py",
    "tests/test_timezone.py",
    "tests/spark_cli/test_cron.py",
    "tests/spark_cli/test_cron_overrides.py",
    "tests/spark_cli/test_reference_cron_events.py",
    "tests/run_agent/test_exit_cleanup_interrupt.py",
    "tests/tools/test_cronjob_tools.py",
    "tests/tools/test_cron_prompt_injection.py",
    "tests/gateway/test_email.py::TestCronDelivery",
    "tests/gateway/test_sms.py::TestSmsToolset",
)

ARTIFACTS = (
    "tests/tools/test_artifact_store.py",
    "tests/tools/test_tool_result_storage.py",
    "tests/run_agent/test_agent_loop_tool_calling.py",
    "tests/run_agent/test_tool_pacing.py",
)

FILE_TOOLS = (
    "tests/tools/test_checkpoint_manager.py",
    "tests/tools/test_file_operations.py",
    "tests/tools/test_file_operations_edge_cases.py",
    "tests/tools/test_file_read_guards.py",
    "tests/tools/test_file_staleness.py",
    "tests/tools/test_file_tools.py",
    "tests/tools/test_file_tools_live.py",
    "tests/tools/test_file_write_safety.py",
    "tests/tools/test_fuzzy_match.py",
    "tests/tools/test_native_file_operations.py",
    "tests/tools/test_patch_parser.py",
    "tests/tools/test_write_deny.py",
)
AFFECTED_TESTS = {"cron": CRON, "artifacts": ARTIFACTS, "file-tools": FILE_TOOLS}


def classify_path(name: str) -> str:
    path = PurePosixPath(name)
    if name in SMOKE or name in {"README.md", "CONTRIBUTING.md"}:
        return "smoke"
    if name.startswith("docs/") and path.suffix == ".md":
        return "smoke"
    if name.startswith("src/spark_cli/web/src/") and path.suffix in {".ts", ".tsx", ".css"}:
        return "smoke"
    if name == "src/spark_cli/web/e2e/cron-outputs.mjs":
        return "smoke"
    if name.startswith(("src/cron/", "tests/cron/")) or name in {
        "src/spark_cli/cron_routes.py",
        "src/spark_cli/cron_output_routes.py",
        "src/tools/cronjob_tools.py",
        *(target for target in CRON if "::" not in target),
    }:
        return "cron"
    if name in {
        "src/tools/artifact_store.py",
        "src/tools/artifact_tool.py",
        "src/tools/tool_result_storage.py",
        *ARTIFACTS,
    }:
        return "artifacts"
    if name in {
        "src/tools/checkpoint_manager.py",
        "src/tools/file_operations.py",
        "src/tools/file_tools.py",
        "src/tools/fuzzy_match.py",
        "src/tools/patch_parser.py",
        *FILE_TOOLS,
    }:
        return "file-tools"
    return "full"


def select_scope(names: list[str]) -> str:
    scopes = {classify_path(name) for name in names}
    affected = scopes - {"smoke"}
    if not scopes or "full" in scopes or len(affected) > 1:
        return "full"
    return next(iter(affected), "smoke")


def changed_paths(base: str) -> list[str]:
    # A PR checkout is the merge commit. Only scope when its first parent is
    # the event's exact base, so stale/wrong/incomplete history falls back.
    parent = subprocess.check_output(["git", "rev-parse", "HEAD^1", "HEAD^2"], text=True).splitlines()[0]
    if parent != base:
        raise ValueError("PR checkout parent does not match its base")
    changed = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", parent, "HEAD"])
    return [path.decode("utf-8") for path in changed.split(b"\0") if path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="", help="Exact PR base SHA. Empty selects full coverage.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    scope = "full"
    if args.base:
        try:
            scope = select_scope(changed_paths(args.base))
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            print(f"Could not classify the PR diff. Running the full Python suite. {exc}")
    targets = () if scope == "full" else SMOKE + AFFECTED_TESTS.get(scope, ())
    print(f"Python coverage: {scope}")
    if targets:
        print("Selected targets:", " ".join(targets))
    with args.output.open("a", encoding="utf-8") as output:
        print(f"scope={scope}", file=output)
        print(f"targets={' '.join(targets)}", file=output)


if __name__ == "__main__":
    main()
