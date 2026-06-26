"""
Multi-provider authentication system for Spark Agent.

Supports OAuth device code flows (OpenAI Codex, Qwen) and
traditional API key providers (OpenRouter, custom endpoints). Auth state
is persisted in ~/.spark/auth.json with cross-process file locking.

Architecture:
- ProviderConfig registry defines known OAuth providers
- Auth store (auth.json) holds per-provider credential state
- resolve_provider() picks the active provider via priority chain
- resolve_*_runtime_credentials() handles token refresh and key minting
- logout_command() is the CLI entry point for clearing auth
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shlex
import shutil
import stat
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from core.spark_constants import OPENROUTER_BASE_URL
from spark_cli.config import get_config_path, get_spark_home, read_raw_config

logger = logging.getLogger(__name__)

try:
    import fcntl
except Exception:
    fcntl = None
try:
    import msvcrt
except Exception:
    msvcrt = None

# =============================================================================
# Constants
# =============================================================================

AUTH_STORE_VERSION = 1
AUTH_LOCK_TIMEOUT_SECONDS = 15.0

DEFAULT_AGENT_KEY_MIN_TTL_SECONDS = 30 * 60  # 30 minutes
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120  # refresh 2 min before expiry
DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS = 1  # poll at most every 1s
DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_QWEN_BASE_URL = "https://portal.qwen.ai/v1"
DEFAULT_GITHUB_MODELS_BASE_URL = "https://api.githubcopilot.com"
DEFAULT_COPILOT_ACP_BASE_URL = "acp://copilot"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
QWEN_OAUTH_CLIENT_ID = "f0304373b74a44d2b584a3fb70ca9e56"
QWEN_OAUTH_TOKEN_URL = "https://chat.qwen.ai/api/v1/oauth2/token"
QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
_DEPRECATED_PROVIDERS = {"nous", "nous-research"}

# =============================================================================
# Multi-model setup UI (SMART / FAST slot for prompts)
# =============================================================================

_MODEL_ROUTING_SLOT_SELECTION: ContextVar[str | None] = ContextVar(
    "_model_routing_slot_selection", default=None
)


def get_model_routing_slot_selection() -> str | None:
    """During multi-model setup, which slot is being configured: ``smart`` or ``fast``."""
    return _MODEL_ROUTING_SLOT_SELECTION.get()


@contextmanager
def model_routing_slot_selection_context(slot: str | None):
    """Scope SMART/FAST labels on provider and model prompts."""
    if not slot:
        yield
        return
    token = _MODEL_ROUTING_SLOT_SELECTION.set(slot)
    try:
        yield
    finally:
        _MODEL_ROUTING_SLOT_SELECTION.reset(token)


# =============================================================================
# Provider Registry
# =============================================================================


@dataclass
class ProviderConfig:
    """Describes a known inference provider."""

    id: str
    name: str
    auth_type: str  # "oauth_device_code", "oauth_external", or "api_key"
    portal_base_url: str = ""
    inference_base_url: str = ""
    client_id: str = ""
    scope: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    # For API-key providers: env vars to check (in priority order)
    api_key_env_vars: tuple = ()
    # Optional env var for base URL override
    base_url_env_var: str = ""


PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "openai-codex": ProviderConfig(
        id="openai-codex",
        name="OpenAI Codex",
        auth_type="oauth_external",
        inference_base_url=DEFAULT_CODEX_BASE_URL,
    ),
    "qwen-oauth": ProviderConfig(
        id="qwen-oauth",
        name="Qwen OAuth",
        auth_type="oauth_external",
        inference_base_url=DEFAULT_QWEN_BASE_URL,
    ),
    "copilot": ProviderConfig(
        id="copilot",
        name="GitHub Copilot",
        auth_type="api_key",
        inference_base_url=DEFAULT_GITHUB_MODELS_BASE_URL,
        api_key_env_vars=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
        base_url_env_var="COPILOT_API_BASE_URL",
    ),
    "copilot-acp": ProviderConfig(
        id="copilot-acp",
        name="GitHub Copilot ACP",
        auth_type="external_process",
        inference_base_url=DEFAULT_COPILOT_ACP_BASE_URL,
        base_url_env_var="COPILOT_ACP_BASE_URL",
    ),
    "gemini": ProviderConfig(
        id="gemini",
        name="Google AI Studio",
        auth_type="api_key",
        inference_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
        base_url_env_var="GEMINI_BASE_URL",
    ),
    "zai": ProviderConfig(
        id="zai",
        name="Z.AI / GLM",
        auth_type="api_key",
        inference_base_url="https://api.z.ai/api/paas/v4",
        api_key_env_vars=("GLM_API_KEY", "ZAI_API_KEY", "Z_AI_API_KEY"),
        base_url_env_var="GLM_BASE_URL",
    ),
    "kimi-coding": ProviderConfig(
        id="kimi-coding",
        name="Kimi / Moonshot",
        auth_type="api_key",
        inference_base_url="https://api.moonshot.ai/v1",
        api_key_env_vars=("KIMI_API_KEY",),
        base_url_env_var="KIMI_BASE_URL",
    ),
    "kimi-coding-cn": ProviderConfig(
        id="kimi-coding-cn",
        name="Kimi / Moonshot (China)",
        auth_type="api_key",
        inference_base_url="https://api.moonshot.cn/v1",
        api_key_env_vars=("KIMI_CN_API_KEY",),
    ),
    "arcee": ProviderConfig(
        id="arcee",
        name="Arcee AI",
        auth_type="api_key",
        inference_base_url="https://api.arcee.ai/api/v1",
        api_key_env_vars=("ARCEEAI_API_KEY",),
        base_url_env_var="ARCEE_BASE_URL",
    ),
    "minimax": ProviderConfig(
        id="minimax",
        name="MiniMax",
        auth_type="api_key",
        inference_base_url="https://api.minimax.io/anthropic",
        api_key_env_vars=("MINIMAX_API_KEY",),
        base_url_env_var="MINIMAX_BASE_URL",
    ),
    "anthropic": ProviderConfig(
        id="anthropic",
        name="Anthropic",
        auth_type="api_key",
        inference_base_url="https://api.anthropic.com",
        api_key_env_vars=(
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_TOKEN",
            "CLAUDE_CODE_OAUTH_TOKEN",
        ),
    ),
    "alibaba": ProviderConfig(
        id="alibaba",
        name="Alibaba Cloud (DashScope)",
        auth_type="api_key",
        inference_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        api_key_env_vars=("DASHSCOPE_API_KEY",),
        base_url_env_var="DASHSCOPE_BASE_URL",
    ),
    "minimax-cn": ProviderConfig(
        id="minimax-cn",
        name="MiniMax (China)",
        auth_type="api_key",
        inference_base_url="https://api.minimaxi.com/anthropic",
        api_key_env_vars=("MINIMAX_CN_API_KEY",),
        base_url_env_var="MINIMAX_CN_BASE_URL",
    ),
    "deepseek": ProviderConfig(
        id="deepseek",
        name="DeepSeek",
        auth_type="api_key",
        inference_base_url="https://api.deepseek.com/v1",
        api_key_env_vars=("DEEPSEEK_API_KEY",),
        base_url_env_var="DEEPSEEK_BASE_URL",
    ),
    "xai": ProviderConfig(
        id="xai",
        name="xAI",
        auth_type="api_key",
        inference_base_url="https://api.x.ai/v1",
        api_key_env_vars=("XAI_API_KEY",),
        base_url_env_var="XAI_BASE_URL",
    ),
    "ai-gateway": ProviderConfig(
        id="ai-gateway",
        name="Vercel AI Gateway",
        auth_type="api_key",
        inference_base_url="https://ai-gateway.vercel.sh/v1",
        api_key_env_vars=("AI_GATEWAY_API_KEY",),
        base_url_env_var="AI_GATEWAY_BASE_URL",
    ),
    "opencode-zen": ProviderConfig(
        id="opencode-zen",
        name="OpenCode Zen",
        auth_type="api_key",
        inference_base_url="https://opencode.ai/zen/v1",
        api_key_env_vars=("OPENCODE_ZEN_API_KEY",),
        base_url_env_var="OPENCODE_ZEN_BASE_URL",
    ),
    "opencode-go": ProviderConfig(
        id="opencode-go",
        name="OpenCode Go",
        auth_type="api_key",
        # OpenCode Go mixes API surfaces by model:
        # - GLM / Kimi use OpenAI-compatible chat completions under /v1
        # - MiniMax models use Anthropic Messages under /v1/messages
        # Keep the provider base at /v1 and select api_mode per-model.
        inference_base_url="https://opencode.ai/zen/go/v1",
        api_key_env_vars=("OPENCODE_GO_API_KEY",),
        base_url_env_var="OPENCODE_GO_BASE_URL",
    ),
    "kilocode": ProviderConfig(
        id="kilocode",
        name="Kilo Code",
        auth_type="api_key",
        inference_base_url="https://api.kilo.ai/api/gateway",
        api_key_env_vars=("KILOCODE_API_KEY",),
        base_url_env_var="KILOCODE_BASE_URL",
    ),
    "huggingface": ProviderConfig(
        id="huggingface",
        name="Hugging Face",
        auth_type="api_key",
        inference_base_url="https://router.huggingface.co/v1",
        api_key_env_vars=("HF_TOKEN",),
        base_url_env_var="HF_BASE_URL",
    ),
    "xiaomi": ProviderConfig(
        id="xiaomi",
        name="Xiaomi MiMo",
        auth_type="api_key",
        inference_base_url="https://api.xiaomimimo.com/v1",
        api_key_env_vars=("XIAOMI_API_KEY",),
        base_url_env_var="XIAOMI_BASE_URL",
    ),
    "ollama": ProviderConfig(
        id="ollama",
        name="Ollama (local)",
        auth_type="none",
        inference_base_url="http://localhost:11434/v1",
        api_key_env_vars=(),
        base_url_env_var="OLLAMA_BASE_URL",
    ),
}


# =============================================================================
# Anthropic Key Helper
# =============================================================================


def get_anthropic_key() -> str:
    """Return the first usable Anthropic credential, or ``""``.

    Checks both the ``.env`` file (via ``get_env_value``) and the process
    environment (``os.getenv``).  The fallback order mirrors the
    ``PROVIDER_REGISTRY["anthropic"].api_key_env_vars`` tuple:

        ANTHROPIC_API_KEY -> ANTHROPIC_TOKEN -> CLAUDE_CODE_OAUTH_TOKEN
    """
    from spark_cli.config import get_env_value

    for var in PROVIDER_REGISTRY["anthropic"].api_key_env_vars:
        value = get_env_value(var) or os.getenv(var, "")
        if value:
            return value
    return ""


# =============================================================================
# Kimi Code Endpoint Detection
# =============================================================================

# Kimi Code (kimi.com/code) issues keys prefixed "sk-kimi-" that only work
# on api.kimi.com/coding/v1.  Legacy keys from platform.moonshot.ai work on
# api.moonshot.ai/v1 (the default).  Auto-detect when user hasn't set
# KIMI_BASE_URL explicitly.
KIMI_CODE_BASE_URL = "https://api.kimi.com/coding/v1"


def _resolve_kimi_base_url(api_key: str, default_url: str, env_override: str) -> str:
    """Return the correct Kimi base URL based on the API key prefix.

    If the user has explicitly set KIMI_BASE_URL, that always wins.
    Otherwise, sk-kimi- prefixed keys route to api.kimi.com/coding/v1.
    """
    if env_override:
        return env_override
    if api_key.startswith("sk-kimi-"):
        return KIMI_CODE_BASE_URL
    return default_url


_PLACEHOLDER_SECRET_VALUES = {
    "*",
    "**",
    "***",
    "changeme",
    "your_api_key",
    "your-api-key",
    "placeholder",
    "example",
    "dummy",
    "null",
    "none",
}


def has_usable_secret(value: Any, *, min_length: int = 4) -> bool:
    """Return True when a configured secret looks usable, not empty/placeholder."""
    if not isinstance(value, str):
        return False
    cleaned = value.strip()
    if len(cleaned) < min_length:
        return False
    if cleaned.lower() in _PLACEHOLDER_SECRET_VALUES:
        return False
    return True


def _resolve_api_key_provider_secret(
    provider_id: str, pconfig: ProviderConfig
) -> tuple[str, str]:
    """Resolve an API-key provider's token and indicate where it came from."""
    if provider_id == "copilot":
        # Use the dedicated copilot auth module for proper token validation
        try:
            from spark_cli.copilot_auth import resolve_copilot_token

            token, source = resolve_copilot_token()
            if token:
                return token, source
        except ValueError as exc:
            logger.warning("Copilot token validation failed: %s", exc)
        except Exception:
            pass
        return "", ""

    for env_var in pconfig.api_key_env_vars:
        val = os.getenv(env_var, "").strip()
        if has_usable_secret(val):
            return val, env_var

    return "", ""


