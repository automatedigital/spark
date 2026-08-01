"""Tool result persistence -- preserves large outputs instead of truncating.

Defense against context-window overflow operates at three levels:

1. **Per-tool output cap** (inside each tool): Tools like search_files
   pre-truncate their own output before returning. This is the first line
   of defense and the only one the tool author controls.

2. **Per-result persistence** (maybe_persist_tool_result): After a tool
   returns, if its output exceeds the tool's registered threshold
   (registry.get_max_result_size), the full output is written INTO THE
   SANDBOX temp dir (for example /tmp/spark-results/{tool_use_id}.txt on
   standard Linux, or $TMPDIR/spark-results/{tool_use_id}.txt on Termux)
   via env.execute(). The in-context content is replaced with a preview +
   file path reference. The model can read_file to access the full output
   on any backend.

3. **Per-turn aggregate budget** (enforce_turn_budget): After all tool
   results in a single assistant turn are collected, the largest
   non-persisted results are spilled until both the hard character ceiling
   and recoverable token soft limit are met. This catches cases where many
   medium-sized or token-dense results combine to overflow context.
"""

import hashlib
import logging
import os
import re
import shlex
import uuid
from collections.abc import Sequence

from tools.budget_config import (
    DEFAULT_BUDGET,
    DEFAULT_PREVIEW_SIZE_CHARS,
    PINNED_THRESHOLDS,
    BudgetConfig,
)

logger = logging.getLogger(__name__)
PERSISTED_OUTPUT_TAG = "<persisted-output>"
PERSISTED_OUTPUT_CLOSING_TAG = "</persisted-output>"
STORAGE_DIR = "/tmp/spark-results"
HEREDOC_MARKER = "SPARK_PERSIST_EOF"
_BUDGET_TOOL_NAME = "__budget_enforcement__"
_CONTENT_HASH_RE = re.compile(r"^Content hash: (sha256:[0-9a-f]{64})$", re.MULTILINE)
_FILE_PATH_RE = re.compile(r"^Full output saved to: (.+)$", re.MULTILINE)


def estimate_tool_result_tokens(content: str) -> int:
    """Return a conservative tokenizer-independent token estimate.

    Three UTF-8 bytes per token intentionally errs below the common
    four-characters-per-token English heuristic, while counting CJK text at
    roughly one token per character.  Provider-reported usage remains the
    authority; this estimate only decides whether a recoverable spill is useful.
    """
    if not content:
        return 0
    return (len(content.encode("utf-8", errors="surrogatepass")) + 2) // 3


def _content_hash(content: str) -> str:
    encoded = content.encode("utf-8", errors="surrogatepass")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _resolve_storage_dir(env) -> str:
    """Return the best temp-backed storage dir for this environment."""
    if env is not None:
        get_temp_dir = getattr(env, "get_temp_dir", None)
        if callable(get_temp_dir):
            try:
                temp_dir = get_temp_dir()
            except Exception as exc:
                logger.debug("Could not resolve env temp dir: %s", exc)
            else:
                if temp_dir:
                    temp_dir = temp_dir.rstrip("/") or "/"
                    return f"{temp_dir}/spark-results"
    return STORAGE_DIR


def generate_preview(content: str, max_chars: int = DEFAULT_PREVIEW_SIZE_CHARS) -> tuple[str, bool]:
    """Truncate at last newline within max_chars. Returns (preview, has_more)."""
    if len(content) <= max_chars:
        return content, False
    truncated = content[:max_chars]
    last_nl = truncated.rfind("\n")
    if last_nl > max_chars // 2:
        truncated = truncated[:last_nl + 1]
    return truncated, True


def _heredoc_marker(content: str) -> str:
    """Return a heredoc delimiter that doesn't collide with content."""
    if HEREDOC_MARKER not in content:
        return HEREDOC_MARKER
    return f"SPARK_PERSIST_{uuid.uuid4().hex[:8]}"


def _write_to_sandbox(content: str, remote_path: str, env) -> bool:
    """Write content into the sandbox via env.execute(). Returns True on success."""
    marker = _heredoc_marker(content)
    storage_dir = os.path.dirname(remote_path)
    cmd = (
        f"mkdir -p {shlex.quote(storage_dir)} && cat > {shlex.quote(remote_path)} << '{marker}'\n"
        f"{content}\n"
        f"{marker}"
    )
    result = env.execute(cmd, timeout=30)
    return result.get("returncode", 1) == 0


