"""Dependency-free availability checks for schema-only tool entries."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path


def _env_any(names: list[str]) -> bool:
    return any(bool(os.getenv(name)) for name in names)


def _env_all(names: list[str]) -> bool:
    return all(bool(os.getenv(name)) for name in names)


def evaluate_check(spec: str, requires_env: list[str]) -> bool:
    """Evaluate a generated manifest check without importing a feature SDK."""
    if spec == "always":
        return True
    if spec == "env_any":
        return _env_any(requires_env)
    if spec == "env_all":
        return _env_all(requires_env)
    if spec == "homeassistant":
        return bool(os.getenv("HASS_TOKEN"))
    if spec == "cron":
        return _env_any(["SPARK_INTERACTIVE", "SPARK_GATEWAY_SESSION", "SPARK_EXEC_ASK"])
    if spec == "browser_active":
        module = sys.modules.get("tools.browser_tool")
        return bool(module and getattr(module, "_browser_session_active", False))
    if spec == "browser_requirements":
        return bool(os.getenv("CAMOFOX_URL") or shutil.which("agent-browser"))
    if spec == "image_generation":
        return bool(os.getenv("FAL_KEY")) and importlib.util.find_spec("fal_client") is not None
    if spec == "tts":
        candidates = ("edge_tts", "elevenlabs", "openai")
        return any(importlib.util.find_spec(name) is not None for name in candidates)
    if spec == "google_oauth":
        spark_home = Path(os.getenv("SPARK_HOME", Path.home() / ".spark"))
        return any((spark_home / name).exists() for name in ("google_token.json", "google_token.pickle"))
    if spec == "gmail":
        return evaluate_check("google_oauth", []) or _env_all(["GMAIL_IMAP_EMAIL", "GMAIL_IMAP_PASSWORD"])
    if spec == "gateway":
        if os.getenv("SPARK_SESSION_PLATFORM", "local") != "local":
            return True
        spark_home = Path(os.getenv("SPARK_HOME", Path.home() / ".spark"))
        return (spark_home / "gateway.pid").exists()
    if spec.startswith("module:"):
        return importlib.util.find_spec(spec.partition(":")[2]) is not None
    return True
