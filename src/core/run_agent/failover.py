"""Provider failover and recovery for AIAgent: fallback activation, credential-pool recovery, and dead-connection cleanup.

Extracted from run_agent/__init__.py. These methods are mixed into AIAgent and
use instance state resolved at runtime through the MRO, so this is a pure
relocation with no behaviour change.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.error_classifier import FailoverReason

logger = logging.getLogger(__name__)


class _FailoverMixin:
    def _cleanup_dead_connections(self) -> bool:
        """Detect and clean up dead TCP connections on the primary client.

        Inspects the httpx connection pool for sockets in unhealthy states
        (CLOSE-WAIT, errors).  If any are found, force-closes all sockets
        and rebuilds the primary client from scratch.

        Returns True if dead connections were found and cleaned up.
        """
        client = getattr(self, "client", None)
        if client is None:
            return False
        try:
            http_client = getattr(client, "_client", None)
            if http_client is None:
                return False
            transport = getattr(http_client, "_transport", None)
            if transport is None:
                return False
            pool = getattr(transport, "_pool", None)
            if pool is None:
                return False
            connections = (
                getattr(pool, "_connections", None)
                or getattr(pool, "_pool", None)
                or []
            )
            dead_count = 0
            for conn in list(connections):
                # Check for connections that are idle but have closed sockets
                stream = (
                    getattr(conn, "_network_stream", None)
                    or getattr(conn, "_stream", None)
                )
                if stream is None:
                    continue
                sock = getattr(stream, "_sock", None)
                if sock is None:
                    sock = getattr(stream, "stream", None)
                    if sock is not None:
                        sock = getattr(sock, "_sock", None)
                if sock is None:
                    continue
                # Probe socket health with a non-blocking recv peek
                import socket as _socket
                try:
                    sock.setblocking(False)
                    data = sock.recv(1, _socket.MSG_PEEK | _socket.MSG_DONTWAIT)
                    if data == b"":
                        dead_count += 1
                except BlockingIOError:
                    # No data available — socket is healthy
                    logger.debug("Ignored exception in _cleanup_dead_connections", exc_info=True)
                except OSError:
                    dead_count += 1
                finally:
                    try:
                        sock.setblocking(True)
                    except OSError:
                        logger.debug("Ignoring error in _cleanup_dead_connections()", exc_info=True)
            if dead_count > 0:
                logger.warning(
                    "Found %d dead connection(s) in client pool — rebuilding client",
                    dead_count,
                )
                self._replace_primary_openai_client(reason="dead_connection_cleanup")
                return True
        except Exception as exc:
            logger.debug("Dead connection check error: %s", exc)
        return False

    def _recover_with_credential_pool(
        self,
        *,
        status_code: int | None,
        has_retried_429: bool,
        classified_reason: FailoverReason | None = None,
        error_context: dict[str, Any] | None = None,
    ) -> tuple[bool, bool]:
        """Attempt credential recovery via pool rotation.

        Returns (recovered, has_retried_429).
        On rate limits: first occurrence retries same credential (sets flag True).
                        second consecutive failure rotates to next credential.
        On billing exhaustion: immediately rotates.
        On auth failures: attempts token refresh before rotating.

        `classified_reason` lets the recovery path honor the structured error
        classifier instead of relying only on raw HTTP codes. This matters for
        providers that surface billing/rate-limit/auth conditions under a
        different status code, such as Anthropic returning HTTP 400 for
        "out of extra usage".
        """
        pool = self._credential_pool
        if pool is None:
            return False, has_retried_429

        effective_reason = classified_reason
        if effective_reason is None:
            if status_code == 402:
                effective_reason = FailoverReason.billing
            elif status_code == 429:
                effective_reason = FailoverReason.rate_limit
            elif status_code == 401:
                effective_reason = FailoverReason.auth

        if effective_reason == FailoverReason.billing:
            rotate_status = status_code if status_code is not None else 402
            next_entry = pool.mark_exhausted_and_rotate(status_code=rotate_status, error_context=error_context)
            if next_entry is not None:
                logger.info(
                    "Credential %s (billing) — rotated to pool entry %s",
                    rotate_status,
                    getattr(next_entry, "id", "?"),
                )
                self._swap_credential(next_entry)
                return True, False
            return False, has_retried_429

        if effective_reason == FailoverReason.rate_limit:
            if not has_retried_429:
                return False, True
            rotate_status = status_code if status_code is not None else 429
            next_entry = pool.mark_exhausted_and_rotate(status_code=rotate_status, error_context=error_context)
            if next_entry is not None:
                logger.info(
                    "Credential %s (rate limit) — rotated to pool entry %s",
                    rotate_status,
                    getattr(next_entry, "id", "?"),
                )
                self._swap_credential(next_entry)
                return True, False
            return False, True

        if effective_reason == FailoverReason.auth:
            # A token refresh can "succeed" (return a new entry) yet still yield a
            # credential the provider rejects. Without a cap, that produces an
            # infinite refresh→retry→401 loop on the same pool entry. Bound the
            # number of consecutive refreshes before forcing a rotation.
            max_auth_refreshes = 3
            auth_refreshes = getattr(self, "_consecutive_auth_refreshes", 0)
            refreshed = pool.try_refresh_current() if auth_refreshes < max_auth_refreshes else None
            if refreshed is not None:
                self._consecutive_auth_refreshes = auth_refreshes + 1
                logger.info(f"Credential auth failure — refreshed pool entry {getattr(refreshed, 'id', '?')}")
                self._swap_credential(refreshed)
                return True, has_retried_429
            if auth_refreshes >= max_auth_refreshes:
                logger.warning(
                    "Credential auth failure — refresh budget (%d) exhausted; rotating to next credential",
                    max_auth_refreshes,
                )
            # Refresh failed or budget exhausted — rotate to next credential
            # instead of looping. Reset the budget for whatever entry comes next.
            # A failed refresh already marked the entry exhausted via try_refresh_current().
            self._consecutive_auth_refreshes = 0
            rotate_status = status_code if status_code is not None else 401
            next_entry = pool.mark_exhausted_and_rotate(status_code=rotate_status, error_context=error_context)
            if next_entry is not None:
                logger.info(
                    "Credential %s (auth refresh failed) — rotated to pool entry %s",
                    rotate_status,
                    getattr(next_entry, "id", "?"),
                )
                self._swap_credential(next_entry)
                return True, False

        return False, has_retried_429

    def _try_activate_fallback(self) -> bool:
        """Switch to the next fallback model/provider in the chain.

        Called when the current model is failing after retries.  Swaps the
        OpenAI client, model slug, and provider in-place so the retry loop
        can continue with the new backend.  Advances through the chain on
        each call; returns False when exhausted.

        Uses the centralized provider router (resolve_provider_client) for
        auth resolution and client construction — no duplicated provider→key
        mappings.
        """
        if self._fallback_index >= len(self._fallback_chain):
            return False

        fb = self._fallback_chain[self._fallback_index]
        self._fallback_index += 1
        fb_provider = (fb.get("provider") or "").strip().lower()
        fb_model = (fb.get("model") or "").strip()
        if not fb_provider or not fb_model:
            return self._try_activate_fallback()  # skip invalid, try next

        # Use centralized router for client construction.
        # raw_codex=True because the main agent needs direct responses.stream()
        # access for Codex providers.
        try:
            from agent.auxiliary_client import resolve_provider_client
            # Pass base_url and api_key from fallback config so custom
            # endpoints (e.g. Ollama Cloud) resolve correctly instead of
            # falling through to OpenRouter defaults.
            fb_base_url_hint = (fb.get("base_url") or "").strip() or None
            fb_api_key_hint = (fb.get("api_key") or "").strip() or None
            # For Ollama Cloud endpoints, pull OLLAMA_API_KEY from env
            # when no explicit key is in the fallback config.
            if fb_base_url_hint and "ollama.com" in fb_base_url_hint.lower() and not fb_api_key_hint:
                fb_api_key_hint = os.getenv("OLLAMA_API_KEY") or None
            fb_client, _resolved_fb_model = resolve_provider_client(
                fb_provider, model=fb_model, raw_codex=True,
                explicit_base_url=fb_base_url_hint,
                explicit_api_key=fb_api_key_hint)
            if fb_client is None:
                logging.warning(
                    "Fallback to %s failed: provider not configured",
                    fb_provider)
                return self._try_activate_fallback()  # try next in chain
            try:
                from spark_cli.model_normalize import normalize_model_for_provider

                fb_model = normalize_model_for_provider(fb_model, fb_provider)
            except Exception:
                logger.debug("Ignoring error in _try_activate_fallback()", exc_info=True)

            # Determine api_mode from provider / base URL / model
            fb_api_mode = "chat_completions"
            fb_base_url = str(fb_client.base_url)
            if fb_provider == "openai-codex":
                fb_api_mode = "codex_responses"
            elif fb_provider == "anthropic" or fb_base_url.rstrip("/").lower().endswith("/anthropic"):
                fb_api_mode = "anthropic_messages"
            elif self._is_direct_openai_url(fb_base_url):
                fb_api_mode = "codex_responses"
            elif self._model_requires_responses_api(fb_model):
                # GPT-5.x models need Responses API on every provider
                # (OpenRouter, Copilot, direct OpenAI, etc.)
                fb_api_mode = "codex_responses"

            old_model = self.model
            self.model = fb_model
            self.provider = fb_provider
            self.base_url = fb_base_url
            self.api_mode = fb_api_mode
            self._fallback_activated = True

            if fb_api_mode == "anthropic_messages":
                # Build native Anthropic client instead of using OpenAI client
                from agent.anthropic_adapter import (
                    _is_oauth_token,
                    build_anthropic_client,
                    resolve_anthropic_token,
                )
                effective_key = (fb_client.api_key or resolve_anthropic_token() or "") if fb_provider == "anthropic" else (fb_client.api_key or "")
                self.api_key = effective_key
                self._anthropic_api_key = effective_key
                self._anthropic_base_url = fb_base_url
                self._anthropic_client = build_anthropic_client(effective_key, self._anthropic_base_url)
                self._is_anthropic_oauth = _is_oauth_token(effective_key)
                self.client = None
                self._client_kwargs = {}
            else:
                # Swap OpenAI client and config in-place
                self.api_key = fb_client.api_key
                self.client = fb_client
                # Preserve provider-specific headers that
                # resolve_provider_client() may have baked into
                # fb_client via the default_headers kwarg.  The OpenAI
                # SDK stores these in _custom_headers.  Without this,
                # subsequent request-client rebuilds (via
                # _create_request_openai_client) drop the headers,
                # causing 403s from providers like Kimi Coding that
                # require a User-Agent sentinel.
                fb_headers = getattr(fb_client, "_custom_headers", None)
                if not fb_headers:
                    fb_headers = getattr(fb_client, "default_headers", None)
                self._client_kwargs = {
                    "api_key": fb_client.api_key,
                    "base_url": fb_base_url,
                    **({"default_headers": dict(fb_headers)} if fb_headers else {}),
                }

            # Re-evaluate prompt caching for the new provider/model
            is_native_anthropic = fb_api_mode == "anthropic_messages" and fb_provider == "anthropic"
            self._use_prompt_caching = (
                ("openrouter" in fb_base_url.lower() and "claude" in fb_model.lower())
                or is_native_anthropic
            )

            # Update context compressor limits for the fallback model.
            # Without this, compression decisions use the primary model's
            # context window (e.g. 200K) instead of the fallback's (e.g. 32K),
            # causing oversized sessions to overflow the fallback.
            if hasattr(self, 'context_compressor') and self.context_compressor:
                from agent.model_metadata import get_model_context_length
                fb_context_length = get_model_context_length(
                    self.model, base_url=self.base_url,
                    api_key=self.api_key, provider=self.provider,
                )
                self.context_compressor.update_model(
                    model=self.model,
                    context_length=fb_context_length,
                    base_url=self.base_url,
                    api_key=getattr(self, "api_key", ""),
                    provider=self.provider,
                )

            self._emit_status(
                f"🔄 Primary model failed — switching to fallback: "
                f"{fb_model} via {fb_provider}"
            )
            logging.info(
                "Fallback activated: %s → %s (%s)",
                old_model, fb_model, fb_provider,
            )
            return True
        except Exception as e:
            logging.error("Failed to activate fallback %s: %s", fb_model, e)
            return self._try_activate_fallback()  # try next in chain