def _build_persisted_message(
    preview: str,
    has_more: bool,
    original_size: int,
    file_path: str,
    *,
    content_hash: str | None = None,
    origin_tool: str | None = None,
) -> str:
    """Build the <persisted-output> replacement block."""
    size_kb = original_size / 1024
    if size_kb >= 1024:
        size_str = f"{size_kb / 1024:.1f} MB"
    else:
        size_str = f"{size_kb:.1f} KB"

    msg = f"{PERSISTED_OUTPUT_TAG}\n"
    msg += f"This tool result was too large ({original_size:,} characters, {size_str}).\n"
    msg += f"Full output saved to: {file_path}\n"
    if content_hash:
        msg += f"Content hash: {content_hash}\n"
    if origin_tool:
        msg += f"Origin tool: {origin_tool}\n"
    msg += "Use the read_file tool with offset and limit to access specific sections of this output.\n\n"
    msg += f"Preview (first {len(preview)} chars):\n"
    msg += preview
    if has_more:
        msg += "\n..."
    msg += f"\n{PERSISTED_OUTPUT_CLOSING_TAG}"
    return msg


def maybe_persist_tool_result(
    content: str,
    tool_name: str,
    tool_use_id: str,
    env=None,
    config: BudgetConfig = DEFAULT_BUDGET,
    threshold: int | float | None = None,
    truncate_on_failure: bool = False,
    force_persist: bool = False,
) -> str:
    """Layer 2: persist oversized result into the sandbox, return preview + path.

    Writes via env.execute() so the file is accessible from any backend
    (local, Docker, SSH, Modal, Daytona). Falls back to inline truncation
    if write fails or no env is available.

    Args:
        content: Raw tool result string.
        tool_name: Name of the tool (used for threshold lookup).
        tool_use_id: Unique ID for this tool call (used as filename).
        env: The active BaseEnvironment instance, or None.
        config: BudgetConfig controlling thresholds and preview size.
        threshold: Explicit override; takes precedence over config resolution.
        truncate_on_failure: Allow a failed forced spill to truncate inline.
            Hard per-result character overflows retain their historical
            truncation behavior regardless of this setting.
        force_persist: Spill this result even when its per-result limits are
            not exceeded, used by aggregate budget enforcement.

    Returns:
        Original content if small, or <persisted-output> replacement.
    """
    effective_threshold = threshold if threshold is not None else config.resolve_threshold(tool_name)

    if effective_threshold == float("inf"):
        return content

    exceeds_char_limit = len(content) > effective_threshold
    exceeds_token_limit = (
        threshold is None
        and env is not None
        and config.result_budget_tokens is not None
        and estimate_tool_result_tokens(content) > config.result_budget_tokens
    )
    if not exceeds_char_limit and not exceeds_token_limit and not force_persist:
        return content

    storage_dir = _resolve_storage_dir(env)
    remote_path = f"{storage_dir}/{tool_use_id}.txt"
    preview, has_more = generate_preview(content, max_chars=config.preview_size)

    if env is not None:
        try:
            if _write_to_sandbox(content, remote_path, env):
                logger.info(
                    "Persisted large tool result: %s (%s, %d chars -> %s)",
                    tool_name, tool_use_id, len(content), remote_path,
                )
                return _build_persisted_message(
                    preview,
                    has_more,
                    len(content),
                    remote_path,
                    content_hash=_content_hash(content),
                    origin_tool=tool_name,
                )
        except Exception as exc:
            logger.warning("Sandbox write failed for %s: %s", tool_use_id, exc)

    if not exceeds_char_limit and not truncate_on_failure:
        logger.info(
            "Keeping token-heavy tool result inline after storage failure: %s (%d chars)",
            tool_name,
            len(content),
        )
        return content

    logger.info(
        "Inline-truncating large tool result: %s (%d chars, no sandbox write)",
        tool_name, len(content),
    )
    return (
        f"{preview}\n\n"
        f"[Truncated: tool response was {len(content):,} chars. "
        f"Full output could not be saved to sandbox.]"
    )