# =============================================================================
# Z.AI Endpoint Detection
# =============================================================================

# Z.AI has separate billing for general vs coding plans, and global vs China
# endpoints.  A key that works on one may return "Insufficient balance" on
# another.  We probe at setup time and store the working endpoint.

ZAI_ENDPOINTS = [
    # (id, base_url, default_model, label)
    ("global", "https://api.z.ai/api/paas/v4", "glm-5", "Global"),
    ("cn", "https://open.bigmodel.cn/api/paas/v4", "glm-5", "China"),
    (
        "coding-global",
        "https://api.z.ai/api/coding/paas/v4",
        "glm-4.7",
        "Global (Coding Plan)",
    ),
    (
        "coding-cn",
        "https://open.bigmodel.cn/api/coding/paas/v4",
        "glm-4.7",
        "China (Coding Plan)",
    ),
]


def detect_zai_endpoint(api_key: str, timeout: float = 8.0) -> dict[str, str] | None:
    """Probe z.ai endpoints to find one that accepts this API key.

    Returns {"id": ..., "base_url": ..., "model": ..., "label": ...} for the
    first working endpoint, or None if all fail.
    """
    for ep_id, base_url, model, label in ZAI_ENDPOINTS:
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "stream": False,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                logger.debug("Z.AI endpoint probe: %s (%s) OK", ep_id, base_url)
                return {
                    "id": ep_id,
                    "base_url": base_url,
                    "model": model,
                    "label": label,
                }
            logger.debug("Z.AI endpoint probe: %s returned %s", ep_id, resp.status_code)
        except Exception as exc:
            logger.debug("Z.AI endpoint probe: %s failed: %s", ep_id, exc)
    return None


def _resolve_zai_base_url(api_key: str, default_url: str, env_override: str) -> str:
    """Return the correct Z.AI base URL by probing endpoints.

    If the user has explicitly set GLM_BASE_URL, that always wins.
    Otherwise, probe the candidate endpoints to find one that accepts the
    key.  The detected endpoint is cached in provider state (auth.json) keyed
    on a hash of the API key so subsequent starts skip the probe.
    """
    if env_override:
        return env_override

    # Check provider-state cache for a previously-detected endpoint.
    auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "zai") or {}
    cached = state.get("detected_endpoint")
    if isinstance(cached, dict) and cached.get("base_url"):
        key_hash = cached.get("key_hash", "")
        if key_hash == hashlib.sha256(api_key.encode()).hexdigest()[:16]:
            logger.debug("Z.AI: using cached endpoint %s", cached["base_url"])
            return cached["base_url"]

    # Probe — may take up to ~8s per endpoint.
    detected = detect_zai_endpoint(api_key)
    if detected and detected.get("base_url"):
        # Persist the detection result keyed on the API key hash.
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        state["detected_endpoint"] = {
            "base_url": detected["base_url"],
            "endpoint_id": detected.get("id", ""),
            "model": detected.get("model", ""),
            "label": detected.get("label", ""),
            "key_hash": key_hash,
        }
        _save_provider_state(auth_store, "zai", state)
        logger.info(
            "Z.AI: auto-detected endpoint %s (%s)",
            detected["label"],
            detected["base_url"],
        )
        return detected["base_url"]

    logger.debug("Z.AI: probe failed, falling back to default %s", default_url)
    return default_url


# =============================================================================
# Error Types
# =============================================================================


class AuthError(RuntimeError):
    """Structured auth error with UX mapping hints."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        code: str | None = None,
        relogin_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.relogin_required = relogin_required


def format_auth_error(error: Exception) -> str:
    """Map auth failures to concise user-facing guidance."""
    if not isinstance(error, AuthError):
        return str(error)

    if error.relogin_required:
        return f"{error} Run `spark model` to re-authenticate."

    if error.code == "subscription_required":
        return (
            "No active paid subscription found for this provider. "
            "Please purchase/activate a subscription, then retry."
        )

    if error.code == "insufficient_credits":
        return (
            "Subscription credits are exhausted. "
            "Top up/renew credits with the provider, then retry."
        )

    if error.code == "temporarily_unavailable":
        return f"{error} Please retry in a few seconds."

    return str(error)


def _token_fingerprint(token: Any) -> str | None:
    """Return a short hash fingerprint for telemetry without leaking token bytes."""
    if not isinstance(token, str):
        return None
    cleaned = token.strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:12]


def _oauth_trace_enabled() -> bool:
    raw = os.getenv("SPARK_OAUTH_TRACE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _oauth_trace(
    event: str, *, sequence_id: str | None = None, **fields: Any
) -> None:
    if not _oauth_trace_enabled():
        return
    payload: dict[str, Any] = {"event": event}
    if sequence_id:
        payload["sequence_id"] = sequence_id
    payload.update(fields)
    logger.info(
        "oauth_trace %s", json.dumps(payload, sort_keys=True, ensure_ascii=False)
    )


# =============================================================================
# Auth Store — persistence layer for ~/.spark/auth.json
# =============================================================================


def _auth_file_path() -> Path:
    return get_spark_home() / "auth.json"


def _auth_lock_path() -> Path:
    return _auth_file_path().with_suffix(".lock")


_auth_lock_holder = threading.local()


@contextmanager
def _auth_store_lock(timeout_seconds: float = AUTH_LOCK_TIMEOUT_SECONDS):
    """Cross-process advisory lock for auth.json reads+writes.  Reentrant."""
    # Reentrant: if this thread already holds the lock, just yield.
    if getattr(_auth_lock_holder, "depth", 0) > 0:
        _auth_lock_holder.depth += 1
        try:
            yield
        finally:
            _auth_lock_holder.depth -= 1
        return

    lock_path = _auth_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None and msvcrt is None:
        _auth_lock_holder.depth = 1
        try:
            yield
        finally:
            _auth_lock_holder.depth = 0
        return

    # On Windows, msvcrt.locking needs the file to have content and the
    # file pointer at position 0.  Ensure the lock file has at least 1 byte.
    if msvcrt and (not lock_path.exists() or lock_path.stat().st_size == 0):
        lock_path.write_text(" ", encoding="utf-8")

    with lock_path.open("r+" if msvcrt else "a+") as lock_file:
        deadline = time.time() + max(1.0, timeout_seconds)
        while True:
            try:
                if fcntl:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except (BlockingIOError, OSError, PermissionError):
                if time.time() >= deadline:
                    raise TimeoutError("Timed out waiting for auth store lock")
                time.sleep(0.05)

        _auth_lock_holder.depth = 1
        try:
            yield
        finally:
            _auth_lock_holder.depth = 0
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def _load_auth_store(auth_file: Path | None = None) -> dict[str, Any]:
    auth_file = auth_file or _auth_file_path()
    if not auth_file.exists():
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    try:
        raw = json.loads(auth_file.read_text())
    except Exception:
        return {"version": AUTH_STORE_VERSION, "providers": {}}

    if isinstance(raw, dict) and (
        isinstance(raw.get("providers"), dict)
        or isinstance(raw.get("credential_pool"), dict)
    ):
        raw.setdefault("providers", {})
        return raw

    return {"version": AUTH_STORE_VERSION, "providers": {}}


def _save_auth_store(auth_store: dict[str, Any]) -> Path:
    auth_file = _auth_file_path()
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_store["version"] = AUTH_STORE_VERSION
    auth_store["updated_at"] = datetime.now(UTC).isoformat()
    payload = json.dumps(auth_store, indent=2) + "\n"
    tmp_path = auth_file.with_name(
        f"{auth_file.name}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, auth_file)
        try:
            dir_fd = os.open(str(auth_file.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    # Restrict file permissions to owner only
    try:
        auth_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return auth_file


def _load_provider_state(
    auth_store: dict[str, Any], provider_id: str
) -> dict[str, Any] | None:
    providers = auth_store.get("providers")
    if not isinstance(providers, dict):
        return None
    state = providers.get(provider_id)
    return dict(state) if isinstance(state, dict) else None


def _save_provider_state(
    auth_store: dict[str, Any], provider_id: str, state: dict[str, Any]
) -> None:
    providers = auth_store.setdefault("providers", {})
    if not isinstance(providers, dict):
        auth_store["providers"] = {}
        providers = auth_store["providers"]
    providers[provider_id] = state
    auth_store["active_provider"] = provider_id


def read_credential_pool(provider_id: str | None = None) -> dict[str, Any]:
    """Return the persisted credential pool, or one provider slice."""
    auth_store = _load_auth_store()
    pool = auth_store.get("credential_pool")
    if not isinstance(pool, dict):
        pool = {}
    if provider_id is None:
        return dict(pool)
    provider_entries = pool.get(provider_id)
    return list(provider_entries) if isinstance(provider_entries, list) else []


def write_credential_pool(provider_id: str, entries: list[dict[str, Any]]) -> Path:
    """Persist one provider's credential pool under auth.json."""
    with _auth_store_lock():
        auth_store = _load_auth_store()
        pool = auth_store.get("credential_pool")
        if not isinstance(pool, dict):
            pool = {}
            auth_store["credential_pool"] = pool
        pool[provider_id] = list(entries)
        return _save_auth_store(auth_store)


