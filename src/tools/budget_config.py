"""Configurable budget constants for tool result persistence.

Overridable at the RL environment level via SparkAgentEnvConfig fields.
Per-tool resolution: pinned > config overrides > registry > default.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Tools whose thresholds must never be overridden.
# read_file=inf prevents infinite persist->read->persist loops.
PINNED_THRESHOLDS: dict[str, float] = {
    "read_file": float("inf"),
    "artifact_read": float("inf"),
}

# Defaults matching the current hardcoded values in tool_result_storage.py.
# Kept here as the single source of truth; tool_result_storage.py imports these.
DEFAULT_RESULT_SIZE_CHARS: int = 100_000
DEFAULT_TURN_BUDGET_CHARS: int = 200_000
DEFAULT_PREVIEW_SIZE_CHARS: int = 1_500
# Conservative, tokenizer-independent soft limits.  These only trigger a
# spill when durable result storage is available; the character limits above
# remain the hard fallback ceilings.
DEFAULT_RESULT_BUDGET_TOKENS: int = 12_000
DEFAULT_TURN_BUDGET_TOKENS: int = 24_000


@dataclass(frozen=True)
class BudgetConfig:
    """Immutable budget constants for the 3-layer tool result persistence system.

    Layer 2 (per-result): resolve_threshold(tool_name) -> threshold in chars.
    Layer 3 (per-turn):   turn_budget -> aggregate char budget across all tool
                          results in a single assistant turn.
    Token soft limits:   result_budget_tokens / turn_budget_tokens -> lower
                          estimated-token limits used when results can be
                          persisted without losing content.
    Preview:              preview_size -> inline snippet size after persistence.
    """

    default_result_size: int = DEFAULT_RESULT_SIZE_CHARS
    turn_budget: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    # Keep tool_overrides as the fourth field for positional compatibility.
    tool_overrides: dict[str, int] = field(default_factory=dict)
    result_budget_tokens: int | None = DEFAULT_RESULT_BUDGET_TOKENS
    turn_budget_tokens: int | None = DEFAULT_TURN_BUDGET_TOKENS
    token_counter: Callable[[str], int] | None = field(default=None, compare=False, repr=False)

    @classmethod
    def for_request(
        cls,
        *,
        remaining_context_tokens: int | None,
        task_phase: str = "work",
        result_kind: str = "text",
        provider_count_tokens=None,
    ) -> "BudgetConfig":
        """Derive conservative result shares from the current request budget.

        Provider tokenizers can tighten the budget at enforcement time; the
        stored values remain hard upper bounds for estimator-only paths.
        """
        if not remaining_context_tokens or remaining_context_tokens <= 0:
            return cls()
        phase_share = {
            "planning": 0.12,
            "work": 0.20,
            "verification": 0.16,
            "final": 0.08,
        }.get(task_phase, 0.16)
        kind_share = {
            "search": 0.75,
            "terminal": 0.85,
            "structured": 0.65,
            "text": 1.0,
        }.get(result_kind, 1.0)
        turn_tokens = max(2_000, min(DEFAULT_TURN_BUDGET_TOKENS, int(remaining_context_tokens * phase_share * kind_share)))
        result_tokens = max(1_000, min(DEFAULT_RESULT_BUDGET_TOKENS, turn_tokens // 2))
        return cls(
            result_budget_tokens=result_tokens,
            turn_budget_tokens=turn_tokens,
            token_counter=provider_count_tokens,
        )

    def count_tokens(self, content: str) -> int:
        """Use a provider counter when available, else the safe UTF-8 estimate."""
        if self.token_counter is not None:
            try:
                count = int(self.token_counter(content))
                if count >= 0:
                    return count
            except Exception:
                logger.debug("Ignoring error in count_tokens()", exc_info=True)
        encoded = content.encode("utf-8", errors="surrogatepass")
        return (len(encoded) + 2) // 3

    def resolve_threshold(self, tool_name: str) -> int | float:
        """Resolve the persistence threshold for a tool.

        Priority: pinned -> tool_overrides -> registry per-tool -> default.
        """
        if tool_name in PINNED_THRESHOLDS:
            return PINNED_THRESHOLDS[tool_name]
        if tool_name in self.tool_overrides:
            return self.tool_overrides[tool_name]
        from tools.registry import registry
        return registry.get_max_result_size(tool_name, default=self.default_result_size)


# Default config preserves the historical character ceilings and adds lower,
# recoverable token soft limits.
DEFAULT_BUDGET = BudgetConfig()
