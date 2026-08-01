"""Provider-independent response normalization primitives."""

from __future__ import annotations

import re
from typing import Any


def normalize_visible_text(value: Any) -> str:
    """Collapse transport-only whitespace for streamed-content comparison."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()