def suppress_credential_source(provider_id: str, source: str) -> None:
    """Mark a credential source as suppressed so it won't be re-seeded."""
    with _auth_store_lock():
        auth_store = _load_auth_store()
        suppressed = auth_store.setdefault("suppressed_sources", {})
        provider_list = suppressed.setdefault(provider_id, [])
        if source not in provider_list:
            provider_list.append(source)
        _save_auth_store(auth_store)


def is_source_suppressed(provider_id: str, source: str) -> bool:
    """Check if a credential source has been suppressed by the user."""
    try:
        auth_store = _load_auth_store()
        suppressed = auth_store.get("suppressed_sources", {})
        return source in suppressed.get(provider_id, [])
    except Exception:
        return False


def get_provider_auth_state(provider_id: str) -> dict[str, Any] | None:
    """Return persisted auth state for a provider, or None."""
    auth_store = _load_auth_store()
    return _load_provider_state(auth_store, provider_id)


def get_active_provider() -> str | None:
    """Return the currently active provider ID from auth store."""
    auth_store = _load_auth_store()
    return auth_store.get("active_provider")


def is_provider_explicitly_configured(provider_id: str) -> bool:
    """Return True only if the user has explicitly configured this provider.

    Checks:
      1. active_provider in auth.json matches
      2. model.provider in config.yaml matches
      3. Provider-specific env vars are set (e.g. ANTHROPIC_API_KEY)

    This is used to gate auto-discovery of external credentials (e.g.
    Claude Code's ~/.claude/.credentials.json) so they are never used
    without the user's explicit choice.  See PR #4210 for the same
    pattern applied to the setup wizard gate.
    """
    normalized = (provider_id or "").strip().lower()

    # 1. Check auth.json active_provider
    try:
        auth_store = _load_auth_store()
        active = (auth_store.get("active_provider") or "").strip().lower()
        if active and active == normalized:
            return True
    except Exception:
        pass

    # 2. Check config.yaml model.provider
    try:
        from spark_cli.config import load_config

        cfg = load_config()
        model_cfg = cfg.get("model")
        if isinstance(model_cfg, dict):
            cfg_provider = (model_cfg.get("provider") or "").strip().lower()
            if cfg_provider == normalized:
                return True
    except Exception:
        pass

    # 3. Check provider-specific env vars
    # Exclude CLAUDE_CODE_OAUTH_TOKEN — it's set by Claude Code itself,
    # not by the user explicitly configuring anthropic in Spark.
    _IMPLICIT_ENV_VARS = {"CLAUDE_CODE_OAUTH_TOKEN"}
    pconfig = PROVIDER_REGISTRY.get(normalized)
    if pconfig and pconfig.auth_type == "api_key":
        for env_var in pconfig.api_key_env_vars:
            if env_var in _IMPLICIT_ENV_VARS:
                continue
            if has_usable_secret(os.getenv(env_var, "")):
                return True

    return False


def clear_provider_auth(provider_id: str | None = None) -> bool:
    """
    Clear auth state for a provider. Used by `spark logout`.
    If provider_id is None, clears the active provider.
    Returns True if something was cleared.
    """
    with _auth_store_lock():
        auth_store = _load_auth_store()
        target = provider_id or auth_store.get("active_provider")
        if not target:
            return False

        providers = auth_store.get("providers", {})
        if not isinstance(providers, dict):
            providers = {}
            auth_store["providers"] = providers

        pool = auth_store.get("credential_pool")
        if not isinstance(pool, dict):
            pool = {}
            auth_store["credential_pool"] = pool

        cleared = False
        if target in providers:
            del providers[target]
            cleared = True
        if target in pool:
            del pool[target]
            cleared = True

        if not cleared:
            return False
        if auth_store.get("active_provider") == target:
            auth_store["active_provider"] = None
        _save_auth_store(auth_store)
    return True


def deactivate_provider() -> None:
    """
    Clear active_provider in auth.json without deleting credentials.
    Used when the user switches to a non-OAuth provider (OpenRouter, custom)
    so auto-resolution doesn't keep picking the OAuth provider.
    """
    with _auth_store_lock():
        auth_store = _load_auth_store()
        auth_store["active_provider"] = None
        _save_auth_store(auth_store)


# =============================================================================
# Provider Resolution — picks which provider to use
# =============================================================================


def _get_config_hint_for_unknown_provider(provider_name: str) -> str:
    """Return a helpful hint string when provider resolution fails.

    Checks for common config.yaml mistakes (malformed custom_providers, etc.)
    and returns a human-readable diagnostic, or empty string if nothing found.
    """
    try:
        from spark_cli.config import validate_config_structure

        issues = validate_config_structure()
        if not issues:
            return ""

        lines = ["Config issue detected — run 'spark doctor' for full diagnostics:"]
        for ci in issues:
            prefix = "ERROR" if ci.severity == "error" else "WARNING"
            lines.append(f"  [{prefix}] {ci.message}")
            # Show first line of hint
            first_hint = ci.hint.splitlines()[0] if ci.hint else ""
            if first_hint:
                lines.append(f"    → {first_hint}")
        return "\n".join(lines)
    except Exception:
        return ""


def resolve_provider(
    requested: str | None = None,
    *,
    explicit_api_key: str | None = None,
    explicit_base_url: str | None = None,
) -> str:
    """
    Determine which inference provider to use.

    Priority (when requested="auto" or None):
    1. active_provider in auth.json with valid credentials
    2. Explicit CLI api_key/base_url -> "openrouter"
    3. OPENAI_API_KEY or OPENROUTER_API_KEY env vars -> "openrouter"
    4. Provider-specific API keys (GLM, Kimi, MiniMax) -> that provider
    5. Fallback: "openrouter"
    """
    normalized = (requested or "auto").strip().lower()

    # Normalize provider aliases
    _PROVIDER_ALIASES = {
        "glm": "zai",
        "z-ai": "zai",
        "z.ai": "zai",
        "zhipu": "zai",
        "google": "gemini",
        "google-gemini": "gemini",
        "google-ai-studio": "gemini",
        "kimi": "kimi-coding",
        "kimi-for-coding": "kimi-coding",
        "moonshot": "kimi-coding",
        "kimi-cn": "kimi-coding-cn",
        "moonshot-cn": "kimi-coding-cn",
        "arcee-ai": "arcee",
        "arceeai": "arcee",
        "minimax-china": "minimax-cn",
        "minimax_cn": "minimax-cn",
        "claude": "anthropic",
        "claude-code": "anthropic",
        "github": "copilot",
        "github-copilot": "copilot",
        "github-models": "copilot",
        "github-model": "copilot",
        "github-copilot-acp": "copilot-acp",
        "copilot-acp-agent": "copilot-acp",
        "aigateway": "ai-gateway",
        "vercel": "ai-gateway",
        "vercel-ai-gateway": "ai-gateway",
        "opencode": "opencode-zen",
        "zen": "opencode-zen",
        "qwen-portal": "qwen-oauth",
        "qwen-cli": "qwen-oauth",
        "qwen-oauth": "qwen-oauth",
        "hf": "huggingface",
        "hugging-face": "huggingface",
        "huggingface-hub": "huggingface",
        "mimo": "xiaomi",
        "xiaomi-mimo": "xiaomi",
        "go": "opencode-go",
        "opencode-go-sub": "opencode-go",
        "kilo": "kilocode",
        "kilo-code": "kilocode",
        "kilo-gateway": "kilocode",
        # Local server aliases — route through the generic custom provider
        "lmstudio": "custom",
        "lm-studio": "custom",
        "lm_studio": "custom",
        "vllm": "custom",
        "llamacpp": "custom",
        "llama.cpp": "custom",
        "llama-cpp": "custom",
    }
    normalized = _PROVIDER_ALIASES.get(normalized, normalized)

    if normalized == "openrouter":
        return "openrouter"
    if normalized == "custom":
        return "custom"
    if normalized in PROVIDER_REGISTRY:
        return normalized
    if normalized != "auto":
        # Check for common config.yaml issues that cause this error
        _config_hint = _get_config_hint_for_unknown_provider(normalized)
        msg = f"Unknown provider '{normalized}'."
        if _config_hint:
            msg += f"\n\n{_config_hint}"
        else:
            msg += " Check 'spark model' for available providers, or run 'spark doctor' to diagnose config issues."
        raise AuthError(msg, code="invalid_provider")

    # Explicit one-off CLI creds always mean openrouter/custom
    if explicit_api_key or explicit_base_url:
        return "openrouter"

    # Check auth store for an active OAuth provider
    try:
        auth_store = _load_auth_store()
        active = auth_store.get("active_provider")
        if active in _DEPRECATED_PROVIDERS:
            active = None
        if active and active in PROVIDER_REGISTRY:
            status = get_auth_status(active)
            if status.get("logged_in"):
                return active
    except Exception as e:
        logger.debug("Could not detect active auth provider: %s", e)

    if has_usable_secret(os.getenv("OPENAI_API_KEY")) or has_usable_secret(
        os.getenv("OPENROUTER_API_KEY")
    ):
        return "openrouter"

    # Auto-detect API-key providers by checking their env vars
    for pid, pconfig in PROVIDER_REGISTRY.items():
        if pconfig.auth_type != "api_key":
            continue
        # GitHub tokens are commonly present for repo/tool access but should not
        # hijack inference auto-selection unless the user explicitly chooses
        # Copilot/GitHub Models as the provider.
        if pid == "copilot":
            continue
        for env_var in pconfig.api_key_env_vars:
            if has_usable_secret(os.getenv(env_var, "")):
                return pid

    raise AuthError(
        "No inference provider configured. Run 'spark model' to choose a "
        "provider and model, or set an API key (OPENROUTER_API_KEY, "
        "OPENAI_API_KEY, etc.) in ~/.spark/.env.",
        code="no_provider_configured",
    )


