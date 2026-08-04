"""Public comparator entry point for SKILL-08 score artifacts."""

from __future__ import annotations

try:
    from .runner import compare_scores
except ImportError:  # pragma: no cover - direct script imports are not supported here
    from runner import compare_scores  # type: ignore[no-redef]

__all__ = ["compare_scores"]