def enforce_turn_budget(
    tool_messages: list[dict],
    env=None,
    config: BudgetConfig = DEFAULT_BUDGET,
    tool_names: Sequence[str] | None = None,
) -> list[dict]:
    """Layer 3: enforce aggregate budget across all tool results in a turn.

    If total chars exceed budget, persist the largest non-persisted results
    first (via sandbox write) until under budget. Already-persisted results
    are skipped.

    ``tool_names``, when supplied, must align one-to-one with ``tool_messages``.
    A mismatch returns the messages unchanged rather than risking persistence
    of a pinned paging tool under the wrong name.

    Mutates the list in-place and returns it.
    """
    if tool_names is not None and len(tool_names) != len(tool_messages):
        logger.warning(
            "Skipping turn budget: %d tool messages but %d tool names",
            len(tool_messages),
            len(tool_names),
        )
        return tool_messages

    candidates = []
    total_size = 0
    total_tokens = 0
    artifacts_by_hash: dict[str, str] = {}
    for i, msg in enumerate(tool_messages):
        content = msg.get("content", "")
        size = len(content)
        total_size += size
        total_tokens += estimate_tool_result_tokens(content)
        tool_name = (
            tool_names[i]
            if tool_names is not None
            else (msg.get("name") or msg.get("tool_name"))
        )
        if tool_name in PINNED_THRESHOLDS:
            continue
        if PERSISTED_OUTPUT_TAG in content:
            hash_match = _CONTENT_HASH_RE.search(content)
            path_match = _FILE_PATH_RE.search(content)
            if hash_match and path_match:
                content_hash = hash_match.group(1)
                file_path = path_match.group(1)
                prior_path = artifacts_by_hash.get(content_hash)
                if prior_path:
                    replacement = (
                        f"{PERSISTED_OUTPUT_TAG}\n"
                        f"Unchanged duplicate of artifact {content_hash}.\n"
                        f"Full output saved to: {prior_path}\n"
                        f"{PERSISTED_OUTPUT_CLOSING_TAG}"
                    )
                    total_size += len(replacement) - size
                    total_tokens += (
                        estimate_tool_result_tokens(replacement)
                        - estimate_tool_result_tokens(content)
                    )
                    msg["content"] = replacement
                else:
                    artifacts_by_hash[content_hash] = file_path
        else:
            candidates.append((i, size))

    def _over_budget() -> bool:
        exceeds_chars = total_size > config.turn_budget
        exceeds_tokens = (
            env is not None
            and config.turn_budget_tokens is not None
            and total_tokens > config.turn_budget_tokens
        )
        return exceeds_chars or exceeds_tokens

    if not _over_budget():
        return tool_messages

    candidates.sort(key=lambda x: x[1], reverse=True)

    for idx, size in candidates:
        if not _over_budget():
            break
        msg = tool_messages[idx]
        content = msg["content"]
        tool_use_id = msg.get("tool_call_id", f"budget_{idx}")
        content_hash = _content_hash(content)

        prior_path = artifacts_by_hash.get(content_hash)
        if prior_path:
            replacement = (
                f"{PERSISTED_OUTPUT_TAG}\n"
                f"Unchanged duplicate of artifact {content_hash}.\n"
                f"Full output saved to: {prior_path}\n"
                f"{PERSISTED_OUTPUT_CLOSING_TAG}"
            )
        else:
            replacement = maybe_persist_tool_result(
                content=content,
                tool_name=_BUDGET_TOOL_NAME,
                tool_use_id=tool_use_id,
                env=env,
                config=config,
                force_persist=True,
                truncate_on_failure=total_size > config.turn_budget,
            )

        if replacement != content:
            total_size -= size
            total_size += len(replacement)
            total_tokens -= estimate_tool_result_tokens(content)
            total_tokens += estimate_tool_result_tokens(replacement)
            tool_messages[idx]["content"] = replacement
            path_match = _FILE_PATH_RE.search(replacement)
            if path_match:
                artifacts_by_hash[content_hash] = path_match.group(1)
            logger.info(
                "Budget enforcement: persisted tool result %s (%d chars)",
                tool_use_id, size,
            )

    return tool_messages