# =============================================================================
# Timestamp / TTL helpers
# =============================================================================


def _parse_iso_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _is_expiring(expires_at_iso: Any, skew_seconds: int) -> bool:
    expires_epoch = _parse_iso_timestamp(expires_at_iso)
    if expires_epoch is None:
        return True
    return expires_epoch <= (time.time() + skew_seconds)


def _coerce_ttl_seconds(expires_in: Any) -> int:
    try:
        ttl = int(expires_in)
    except Exception:
        ttl = 0
    return max(0, ttl)


def _optional_base_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip().rstrip("/")
    return cleaned if cleaned else None


def _decode_jwt_claims(token: Any) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * ((4 - len(payload) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("utf-8"))
        claims = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}


def _codex_access_token_is_expiring(access_token: Any, skew_seconds: int) -> bool:
    claims = _decode_jwt_claims(access_token)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= (time.time() + max(0, int(skew_seconds)))


def _codex_token_exp(access_token: Any) -> float | None:
    """Return a Codex access token's JWT ``exp`` (epoch seconds), or None.

    Used to compare two tokens' freshness — e.g. deciding whether the Codex CLI
    shared store holds a newer token than Spark's own, which signals Spark's
    token was superseded by the CLI rotating their shared refresh token.
    """
    exp = _decode_jwt_claims(access_token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else None


def _qwen_cli_auth_path() -> Path:
    return Path.home() / ".qwen" / "oauth_creds.json"


def _read_qwen_cli_tokens() -> dict[str, Any]:
    auth_path = _qwen_cli_auth_path()
    if not auth_path.exists():
        raise AuthError(
            "Qwen CLI credentials not found. Run 'qwen auth qwen-oauth' first.",
            provider="qwen-oauth",
            code="qwen_auth_missing",
        )
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AuthError(
            f"Failed to read Qwen CLI credentials from {auth_path}: {exc}",
            provider="qwen-oauth",
            code="qwen_auth_read_failed",
        ) from exc
    if not isinstance(data, dict):
        raise AuthError(
            f"Invalid Qwen CLI credentials in {auth_path}.",
            provider="qwen-oauth",
            code="qwen_auth_invalid",
        )
    return data


def _save_qwen_cli_tokens(tokens: dict[str, Any]) -> Path:
    auth_path = _qwen_cli_auth_path()
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = auth_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(tokens, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(auth_path)
    return auth_path


def _qwen_access_token_is_expiring(
    expiry_date_ms: Any, skew_seconds: int = QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS
) -> bool:
    try:
        expiry_ms = int(expiry_date_ms)
    except Exception:
        return True
    return (time.time() + max(0, int(skew_seconds))) * 1000 >= expiry_ms


def _refresh_qwen_cli_tokens(
    tokens: dict[str, Any], timeout_seconds: float = 20.0
) -> dict[str, Any]:
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not refresh_token:
        raise AuthError(
            "Qwen OAuth refresh token missing. Re-run 'qwen auth qwen-oauth'.",
            provider="qwen-oauth",
            code="qwen_refresh_token_missing",
        )

    try:
        response = httpx.post(
            QWEN_OAUTH_TOKEN_URL,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": QWEN_OAUTH_CLIENT_ID,
            },
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise AuthError(
            f"Qwen OAuth refresh failed: {exc}",
            provider="qwen-oauth",
            code="qwen_refresh_failed",
        ) from exc

    if response.status_code >= 400:
        body = response.text.strip()
        raise AuthError(
            "Qwen OAuth refresh failed. Re-run 'qwen auth qwen-oauth'."
            + (f" Response: {body}" if body else ""),
            provider="qwen-oauth",
            code="qwen_refresh_failed",
        )

    try:
        payload = response.json()
    except Exception as exc:
        raise AuthError(
            f"Qwen OAuth refresh returned invalid JSON: {exc}",
            provider="qwen-oauth",
            code="qwen_refresh_invalid_json",
        ) from exc

    if (
        not isinstance(payload, dict)
        or not str(payload.get("access_token", "") or "").strip()
    ):
        raise AuthError(
            "Qwen OAuth refresh response missing access_token.",
            provider="qwen-oauth",
            code="qwen_refresh_invalid_response",
        )

    expires_in = payload.get("expires_in")
    try:
        expires_in_seconds = int(expires_in)
    except Exception:
        expires_in_seconds = 6 * 60 * 60

    refreshed = {
        "access_token": str(payload.get("access_token", "") or "").strip(),
        "refresh_token": str(
            payload.get("refresh_token", refresh_token) or refresh_token
        ).strip(),
        "token_type": str(
            payload.get("token_type", tokens.get("token_type", "Bearer")) or "Bearer"
        ).strip()
        or "Bearer",
        "resource_url": str(
            payload.get("resource_url", tokens.get("resource_url", "portal.qwen.ai"))
            or "portal.qwen.ai"
        ).strip(),
        "expiry_date": int(time.time() * 1000) + max(1, expires_in_seconds) * 1000,
    }
    _save_qwen_cli_tokens(refreshed)
    return refreshed


def resolve_qwen_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = QWEN_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> dict[str, Any]:
    tokens = _read_qwen_cli_tokens()
    access_token = str(tokens.get("access_token", "") or "").strip()
    should_refresh = bool(force_refresh)
    if not should_refresh and refresh_if_expiring:
        should_refresh = _qwen_access_token_is_expiring(
            tokens.get("expiry_date"), refresh_skew_seconds
        )
    if should_refresh:
        tokens = _refresh_qwen_cli_tokens(tokens)
        access_token = str(tokens.get("access_token", "") or "").strip()
    if not access_token:
        raise AuthError(
            "Qwen OAuth access token missing. Re-run 'qwen auth qwen-oauth'.",
            provider="qwen-oauth",
            code="qwen_access_token_missing",
        )

    base_url = (
        os.getenv("SPARK_QWEN_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_QWEN_BASE_URL
    )
    return {
        "provider": "qwen-oauth",
        "base_url": base_url,
        "api_key": access_token,
        "source": "qwen-cli",
        "expires_at_ms": tokens.get("expiry_date"),
        "auth_file": str(_qwen_cli_auth_path()),
    }


def get_qwen_auth_status() -> dict[str, Any]:
    auth_path = _qwen_cli_auth_path()
    try:
        creds = resolve_qwen_runtime_credentials(refresh_if_expiring=False)
        return {
            "logged_in": True,
            "auth_file": str(auth_path),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
            "expires_at_ms": creds.get("expires_at_ms"),
        }
    except AuthError as exc:
        return {
            "logged_in": False,
            "auth_file": str(auth_path),
            "error": str(exc),
        }


# =============================================================================
# SSH / remote session detection
# =============================================================================


def _is_remote_session() -> bool:
    """Detect if running in an SSH session where webbrowser.open() won't work."""
    return bool(os.getenv("SSH_CLIENT") or os.getenv("SSH_TTY"))


# =============================================================================
# OpenAI Codex auth — tokens stored in ~/.spark/auth.json (not ~/.codex/)
#
# Spark maintains its own Codex OAuth session separate from the Codex CLI
# and VS Code extension. This prevents refresh token rotation conflicts
# where one app's refresh invalidates the other's session.
# =============================================================================


def _read_codex_tokens(*, _lock: bool = True) -> dict[str, Any]:
    """Read Codex OAuth tokens from Spark auth store (~/.spark/auth.json).

    Returns dict with 'tokens' (access_token, refresh_token) and 'last_refresh'.
    Raises AuthError if no Codex tokens are stored.
    """
    if _lock:
        with _auth_store_lock():
            auth_store = _load_auth_store()
    else:
        auth_store = _load_auth_store()
    state = _load_provider_state(auth_store, "openai-codex")
    if not state:
        raise AuthError(
            "No Codex credentials stored. Run `spark auth` to authenticate.",
            provider="openai-codex",
            code="codex_auth_missing",
            relogin_required=True,
        )
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        raise AuthError(
            "Codex auth state is missing tokens. Run `spark auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_invalid_shape",
            relogin_required=True,
        )
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise AuthError(
            "Codex auth is missing access_token. Run `spark auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_access_token",
            relogin_required=True,
        )
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise AuthError(
            "Codex auth is missing refresh_token. Run `spark auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )
    return {
        "tokens": tokens,
        "last_refresh": state.get("last_refresh"),
    }


def _write_codex_cli_tokens(
    access_token: str,
    refresh_token: str,
    *,
    id_token: str | None = None,
    last_refresh: str | None = None,
) -> None:
    """Write refreshed tokens back to ~/.codex/auth.json.

    OpenAI OAuth refresh tokens are single-use and rotate on every refresh.
    When Spark refreshes a token it consumes the old refresh_token; if we
    don't write the new pair back, the Codex CLI (or VS Code extension) will
    fail with ``refresh_token_reused`` on its next refresh attempt.

    This mirrors the Anthropic write-back to ~/.claude/.credentials.json
    via ``_write_claude_code_credentials()``.
    """
    codex_home = os.getenv("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    auth_path = Path(codex_home).expanduser() / "auth.json"
    try:
        existing: dict[str, Any] = {}
        if auth_path.is_file():
            existing = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            existing = {}

        tokens_dict = existing.get("tokens")
        if not isinstance(tokens_dict, dict):
            tokens_dict = {}
        tokens_dict["access_token"] = access_token
        tokens_dict["refresh_token"] = refresh_token
        if id_token:
            tokens_dict["id_token"] = id_token
        existing["tokens"] = tokens_dict
        if last_refresh is not None:
            existing["last_refresh"] = last_refresh

        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        auth_path.chmod(0o600)
    except OSError as exc:
        logger.debug("Failed to write refreshed tokens to %s: %s", auth_path, exc)


def _save_codex_tokens(tokens: dict[str, str], last_refresh: str = None) -> None:
    """Save Codex OAuth tokens to Spark auth store (~/.spark/auth.json)."""
    if last_refresh is None:
        last_refresh = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with _auth_store_lock():
        auth_store = _load_auth_store()
        state = _load_provider_state(auth_store, "openai-codex") or {}
        state["tokens"] = tokens
        state["last_refresh"] = last_refresh
        state["auth_mode"] = "chatgpt"
        _save_provider_state(auth_store, "openai-codex", state)
        _save_auth_store(auth_store)


def refresh_codex_oauth_pure(
    access_token: str,
    refresh_token: str,
    *,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Refresh Codex OAuth tokens without mutating Spark auth state."""
    del (
        access_token
    )  # Access token is only used by callers to decide whether to refresh.
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise AuthError(
            "Codex auth is missing refresh_token. Run `spark auth` to re-authenticate.",
            provider="openai-codex",
            code="codex_auth_missing_refresh_token",
            relogin_required=True,
        )

    timeout = httpx.Timeout(max(5.0, float(timeout_seconds)))
    with httpx.Client(
        timeout=timeout, headers={"Accept": "application/json"}
    ) as client:
        response = client.post(
            CODEX_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": CODEX_OAUTH_CLIENT_ID,
            },
        )

    if response.status_code != 200:
        code = "codex_refresh_failed"
        message = f"Codex token refresh failed with status {response.status_code}."
        relogin_required = False
        try:
            err = response.json()
            if isinstance(err, dict):
                err_code = err.get("error")
                if isinstance(err_code, str) and err_code.strip():
                    code = err_code.strip()
                err_desc = err.get("error_description") or err.get("message")
                if isinstance(err_desc, str) and err_desc.strip():
                    message = f"Codex token refresh failed: {err_desc.strip()}"
        except Exception:
            pass
        if code in {"invalid_grant", "invalid_token", "invalid_request"}:
            relogin_required = True
        if code == "refresh_token_reused":
            message = (
                "Codex refresh token was already consumed by another client "
                "(e.g. Codex CLI or VS Code extension). "
                "Run `codex` in your terminal to generate fresh tokens, "
                "then run `spark auth` to re-authenticate."
            )
            relogin_required = True
        raise AuthError(
            message,
            provider="openai-codex",
            code=code,
            relogin_required=relogin_required,
        )

    try:
        refresh_payload = response.json()
    except Exception as exc:
        raise AuthError(
            "Codex token refresh returned invalid JSON.",
            provider="openai-codex",
            code="codex_refresh_invalid_json",
            relogin_required=True,
        ) from exc

    refreshed_access = refresh_payload.get("access_token")
    if not isinstance(refreshed_access, str) or not refreshed_access.strip():
        raise AuthError(
            "Codex token refresh response was missing access_token.",
            provider="openai-codex",
            code="codex_refresh_missing_access_token",
            relogin_required=True,
        )

    updated = {
        "access_token": refreshed_access.strip(),
        "refresh_token": refresh_token.strip(),
        "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    next_refresh = refresh_payload.get("refresh_token")
    if isinstance(next_refresh, str) and next_refresh.strip():
        updated["refresh_token"] = next_refresh.strip()
    # Preserve a refreshed id_token when the server returns one. Dropping it
    # left the stored id_token to expire while the access token kept rotating.
    next_id = refresh_payload.get("id_token")
    if isinstance(next_id, str) and next_id.strip():
        updated["id_token"] = next_id.strip()
    return updated


def _refresh_codex_auth_tokens(
    tokens: dict[str, str],
    timeout_seconds: float,
) -> dict[str, str]:
    """Refresh Codex access token using the refresh token.

    Saves the new tokens to Spark auth store automatically.
    """
    refreshed = refresh_codex_oauth_pure(
        str(tokens.get("access_token", "") or ""),
        str(tokens.get("refresh_token", "") or ""),
        timeout_seconds=timeout_seconds,
    )
    updated_tokens = dict(tokens)
    updated_tokens["access_token"] = refreshed["access_token"]
    updated_tokens["refresh_token"] = refreshed["refresh_token"]
    if refreshed.get("id_token"):
        updated_tokens["id_token"] = refreshed["id_token"]

    _save_codex_tokens(updated_tokens)
    # Write back to ~/.codex/auth.json so Codex CLI / VS Code stay in sync.
    _write_codex_cli_tokens(
        refreshed["access_token"],
        refreshed["refresh_token"],
        id_token=updated_tokens.get("id_token"),
        last_refresh=refreshed.get("last_refresh"),
    )
    return updated_tokens


def _import_codex_cli_tokens() -> dict[str, str] | None:
    """Try to read tokens from ~/.codex/auth.json (Codex CLI shared file).

    Returns tokens dict if valid and not expired, None otherwise.
    Does NOT write to the shared file.
    """
    codex_home = os.getenv("CODEX_HOME", "").strip()
    if not codex_home:
        codex_home = str(Path.home() / ".codex")
    auth_path = Path(codex_home).expanduser() / "auth.json"
    if not auth_path.is_file():
        return None
    try:
        payload = json.loads(auth_path.read_text())
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            return None
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not access_token or not refresh_token:
            return None
        # Reject expired tokens — importing stale tokens from ~/.codex/
        # that can't be refreshed leaves the user stuck with "Login successful!"
        # but no working credentials.
        if _codex_access_token_is_expiring(access_token, 0):
            logger.debug(
                "Codex CLI tokens at %s are expired — skipping import.",
                auth_path,
            )
            return None
        return dict(tokens)
    except Exception:
        return None


def resolve_codex_runtime_credentials(
    *,
    force_refresh: bool = False,
    refresh_if_expiring: bool = True,
    refresh_skew_seconds: int = CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS,
) -> dict[str, Any]:
    """Resolve runtime credentials from Spark's own Codex token store."""
    try:
        data = _read_codex_tokens()
    except AuthError as orig_err:
        # Only attempt migration when there are NO tokens stored at all
        # (code == "codex_auth_missing"), not when tokens exist but are invalid.
        if orig_err.code != "codex_auth_missing":
            raise

        # Migration: user had Codex as active provider with old storage (~/.codex/).
        cli_tokens = _import_codex_cli_tokens()
        if cli_tokens:
            logger.info(
                "Migrating Codex credentials from ~/.codex/ to Spark auth store"
            )
            print("⚠️  Migrating Codex credentials to Spark's own auth store.")
            print("   This avoids conflicts with Codex CLI and VS Code.")
            print("   Run `spark auth` to create a fully independent session.\n")
            _save_codex_tokens(cli_tokens)
            data = _read_codex_tokens()
        else:
            raise
    tokens = dict(data["tokens"])
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_timeout_seconds = float(
        os.getenv("SPARK_CODEX_REFRESH_TIMEOUT_SECONDS", "20")
    )

    should_refresh = bool(force_refresh)
    if (not should_refresh) and refresh_if_expiring:
        should_refresh = _codex_access_token_is_expiring(
            access_token, refresh_skew_seconds
        )
    if should_refresh:
        # Re-read under lock to avoid racing with other Spark processes
        with _auth_store_lock(
            timeout_seconds=max(
                float(AUTH_LOCK_TIMEOUT_SECONDS), refresh_timeout_seconds + 5.0
            )
        ):
            data = _read_codex_tokens(_lock=False)
            tokens = dict(data["tokens"])
            access_token = str(tokens.get("access_token", "") or "").strip()

            should_refresh = bool(force_refresh)
            if (not should_refresh) and refresh_if_expiring:
                should_refresh = _codex_access_token_is_expiring(
                    access_token, refresh_skew_seconds
                )

            if should_refresh:
                tokens = _refresh_codex_auth_tokens(tokens, refresh_timeout_seconds)
                access_token = str(tokens.get("access_token", "") or "").strip()

    base_url = (
        os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )

    return {
        "provider": "openai-codex",
        "base_url": base_url,
        "api_key": access_token,
        "source": "spark-auth-store",
        "last_refresh": data.get("last_refresh"),
        "auth_mode": "chatgpt",
    }


# =============================================================================
# TLS verification helper
# =============================================================================


def _resolve_verify(
    *,
    insecure: bool | None = None,
    ca_bundle: str | None = None,
    auth_state: dict[str, Any] | None = None,
) -> bool | str:
    tls_state = auth_state.get("tls") if isinstance(auth_state, dict) else {}
    tls_state = tls_state if isinstance(tls_state, dict) else {}

    effective_insecure = (
        bool(insecure)
        if insecure is not None
        else bool(tls_state.get("insecure", False))
    )
    effective_ca = (
        ca_bundle
        or tls_state.get("ca_bundle")
        or os.getenv("SPARK_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
    )

    if effective_insecure:
        return False
    if effective_ca:
        ca_path = str(effective_ca)
        if not os.path.isfile(ca_path):
            import logging

            logging.getLogger("spark.auth").warning(
                "CA bundle path does not exist: %s — falling back to default certificates",
                ca_path,
            )
            return True
        return ca_path
    return True


# =============================================================================
# OAuth Device Code Flow — generic, parameterized by provider
# =============================================================================


def _request_device_code(
    client: httpx.Client,
    portal_base_url: str,
    client_id: str,
    scope: str | None,
) -> dict[str, Any]:
    """POST to the device code endpoint. Returns device_code, user_code, etc."""
    response = client.post(
        f"{portal_base_url}/api/oauth/device/code",
        data={
            "client_id": client_id,
            **({"scope": scope} if scope else {}),
        },
    )
    response.raise_for_status()
    data = response.json()

    required_fields = [
        "device_code",
        "user_code",
        "verification_uri",
        "verification_uri_complete",
        "expires_in",
        "interval",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ValueError(f"Device code response missing fields: {', '.join(missing)}")
    return data


def _poll_for_token(
    client: httpx.Client,
    portal_base_url: str,
    client_id: str,
    device_code: str,
    expires_in: int,
    poll_interval: int,
) -> dict[str, Any]:
    """Poll the token endpoint until the user approves or the code expires."""
    deadline = time.time() + max(1, expires_in)
    current_interval = max(1, min(poll_interval, DEVICE_AUTH_POLL_INTERVAL_CAP_SECONDS))

    while time.time() < deadline:
        response = client.post(
            f"{portal_base_url}/api/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )

        if response.status_code == 200:
            payload = response.json()
            if "access_token" not in payload:
                raise ValueError("Token response did not include access_token")
            return payload

        try:
            error_payload = response.json()
        except Exception:
            response.raise_for_status()
            raise RuntimeError("Token endpoint returned a non-JSON error response")

        error_code = error_payload.get("error", "")
        if error_code == "authorization_pending":
            time.sleep(current_interval)
            continue
        if error_code == "slow_down":
            current_interval = min(current_interval + 1, 30)
            time.sleep(current_interval)
            continue

        description = (
            error_payload.get("error_description") or "Unknown authentication error"
        )
        raise RuntimeError(f"{error_code}: {description}")

    raise TimeoutError("Timed out waiting for device authorization")


# =============================================================================
# Status helpers
# =============================================================================



def get_codex_auth_status() -> dict[str, Any]:
    """Status snapshot for Codex auth.

    Checks the credential pool first (where `spark auth` stores credentials),
    then falls back to the legacy provider state.
    """
    # Check credential pool first — this is where `spark auth` and
    # `spark model` store device_code tokens.
    try:
        from agent.credential_pool import load_pool

        pool = load_pool("openai-codex")
        if pool and pool.has_credentials():
            entry = pool.select()
            if entry is not None:
                api_key = getattr(entry, "runtime_api_key", None) or getattr(
                    entry, "access_token", ""
                )
                if api_key and not _codex_access_token_is_expiring(api_key, 0):
                    return {
                        "logged_in": True,
                        "auth_store": str(_auth_file_path()),
                        "last_refresh": getattr(entry, "last_refresh", None),
                        "auth_mode": "chatgpt",
                        "source": f"pool:{getattr(entry, 'label', 'unknown')}",
                        "api_key": api_key,
                    }
    except Exception:
        pass

    # Fall back to legacy provider state
    try:
        creds = resolve_codex_runtime_credentials()
        return {
            "logged_in": True,
            "auth_store": str(_auth_file_path()),
            "last_refresh": creds.get("last_refresh"),
            "auth_mode": creds.get("auth_mode"),
            "source": creds.get("source"),
            "api_key": creds.get("api_key"),
        }
    except AuthError as exc:
        return {
            "logged_in": False,
            "auth_store": str(_auth_file_path()),
            "error": str(exc),
        }


def get_api_key_provider_status(provider_id: str) -> dict[str, Any]:
    """Status snapshot for API-key providers (z.ai, Kimi, MiniMax)."""
    pconfig = PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "api_key":
        return {"configured": False}

    api_key = ""
    key_source = ""
    api_key, key_source = _resolve_api_key_provider_secret(provider_id, pconfig)

    env_url = ""
    if pconfig.base_url_env_var:
        env_url = os.getenv(pconfig.base_url_env_var, "").strip()

    if provider_id == "kimi-coding":
        base_url = _resolve_kimi_base_url(api_key, pconfig.inference_base_url, env_url)
    elif env_url:
        base_url = env_url
    else:
        base_url = pconfig.inference_base_url

    return {
        "configured": bool(api_key),
        "provider": provider_id,
        "name": pconfig.name,
        "key_source": key_source,
        "base_url": base_url,
        "logged_in": bool(api_key),  # compat with OAuth status shape
    }


def get_external_process_provider_status(provider_id: str) -> dict[str, Any]:
    """Status snapshot for providers that run a local subprocess."""
    pconfig = PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "external_process":
        return {"configured": False}

    command = (
        os.getenv("SPARK_COPILOT_ACP_COMMAND", "").strip()
        or os.getenv("COPILOT_CLI_PATH", "").strip()
        or "copilot"
    )
    raw_args = os.getenv("SPARK_COPILOT_ACP_ARGS", "").strip()
    args = shlex.split(raw_args) if raw_args else ["--acp", "--stdio"]
    base_url = (
        os.getenv(pconfig.base_url_env_var, "").strip()
        if pconfig.base_url_env_var
        else ""
    )
    if not base_url:
        base_url = pconfig.inference_base_url

    resolved_command = shutil.which(command) if command else None
    return {
        "configured": bool(resolved_command or base_url.startswith("acp+tcp://")),
        "provider": provider_id,
        "name": pconfig.name,
        "command": command,
        "args": args,
        "resolved_command": resolved_command,
        "base_url": base_url,
        "logged_in": bool(resolved_command or base_url.startswith("acp+tcp://")),
    }


def get_auth_status(provider_id: str | None = None) -> dict[str, Any]:
    """Generic auth status dispatcher."""
    target = provider_id or get_active_provider()
    if target == "openai-codex":
        return get_codex_auth_status()
    if target == "qwen-oauth":
        return get_qwen_auth_status()
    if target == "copilot-acp":
        return get_external_process_provider_status(target)
    if target == "ollama":
        # Ollama needs no credentials — report as configured when it's the
        # active provider (model.provider == "ollama") or the env var is set.
        try:
            import os as _os

            from spark_cli.config import load_config as _load_config

            _cfg = _load_config()
            _model_cfg = _cfg.get("model", {})
            _is_active = (
                isinstance(_model_cfg, dict) and _model_cfg.get("provider") == "ollama"
            )
            _has_env = bool(_os.getenv("OLLAMA_BASE_URL", "").strip())
            if _is_active or _has_env:
                return {"logged_in": True, "configured": True, "auth_type": "none"}
        except Exception:
            pass
        return {"logged_in": False, "configured": False}
    # API-key providers
    pconfig = PROVIDER_REGISTRY.get(target)
    if pconfig and pconfig.auth_type == "api_key":
        return get_api_key_provider_status(target)
    return {"logged_in": False}


def resolve_api_key_provider_credentials(provider_id: str) -> dict[str, Any]:
    """Resolve API key and base URL for an API-key provider.

    Returns dict with: provider, api_key, base_url, source.
    """
    pconfig = PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "api_key":
        raise AuthError(
            f"Provider '{provider_id}' is not an API-key provider.",
            provider=provider_id,
            code="invalid_provider",
        )

    api_key = ""
    key_source = ""
    api_key, key_source = _resolve_api_key_provider_secret(provider_id, pconfig)

    env_url = ""
    if pconfig.base_url_env_var:
        env_url = os.getenv(pconfig.base_url_env_var, "").strip()

    if provider_id == "kimi-coding":
        base_url = _resolve_kimi_base_url(api_key, pconfig.inference_base_url, env_url)
    elif provider_id == "zai":
        base_url = _resolve_zai_base_url(api_key, pconfig.inference_base_url, env_url)
    elif env_url:
        base_url = env_url.rstrip("/")
    else:
        base_url = pconfig.inference_base_url

    return {
        "provider": provider_id,
        "api_key": api_key,
        "base_url": base_url.rstrip("/"),
        "source": key_source or "default",
    }


def resolve_external_process_provider_credentials(provider_id: str) -> dict[str, Any]:
    """Resolve runtime details for local subprocess-backed providers."""
    pconfig = PROVIDER_REGISTRY.get(provider_id)
    if not pconfig or pconfig.auth_type != "external_process":
        raise AuthError(
            f"Provider '{provider_id}' is not an external-process provider.",
            provider=provider_id,
            code="invalid_provider",
        )

    base_url = (
        os.getenv(pconfig.base_url_env_var, "").strip()
        if pconfig.base_url_env_var
        else ""
    )
    if not base_url:
        base_url = pconfig.inference_base_url

    command = (
        os.getenv("SPARK_COPILOT_ACP_COMMAND", "").strip()
        or os.getenv("COPILOT_CLI_PATH", "").strip()
        or "copilot"
    )
    raw_args = os.getenv("SPARK_COPILOT_ACP_ARGS", "").strip()
    args = shlex.split(raw_args) if raw_args else ["--acp", "--stdio"]
    resolved_command = shutil.which(command) if command else None
    if not resolved_command and not base_url.startswith("acp+tcp://"):
        raise AuthError(
            f"Could not find the Copilot CLI command '{command}'. "
            "Install GitHub Copilot CLI or set SPARK_COPILOT_ACP_COMMAND/COPILOT_CLI_PATH.",
            provider=provider_id,
            code="missing_copilot_cli",
        )

    return {
        "provider": provider_id,
        "api_key": "copilot-acp",
        "base_url": base_url.rstrip("/"),
        "command": resolved_command or command,
        "args": args,
        "source": "process",
    }


# =============================================================================
# CLI Commands — login / logout
# =============================================================================


def _update_config_for_provider(
    provider_id: str,
    inference_base_url: str,
    default_model: str | None = None,
) -> Path:
    """Update config.yaml and auth.json to reflect the active provider.

    When *default_model* is provided the function also writes it as the
    ``model.default`` value.  This prevents a race condition where the
    gateway (which re-reads config per-message) picks up the new provider
    before the caller has finished model selection, resulting in a
    mismatched model/provider (e.g. ``anthropic/claude-opus-4.6`` sent to
    MiniMax's API).
    """
    # Set active_provider in auth.json so auto-resolution picks this provider
    with _auth_store_lock():
        auth_store = _load_auth_store()
        auth_store["active_provider"] = provider_id
        _save_auth_store(auth_store)

    # Update config.yaml model section
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    config = read_raw_config()

    current_model = config.get("model")
    if isinstance(current_model, dict):
        model_cfg = dict(current_model)
    elif isinstance(current_model, str) and current_model.strip():
        model_cfg = {"default": current_model.strip()}
    else:
        model_cfg = {}

    model_cfg["provider"] = provider_id
    if inference_base_url and inference_base_url.strip():
        model_cfg["base_url"] = inference_base_url.rstrip("/")
    else:
        # Clear stale base_url to prevent contamination when switching providers
        model_cfg.pop("base_url", None)

    # When switching to a non-OpenRouter provider, ensure model.default is
    # valid for the new provider.  An OpenRouter-formatted name like
    # "anthropic/claude-opus-4.6" will fail on direct-API providers.
    if default_model:
        cur_default = model_cfg.get("default", "")
        if not cur_default or "/" in cur_default:
            model_cfg["default"] = default_model

    config["model"] = model_cfg

    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return config_path


def _reset_config_provider() -> Path:
    """Reset config.yaml provider back to auto after logout."""
    config_path = get_config_path()
    if not config_path.exists():
        return config_path

    config = read_raw_config()
    if not config:
        return config_path

    model = config.get("model")
    if isinstance(model, dict):
        model["provider"] = "auto"
        if "base_url" in model:
            model["base_url"] = OPENROUTER_BASE_URL
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    return config_path


def _prompt_model_selection(
    model_ids: list[str],
    current_model: str = "",
    pricing: dict[str, dict[str, str]] | None = None,
    unavailable_models: list[str] | None = None,
    portal_url: str = "",
) -> str | None:
    """Interactive model selection. Puts current_model first with a marker. Returns chosen model ID or None.

    If *pricing* is provided (``{model_id: {prompt, completion}}``), a compact
    price indicator is shown next to each model in aligned columns.

    If *unavailable_models* is provided, those models are shown grayed out
    and unselectable, with an upgrade link to *portal_url*.
    """
    from spark_cli.models import _format_price_per_mtok

    _unavailable = unavailable_models or []

    # Reorder: current model first, then the rest (deduplicated)
    ordered = []
    if current_model and current_model in model_ids:
        ordered.append(current_model)
    for mid in model_ids:
        if mid not in ordered:
            ordered.append(mid)

    # All models for column-width computation (selectable + unavailable)
    all_models = list(ordered) + list(_unavailable)

    # Column-aligned labels when pricing is available
    has_pricing = bool(pricing and any(pricing.get(m) for m in all_models))
    name_col = max((len(m) for m in all_models), default=0) + 2 if has_pricing else 0

    # Pre-compute formatted prices and dynamic column widths
    _price_cache: dict[str, tuple[str, str, str]] = {}
    price_col = 3  # minimum width
    cache_col = 0  # only set if any model has cache pricing
    has_cache = False
    if has_pricing:
        for mid in all_models:
            p = pricing.get(mid)  # type: ignore[union-attr]
            if p:
                inp = _format_price_per_mtok(p.get("prompt", ""))
                out = _format_price_per_mtok(p.get("completion", ""))
                cache_read = p.get("input_cache_read", "")
                cache = _format_price_per_mtok(cache_read) if cache_read else ""
                if cache:
                    has_cache = True
            else:
                inp, out, cache = "", "", ""
            _price_cache[mid] = (inp, out, cache)
            price_col = max(price_col, len(inp), len(out))
            cache_col = max(cache_col, len(cache))
        if has_cache:
            cache_col = max(cache_col, 5)  # minimum: "Cache" header

    def _label(mid):
        if has_pricing:
            inp, out, cache = _price_cache.get(mid, ("", "", ""))
            price_part = f" {inp:>{price_col}}  {out:>{price_col}}"
            if has_cache:
                price_part += f"  {cache:>{cache_col}}"
            base = f"{mid:<{name_col}}{price_part}"
        else:
            base = mid
        if mid == current_model:
            base += "  ← currently in use"
        return base

    # Default cursor on the current model (index 0 if it was reordered to top)
    default_idx = 0

    # Build a pricing header hint for the menu title
    menu_title = "Select default model:"
    _slot = get_model_routing_slot_selection()
    if _slot == "smart":
        menu_title = "Select default model (SMART — complex / coding tasks):"
    elif _slot == "fast":
        menu_title = "Select default model (FAST — general / simple requests):"
    if has_pricing:
        # Align the header with the model column.
        # Each choice is "  {label}" (2 spaces) and simple_term_menu prepends
        # a 3-char cursor region ("-> " or "   "), so content starts at col 5.
        pad = " " * 5
        header = f"\n{pad}{'':>{name_col}} {'In':>{price_col}}  {'Out':>{price_col}}"
        if has_cache:
            header += f"  {'Cache':>{cache_col}}"
        menu_title += header + "  /Mtok"

    # ANSI escape for dim text
    _DIM = "\033[2m"
    _RESET = "\033[0m"

    # Try arrow-key menu first, fall back to number input
    try:
        from simple_term_menu import TerminalMenu

        choices = [f"  {_label(mid)}" for mid in ordered]
        choices.append("  Enter custom model name")
        choices.append("  Skip (keep current)")

        # Print the unavailable block BEFORE the menu via regular print().
        # simple_term_menu pads title lines to terminal width (causes wrapping),
        # so we keep the title minimal and use stdout for the static block.
        # clear_screen=False means our printed output stays visible above.
        _upgrade_url = (portal_url or "").rstrip("/")
        if _unavailable:
            print(menu_title)
            print()
            for mid in _unavailable:
                print(f"{_DIM}     {_label(mid)}{_RESET}")
            print()
            print(f"{_DIM}  ── Upgrade at {_upgrade_url} for paid models ──{_RESET}")
            print()
            _slot_u = get_model_routing_slot_selection()
            if _slot_u == "smart":
                effective_title = "Available free models (SMART):"
            elif _slot_u == "fast":
                effective_title = "Available free models (FAST):"
            else:
                effective_title = "Available free models:"
        else:
            effective_title = menu_title

        menu = TerminalMenu(
            choices,
            cursor_index=default_idx,
            menu_cursor="-> ",
            menu_cursor_style=("fg_green", "bold"),
            menu_highlight_style=("fg_green",),
            cycle_cursor=True,
            clear_screen=False,
            title=effective_title,
        )
        idx = menu.show()
        from spark_cli.curses_ui import flush_stdin

        flush_stdin()
        if idx is None:
            return None
        print()
        if idx < len(ordered):
            return ordered[idx]
        elif idx == len(ordered):
            custom = input("Enter model name: ").strip()
            return custom if custom else None
        return None
    except (ImportError, NotImplementedError, OSError, subprocess.SubprocessError):
        pass

    # Fallback: numbered list
    print(menu_title)
    num_width = len(str(len(ordered) + 2))
    for i, mid in enumerate(ordered, 1):
        print(f"  {i:>{num_width}}. {_label(mid)}")
    n = len(ordered)
    print(f"  {n + 1:>{num_width}}. Enter custom model name")
    print(f"  {n + 2:>{num_width}}. Skip (keep current)")

    if _unavailable:
        _upgrade_url = (portal_url or "").rstrip("/")
        print()
        print(
            f"  {_DIM}── Unavailable models (requires paid tier — upgrade at {_upgrade_url}) ──{_RESET}"
        )
        for mid in _unavailable:
            print(f"  {'':>{num_width}}  {_DIM}{_label(mid)}{_RESET}")
    print()

    while True:
        try:
            choice = input(f"Choice [1-{n + 2}] (default: skip): ").strip()
            if not choice:
                return None
            idx = int(choice)
            if 1 <= idx <= n:
                return ordered[idx - 1]
            elif idx == n + 1:
                custom = input("Enter model name: ").strip()
                return custom if custom else None
            elif idx == n + 2:
                return None
            print(f"Please enter 1-{n + 2}")
        except ValueError:
            print("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            return None


def _save_model_choice(model_id: str) -> None:
    """Save the selected model to config.yaml (single source of truth).

    The model is stored in config.yaml only — NOT in .env.  This avoids
    conflicts in multi-agent setups where env vars would stomp each other.
    """
    from spark_cli.model_config import write_global_model_config

    write_global_model_config(model=model_id)


def login_command(args) -> None:
    """Deprecated: use 'spark model' or 'spark setup' instead."""
    print("The 'spark login' command has been removed.")
    print("Use 'spark auth' to manage credentials,")
    print("'spark model' to select a provider, or 'spark setup' for full setup.")
    raise SystemExit(0)


def _login_openai_codex(args, pconfig: ProviderConfig) -> None:
    """OpenAI Codex login via device code flow. Tokens stored in ~/.spark/auth.json."""

    # Check for existing Spark-owned credentials
    try:
        existing = resolve_codex_runtime_credentials()
        # Verify the resolved token is actually usable (not expired).
        # resolve_codex_runtime_credentials attempts refresh, so if we get
        # here the token should be valid — but double-check before telling
        # the user "Login successful!".
        _resolved_key = existing.get("api_key", "")
        if (
            isinstance(_resolved_key, str)
            and _resolved_key
            and not _codex_access_token_is_expiring(_resolved_key, 60)
        ):
            print("Existing Codex credentials found in Spark auth store.")
            try:
                reuse = input("Use existing credentials? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                reuse = "y"
            if reuse in ("", "y", "yes"):
                config_path = _update_config_for_provider(
                    "openai-codex", existing.get("base_url", DEFAULT_CODEX_BASE_URL)
                )
                print()
                print("Login successful!")
                print(f"  Config updated: {config_path} (model.provider=openai-codex)")
                return
        else:
            print("Existing Codex credentials are expired. Starting fresh login...")
    except AuthError:
        pass

    # Check for existing Codex CLI tokens we can import
    cli_tokens = _import_codex_cli_tokens()
    if cli_tokens:
        print("Found existing Codex CLI credentials at ~/.codex/auth.json")
        print(
            "Spark will create its own session to avoid conflicts with Codex CLI / VS Code."
        )
        try:
            do_import = (
                input(
                    "Import these credentials? (a separate login is recommended) [y/N]: "
                )
                .strip()
                .lower()
            )
        except (EOFError, KeyboardInterrupt):
            do_import = "n"
        if do_import in ("y", "yes"):
            _save_codex_tokens(cli_tokens)
            base_url = (
                os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
                or DEFAULT_CODEX_BASE_URL
            )
            config_path = _update_config_for_provider("openai-codex", base_url)
            print()
            print("Credentials imported. Note: if Codex CLI refreshes its token,")
            print("Spark will keep working independently with its own session.")
            print(f"  Config updated: {config_path} (model.provider=openai-codex)")
            return

    # Run a fresh device code flow — Spark gets its own OAuth session
    print()
    print("Signing in to OpenAI Codex...")
    print("(Spark creates its own session — won't affect Codex CLI or VS Code)")
    print()

    creds = _codex_device_code_login()

    # Save tokens to Spark auth store
    _save_codex_tokens(creds["tokens"], creds.get("last_refresh"))
    config_path = _update_config_for_provider(
        "openai-codex", creds.get("base_url", DEFAULT_CODEX_BASE_URL)
    )
    print()
    print("Login successful!")
    from core.spark_constants import display_spark_home as _dhh

    print(f"  Auth state: {_dhh()}/auth.json")
    print(f"  Config updated: {config_path} (model.provider=openai-codex)")


def _codex_device_code_login() -> dict[str, Any]:
    """Run the OpenAI device code login flow and return credentials dict."""
    import time as _time

    cli_creds = _codex_cli_device_code_login()
    if cli_creds is not None:
        return cli_creds

    issuer = "https://auth.openai.com"
    client_id = CODEX_OAUTH_CLIENT_ID

    # Step 1: Request device code
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                f"{issuer}/api/accounts/deviceauth/usercode",
                json={"client_id": client_id},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise AuthError(
            f"Failed to request device code: {exc}",
            provider="openai-codex",
            code="device_code_request_failed",
        )

    if resp.status_code != 200:
        raise AuthError(
            f"Device code request returned status {resp.status_code}.",
            provider="openai-codex",
            code="device_code_request_error",
        )

    device_data = resp.json()
    user_code = device_data.get("user_code", "")
    device_auth_id = device_data.get("device_auth_id", "")
    poll_interval = max(3, int(device_data.get("interval", "5")))

    if not user_code or not device_auth_id:
        raise AuthError(
            "Device code response missing required fields.",
            provider="openai-codex",
            code="device_code_incomplete",
        )

    # Step 2: Show user the code
    print("To continue, follow these steps:\n")
    print("  1. Open this URL in your browser:")
    print(f"     \033[94m{issuer}/codex/device\033[0m\n")
    print("  2. Enter this code:")
    print(f"     \033[94m{user_code}\033[0m\n")
    hint = _codex_user_code_hint(user_code)
    if hint:
        print(f"     {hint}\n")
    print("Waiting for sign-in... (press Ctrl+C to cancel)")

    # Step 3: Poll for authorization code
    max_wait = 15 * 60  # 15 minutes
    start = _time.monotonic()
    code_resp = None

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while _time.monotonic() - start < max_wait:
                _time.sleep(poll_interval)
                poll_resp = client.post(
                    f"{issuer}/api/accounts/deviceauth/token",
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )

                if poll_resp.status_code == 200:
                    code_resp = poll_resp.json()
                    break
                elif poll_resp.status_code in (403, 404):
                    continue  # User hasn't completed login yet
                else:
                    raise AuthError(
                        f"Device auth polling returned status {poll_resp.status_code}.",
                        provider="openai-codex",
                        code="device_code_poll_error",
                    )
    except KeyboardInterrupt:
        print("\nLogin cancelled.")
        raise SystemExit(130)

    if code_resp is None:
        raise AuthError(
            "Login timed out after 15 minutes.",
            provider="openai-codex",
            code="device_code_timeout",
        )

    # Step 4: Exchange authorization code for tokens
    authorization_code = code_resp.get("authorization_code", "")
    code_verifier = code_resp.get("code_verifier", "")
    redirect_uri = f"{issuer}/deviceauth/callback"

    if not authorization_code or not code_verifier:
        raise AuthError(
            "Device auth response missing authorization_code or code_verifier.",
            provider="openai-codex",
            code="device_code_incomplete_exchange",
        )

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                CODEX_OAUTH_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise AuthError(
            f"Token exchange failed: {exc}",
            provider="openai-codex",
            code="token_exchange_failed",
        )

    if token_resp.status_code != 200:
        raise AuthError(
            f"Token exchange returned status {token_resp.status_code}.",
            provider="openai-codex",
            code="token_exchange_error",
        )

    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    id_token = tokens.get("id_token", "")

    if not access_token:
        raise AuthError(
            "Token exchange did not return an access_token.",
            provider="openai-codex",
            code="token_exchange_no_access_token",
        )

    # Return tokens for the caller to persist (no longer writes to ~/.codex/)
    base_url = (
        os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )

    return {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
        },
        "base_url": base_url,
        "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "auth_mode": "chatgpt",
        "source": "device-code",
    }


def _codex_user_code_hint(user_code: str) -> str:
    """Clarify visually ambiguous device-code characters for manual entry."""
    hints = []
    for char in user_code.replace("-", ""):
        if char == "0":
            hints.append("0 = zero")
        elif char == "O":
            hints.append("O = capital letter O")
        elif char == "I":
            hints.append("I = capital letter I")
        elif char == "1":
            hints.append("1 = one")
    deduped = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
    if not deduped:
        return ""
    return "Character hint: " + ", ".join(deduped)


def _codex_cli_device_code_login() -> dict[str, Any] | None:
    """Use official Codex CLI device auth when installed, then import tokens."""
    if os.getenv("SPARK_CODEX_DEVICE_AUTH_IMPL", "").strip().lower() == "inline":
        return None
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return None

    print("Using official Codex CLI device-auth flow...")
    print("(Set SPARK_CODEX_DEVICE_AUTH_IMPL=inline to use Spark's built-in fallback.)")
    try:
        completed = subprocess.run([codex_bin, "login", "--device-auth"], check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Failed to run Codex CLI device auth: %s", exc)
        return None

    if completed.returncode != 0:
        raise AuthError(
            f"Codex CLI device-auth failed with exit status {completed.returncode}.",
            provider="openai-codex",
            code="codex_cli_device_auth_failed",
            relogin_required=True,
        )

    tokens = _import_codex_cli_tokens()
    if not tokens:
        raise AuthError(
            "Codex CLI login completed, but Spark could not import tokens from ~/.codex/auth.json. "
            "Configure Codex CLI to use file-backed credentials or run with SPARK_CODEX_DEVICE_AUTH_IMPL=inline.",
            provider="openai-codex",
            code="codex_cli_tokens_missing",
            relogin_required=True,
        )

    base_url = (
        os.getenv("SPARK_CODEX_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_CODEX_BASE_URL
    )
    return {
        "tokens": tokens,
        "base_url": base_url,
        "last_refresh": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "auth_mode": "chatgpt",
        "source": "codex-cli-device-auth",
    }




def logout_command(args) -> None:
    """Clear auth state for a provider."""
    provider_id = getattr(args, "provider", None)

    if provider_id and provider_id not in PROVIDER_REGISTRY:
        print(f"Unknown provider: {provider_id}")
        raise SystemExit(1)

    active = get_active_provider()
    target = provider_id or active

    if not target:
        print("No provider is currently logged in.")
        return

    provider_name = (
        PROVIDER_REGISTRY[target].name if target in PROVIDER_REGISTRY else target
    )

    if clear_provider_auth(target):
        _reset_config_provider()
        print(f"Logged out of {provider_name}.")
        if os.getenv("OPENROUTER_API_KEY"):
            print("Spark will use OpenRouter for inference.")
        else:
            print("Run `spark model` or configure an API key to use Spark.")
    else:
        print(f"No auth state found for {provider_name}.")
