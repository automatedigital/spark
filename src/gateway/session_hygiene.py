"""Gateway transcript hygiene before agent turns."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from gateway.session import SessionEntry, SessionSource

HYGIENE_THRESHOLD_PCT = 0.85
HYGIENE_WARN_THRESHOLD_PCT = 0.95
HYGIENE_HARD_MESSAGE_LIMIT = 400


def compression_threshold(context_length: int) -> int:
    """Return the token threshold where gateway hygiene should compress."""
    return int(context_length * HYGIENE_THRESHOLD_PCT)


def warning_threshold(context_length: int) -> int:
    """Return the post-compression warning threshold."""
    return int(context_length * HYGIENE_WARN_THRESHOLD_PCT)


def needs_hygiene_compression(
    *,
    message_count: int,
    token_count: int,
    context_length: int,
) -> bool:
    """Return whether a transcript should be compressed before an agent turn."""
    return (
        token_count >= compression_threshold(context_length)
        or message_count >= HYGIENE_HARD_MESSAGE_LIMIT
    )


async def run_session_hygiene(
    runner: Any,
    *,
    source: SessionSource,
    session_key: str,
    session_entry: SessionEntry,
    history: list[dict[str, Any]],
    spark_home: Path,
    logger: Any,
) -> list[dict[str, Any]]:
    """Compress pathologically large gateway transcripts before agent startup."""
    if not history or len(history) < 4:
        return history

    from agent.model_metadata import (
        estimate_messages_tokens_rough,
        get_model_context_length,
    )

    hyg_model = "anthropic/claude-sonnet-4.6"
    hyg_compression_enabled = True
    hyg_config_context_length = None
    hyg_provider = None
    hyg_base_url = None
    hyg_api_key = None
    hyg_data: dict[str, Any] = {}
    try:
        hyg_cfg_path = spark_home / "config.yaml"
        if hyg_cfg_path.exists():
            import yaml as hyg_yaml

            with open(hyg_cfg_path, encoding="utf-8") as hyg_f:
                loaded = hyg_yaml.safe_load(hyg_f) or {}
                hyg_data = loaded if isinstance(loaded, dict) else {}

            model_cfg = hyg_data.get("model", {})
            if isinstance(model_cfg, str):
                hyg_model = model_cfg
            elif isinstance(model_cfg, dict):
                hyg_model = model_cfg.get("default") or model_cfg.get("model") or hyg_model
                raw_ctx = model_cfg.get("context_length")
                if raw_ctx is not None:
                    try:
                        hyg_config_context_length = int(raw_ctx)
                    except (TypeError, ValueError):
                        pass
                hyg_provider = model_cfg.get("provider") or None
                hyg_base_url = model_cfg.get("base_url") or None

            comp_cfg = hyg_data.get("compression", {})
            if isinstance(comp_cfg, dict):
                hyg_compression_enabled = str(
                    comp_cfg.get("enabled", True)
                ).lower() in ("true", "1", "yes")

        try:
            hyg_model, hyg_runtime = runner._resolve_session_agent_runtime(
                source=source,
                session_key=session_key,
                user_config=hyg_data if isinstance(hyg_data, dict) else None,
            )
            hyg_provider = hyg_runtime.get("provider") or hyg_provider
            hyg_base_url = hyg_runtime.get("base_url") or hyg_base_url
            hyg_api_key = hyg_runtime.get("api_key") or hyg_api_key
        except Exception:
            pass

        if hyg_config_context_length is None and hyg_base_url:
            try:
                try:
                    from spark_cli.config import get_compatible_custom_providers as gw_gcp

                    hyg_custom_providers = gw_gcp(hyg_data)
                except Exception:
                    hyg_custom_providers = hyg_data.get("custom_providers")
                    if not isinstance(hyg_custom_providers, list):
                        hyg_custom_providers = []
                for custom_provider in hyg_custom_providers:
                    if not isinstance(custom_provider, dict):
                        continue
                    custom_provider_url = (custom_provider.get("base_url") or "").rstrip("/")
                    if custom_provider_url and custom_provider_url == hyg_base_url.rstrip("/"):
                        custom_provider_models = custom_provider.get("models", {})
                        if isinstance(custom_provider_models, dict):
                            custom_model_cfg = custom_provider_models.get(hyg_model, {})
                            if isinstance(custom_model_cfg, dict):
                                custom_provider_ctx = custom_model_cfg.get("context_length")
                                if custom_provider_ctx is not None:
                                    hyg_config_context_length = int(custom_provider_ctx)
                        break
            except (TypeError, ValueError):
                pass
    except Exception:
        pass

    if not hyg_compression_enabled:
        return history

    hyg_context_length = get_model_context_length(
        hyg_model,
        base_url=hyg_base_url or "",
        api_key=hyg_api_key or "",
        config_context_length=hyg_config_context_length,
        provider=hyg_provider or "",
    )
    compress_token_threshold = compression_threshold(hyg_context_length)
    warn_token_threshold = warning_threshold(hyg_context_length)

    msg_count = len(history)
    stored_tokens = session_entry.last_prompt_tokens
    if stored_tokens > 0:
        approx_tokens = stored_tokens
        token_source = "actual"
    else:
        approx_tokens = estimate_messages_tokens_rough(history)
        token_source = "estimated"

    if not needs_hygiene_compression(
        message_count=msg_count,
        token_count=approx_tokens,
        context_length=hyg_context_length,
    ):
        return history

    logger.info(
        "Session hygiene: %s messages, ~%s tokens (%s) — auto-compressing "
        "(threshold: %s%% of %s = %s tokens)",
        msg_count,
        f"{approx_tokens:,}",
        token_source,
        int(HYGIENE_THRESHOLD_PCT * 100),
        f"{hyg_context_length:,}",
        f"{compress_token_threshold:,}",
    )

    try:
        from core.run_agent import AIAgent

        hyg_model, hyg_runtime = runner._resolve_session_agent_runtime(
            source=source,
            session_key=session_key,
            user_config=hyg_data if isinstance(hyg_data, dict) else None,
        )
        if not hyg_runtime.get("api_key"):
            return history

        hyg_msgs = [
            {"role": message.get("role"), "content": message.get("content")}
            for message in history
            if message.get("role") in ("user", "assistant") and message.get("content")
        ]

        if len(hyg_msgs) < 4:
            return history

        hyg_agent = AIAgent(
            **hyg_runtime,
            model=hyg_model,
            max_iterations=4,
            quiet_mode=True,
            enabled_toolsets=["memory"],
            session_id=session_entry.session_id,
        )
        hyg_agent._print_fn = lambda *a, **kw: None

        loop = asyncio.get_event_loop()
        compressed, _ = await loop.run_in_executor(
            None,
            lambda: hyg_agent._compress_context(
                hyg_msgs,
                "",
                approx_tokens=approx_tokens,
            ),
        )

        hyg_new_sid = hyg_agent.session_id
        if hyg_new_sid != session_entry.session_id:
            session_entry.session_id = hyg_new_sid
            runner.session_store._save()

        runner.session_store.rewrite_transcript(session_entry.session_id, compressed)
        session_entry.last_prompt_tokens = 0
        new_tokens = estimate_messages_tokens_rough(compressed)

        logger.info(
            "Session hygiene: compressed %s → %s msgs, ~%s → ~%s tokens",
            msg_count,
            len(compressed),
            f"{approx_tokens:,}",
            f"{new_tokens:,}",
        )

        if new_tokens >= warn_token_threshold:
            logger.warning(
                "Session hygiene: still ~%s tokens after compression",
                f"{new_tokens:,}",
            )

        return compressed
    except Exception as exc:
        logger.warning("Session hygiene auto-compress failed: %s", exc)
        return history
