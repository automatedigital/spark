#!/usr/bin/env python3
"""Permission gates for sensitive agent browser actions (PLAN.md 2b).

Before the agent submits a payment, sends a message, or logs into a NEW domain,
we pause and require explicit user confirmation rather than auto-proceeding.

The classifier is heuristic — it inspects the target URL, the page snapshot
text near the action, and the click/submit semantics — and returns a
``Classification`` describing whether the pending action is sensitive and why.
The browser tool turns a sensitive classification into a ``needs_confirmation``
tool result the user must approve.

Policy is configurable via ``security.browser_confirm_sensitive`` in config.yaml
(default ``True``).  Approvals are remembered per (session, category, domain)
for the lifetime of the process so the agent isn't re-prompted for the same
action after the user grants it.

This module is import-safe and has no heavy dependencies.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Sensitivity categories.
CATEGORY_PAYMENT = "payment"
CATEGORY_MESSAGE = "message"
CATEGORY_LOGIN_NEW_DOMAIN = "login_new_domain"

_PAYMENT_PATTERNS = re.compile(
    r"\b(pay\s*now|place\s+order|complete\s+(?:order|purchase)|checkout|"
    r"buy\s+now|confirm\s+(?:payment|purchase|order)|submit\s+payment|"
    r"add\s+card|card\s+number|cvv|cvc|billing|donate|subscribe\s+now|"
    r"authori[sz]e\s+payment)\b",
    re.IGNORECASE,
)
_MESSAGE_PATTERNS = re.compile(
    r"\b(send\s+(?:message|email|invite|dm)|post\s+(?:tweet|reply|comment)|"
    r"publish|tweet|submit\s+(?:message|comment|post|review)|reply\s+all|"
    r"send\s+now)\b",
    re.IGNORECASE,
)
_LOGIN_PATTERNS = re.compile(
    r"\b(log\s*in|sign\s*in|sign\s*on|continue\s+with|authenticate|"
    r"password|two.?factor)\b",
    re.IGNORECASE,
)


@dataclass
class Classification:
    """Result of classifying a pending browser action."""

    sensitive: bool
    category: str | None = None
    reason: str = ""
    domain: str | None = None
    details: dict = field(default_factory=dict)


# Per-process state: domains the agent has already logged into (seen), and
# approvals the user has granted.  Keyed loosely so tests can reset them.
_lock = threading.Lock()
_known_login_domains: set[str] = set()
_granted: set[tuple[str, str, str]] = set()  # (session_slug, category, domain)


def reset_state() -> None:
    """Clear in-process gate state (test helper)."""
    with _lock:
        _known_login_domains.clear()
        _granted.clear()


def _session_slug() -> str:
    name = (os.environ.get("SPARK_BROWSER_PREVIEW_SESSION") or "").strip()
    return name.removeprefix("spark-preview-") if name else "default"


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
    except Exception:  # noqa: BLE001
        return None
    host = host.lower()
    # Collapse to registrable-ish domain (last two labels) so www.x.com and
    # accounts.x.com count as the same login domain.
    parts = [p for p in host.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host or None


def gate_enabled() -> bool:
    """Return whether sensitive-action confirmation is enabled (config flag).

    Reads ``security.browser_confirm_sensitive`` (default True).  Fails safe to
    True when config is unreadable.
    """
    try:
        from spark_cli.config import read_raw_config

        cfg = read_raw_config()
        security = cfg.get("security", {})
        if isinstance(security, dict) and "browser_confirm_sensitive" in security:
            return bool(security["browser_confirm_sensitive"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not read security.browser_confirm_sensitive: %s", exc)
    return True


def note_login_domain(url: str | None) -> None:
    """Record a domain as already-known (the agent has navigated/logged in)."""
    dom = _domain(url)
    if dom:
        with _lock:
            _known_login_domains.add(dom)


def is_known_login_domain(url: str | None) -> bool:
    dom = _domain(url)
    if not dom:
        return True  # can't classify → don't treat as new
    with _lock:
        return dom in _known_login_domains


def classify_action(
    action: str,
    *,
    url: str | None = None,
    context_text: str = "",
    is_new_domain: bool | None = None,
) -> Classification:
    """Classify a pending browser action as sensitive or not.

    Args:
        action: ``click``, ``type``, ``press``, ``navigate``…
        url: Current page URL (for domain reasoning).
        context_text: Snapshot/element text near the action (button label,
                      nearby form fields), used for keyword heuristics.
        is_new_domain: Override for login-domain novelty; when ``None`` we
                       consult the per-process seen-domains set.
    """
    dom = _domain(url)
    text = context_text or ""

    # Payments — highest priority.
    if _PAYMENT_PATTERNS.search(text):
        return Classification(
            sensitive=True,
            category=CATEGORY_PAYMENT,
            reason="Action appears to submit a payment or place an order.",
            domain=dom,
            details={"matched": "payment_keywords"},
        )

    # Messages / posts.
    if _MESSAGE_PATTERNS.search(text):
        return Classification(
            sensitive=True,
            category=CATEGORY_MESSAGE,
            reason="Action appears to send a message or publish content.",
            domain=dom,
            details={"matched": "message_keywords"},
        )

    # Login into a NEW domain.
    if _LOGIN_PATTERNS.search(text):
        novel = is_new_domain if is_new_domain is not None else (
            dom is not None and not is_known_login_domain(url)
        )
        if novel:
            return Classification(
                sensitive=True,
                category=CATEGORY_LOGIN_NEW_DOMAIN,
                reason=f"Action appears to log into a new domain ({dom}).",
                domain=dom,
                details={"matched": "login_keywords"},
            )

    return Classification(sensitive=False, domain=dom)


def is_granted(classification: Classification) -> bool:
    """Return True if the user already approved this category+domain this run."""
    if not classification.sensitive:
        return True
    key = (_session_slug(), classification.category or "", classification.domain or "")
    with _lock:
        return key in _granted


def grant(classification: Classification) -> None:
    """Remember the user's approval for this category+domain for the process."""
    if not classification.sensitive:
        return
    key = (_session_slug(), classification.category or "", classification.domain or "")
    with _lock:
        _granted.add(key)
