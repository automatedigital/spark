"""Model picker + /model switch handling for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). The curses model picker, model-switch
pipeline, and provider listing. Combined into SparkCLI via inheritance.
"""

from __future__ import annotations

from core.cli import _looks_like_slash_command  # defined before this import; no cycle
from core.cli.render import _cprint


class _ModelMixin:
    def _run_curses_picker(
        self, title: str, items: list[str], default_index: int = 0
    ) -> int | None:
        """Run curses_single_select via run_in_terminal so prompt_toolkit handles terminal ownership cleanly."""
        import threading
        from spark_cli.curses_ui import curses_single_select

        result = [None]

        def _pick():
            result[0] = curses_single_select(title, items, default_index=default_index)

        # run_in_terminal requires an asyncio event loop - only exists in the
        # main prompt_toolkit thread.  If we're in a background thread (e.g.
        # process_loop), fall back to direct curses call.
        in_main_thread = threading.current_thread() is threading.main_thread()

        if self._app and in_main_thread:
            from prompt_toolkit.application import run_in_terminal

            was_visible = self._status_bar_visible
            self._status_bar_visible = False
            self._app.invalidate()
            try:
                run_in_terminal(_pick)
            finally:
                self._status_bar_visible = was_visible
                self._app.invalidate()
        else:
            _pick()

        return result[0]

    def _prompt_text_input(self, prompt_text: str) -> str | None:
        """Prompt for free-text input safely inside or outside prompt_toolkit."""
        result = [None]

        def _ask():
            try:
                result[0] = input(prompt_text).strip() or None
            except (KeyboardInterrupt, EOFError):
                pass

        if self._app:
            from prompt_toolkit.application import run_in_terminal

            was_visible = self._status_bar_visible
            self._status_bar_visible = False
            self._app.invalidate()
            try:
                run_in_terminal(_ask)
            finally:
                self._status_bar_visible = was_visible
                self._app.invalidate()
        else:
            _ask()
        return result[0]

    def _open_model_picker(
        self,
        providers: list,
        current_model: str,
        current_provider: str,
        user_provs=None,
        custom_provs=None,
    ) -> None:
        """Open prompt_toolkit-native /model picker modal."""
        self._capture_modal_input_snapshot()
        default_idx = next(
            (i for i, p in enumerate(providers) if p.get("is_current")), 0
        )
        self._model_picker_state = {
            "stage": "provider",
            "providers": providers,
            "selected": default_idx,
            "current_model": current_model,
            "current_provider": current_provider,
            "user_provs": user_provs,
            "custom_provs": custom_provs,
        }
        self._invalidate(min_interval=0.0)

    def _close_model_picker(self) -> None:
        self._model_picker_state = None
        self._restore_modal_input_snapshot()
        self._invalidate(min_interval=0.0)

    def _apply_model_switch_result(self, result, persist_global: bool) -> None:
        if not result.success:
            _cprint(f"  ERROR: {result.error_message}")
            return

        old_model = self.model
        self.model = result.new_model
        self.provider = result.target_provider
        self.requested_provider = result.target_provider
        if result.api_key:
            self.api_key = result.api_key
            self._explicit_api_key = result.api_key
        if result.base_url:
            self.base_url = result.base_url
            self._explicit_base_url = result.base_url
        if result.api_mode:
            self.api_mode = result.api_mode

        if self.agent is not None:
            try:
                self.agent.switch_model(
                    new_model=result.new_model,
                    new_provider=result.target_provider,
                    api_key=result.api_key,
                    base_url=result.base_url,
                    api_mode=result.api_mode,
                )
            except Exception as exc:
                _cprint(
                    f"  WARN Agent swap failed ({exc}); change applied to next session."
                )

        self._pending_model_switch_note = (
            f"[Note: model was just switched from {old_model} to {result.new_model} "
            f"via {result.provider_label or result.target_provider}. "
            f"Adjust your self-identification accordingly.]"
        )

        provider_label = result.provider_label or result.target_provider
        _cprint(f"  OK: Model switched: {result.new_model}")
        _cprint(f"    Provider: {provider_label}")

        mi = result.model_info
        if mi:
            if mi.context_window:
                _cprint(f"    Context: {mi.context_window:,} tokens")
            if mi.max_output:
                _cprint(f"    Max output: {mi.max_output:,} tokens")
            if mi.has_cost_data():
                _cprint(f"    Cost: {mi.format_cost()}")
            _cprint(f"    Capabilities: {mi.format_capabilities()}")
        else:
            try:
                from agent.model_metadata import get_model_context_length

                ctx = get_model_context_length(
                    result.new_model,
                    base_url=result.base_url or self.base_url,
                    api_key=result.api_key or self.api_key,
                    provider=result.target_provider,
                )
                _cprint(f"    Context: {ctx:,} tokens")
            except Exception:
                pass

        cache_enabled = (
            "openrouter" in (result.base_url or "").lower()
            and "claude" in result.new_model.lower()
        ) or result.api_mode == "anthropic_messages"
        if cache_enabled:
            _cprint("    Prompt caching: enabled")
        if result.warning_message:
            _cprint(f"    WARN {result.warning_message}")
        try:
            from spark_cli.model_config import write_model_switch_result

            write_model_switch_result(result)
            _cprint("    Saved to config.yaml")
        except Exception as exc:
            _cprint(f"    WARN Failed to save model config: {exc}")

    def _handle_model_picker_selection(self, persist_global: bool = False) -> None:
        state = self._model_picker_state
        if not state:
            return
        selected = state.get("selected", 0)
        stage = state.get("stage")
        if stage == "provider":
            providers = state.get("providers") or []
            if selected >= len(providers):
                self._close_model_picker()
                return
            provider_data = providers[selected]
            model_list = []
            try:
                from spark_cli.models import provider_model_ids

                live = provider_model_ids(provider_data["slug"])
                if live:
                    model_list = live
            except Exception:
                pass
            if not model_list:
                model_list = provider_data.get("models", [])
            state["stage"] = "model"
            state["provider_data"] = provider_data
            state["model_list"] = model_list
            state["selected"] = 0
            self._invalidate(min_interval=0.0)
            return
        if stage == "model":
            provider_data = state.get("provider_data") or {}
            model_list = state.get("model_list") or []
            back_idx = len(model_list)
            cancel_idx = len(model_list) + 1
            if selected == back_idx:
                state["stage"] = "provider"
                state["selected"] = next(
                    (
                        i
                        for i, p in enumerate(state.get("providers") or [])
                        if p.get("slug") == provider_data.get("slug")
                    ),
                    0,
                )
                self._invalidate(min_interval=0.0)
                return
            if selected >= cancel_idx:
                self._close_model_picker()
                return
            if selected < len(model_list):
                from spark_cli.model_switch import switch_model

                chosen_model = model_list[selected]
                result = switch_model(
                    raw_input=chosen_model,
                    current_provider=self.provider or "",
                    current_model=self.model or "",
                    current_base_url=self.base_url or "",
                    current_api_key=self.api_key or "",
                    is_global=True,
                    explicit_provider=provider_data.get("slug"),
                    user_providers=state.get("user_provs"),
                    custom_providers=state.get("custom_provs"),
                )
                self._close_model_picker()
                self._apply_model_switch_result(result, persist_global)
                return
            self._close_model_picker()

    def _handle_model_switch(self, cmd_original: str):
        """Handle /model command - switch the universal model config.

        Supports:
          /model                              - show current model + usage hints
          /model <name>                       - switch and persist to config.yaml
          /model <name> --global              - accepted for compatibility
          /model <name> --provider <provider> - switch provider + model
          /model --provider <provider>        - switch to provider, auto-detect model
        """
        from spark_cli.model_switch import (
            switch_model,
            parse_model_flags,
            list_authenticated_providers,
        )
        from spark_cli.providers import get_label

        # Parse args from the original command
        parts = cmd_original.split(None, 1)  # split off '/model'
        raw_args = parts[1].strip() if len(parts) > 1 else ""

        # Parse --provider and --global flags
        model_input, explicit_provider, persist_global = parse_model_flags(raw_args)

        user_provs = None
        custom_provs = None

        # No args at all: ask Simple / Multi-model, then open the picker
        if not model_input and not explicit_provider:
            # ── Mode selection ────────────────────────────────────────────────
            try:
                from spark_cli.config import load_config as _lc

                _routing_cfg = _lc().get("smart_model_routing") or {}
                _multi_active = bool(_routing_cfg.get("enabled"))
            except Exception:
                _multi_active = False

            _mode_default = 1 if _multi_active else 0
            _mode_idx = self._run_curses_picker(
                "Model configuration mode:",
                [
                    "Simple          — one model for all requests",
                    "Multi-model     — fast model for general, smart model for complex",
                ],
                default_index=_mode_default,
            )
            if _mode_idx is None:
                return  # cancelled

            if _mode_idx == 1:
                # Multi-model: run the terminal-based two-pass wizard
                def _run_multi():
                    from spark_cli.main import _do_multi_model_selection
                    _do_multi_model_selection()
                    # Re-read effective model from config and apply to CLI state
                    try:
                        from spark_cli.config import load_config as _lc2
                        _cfg = _lc2()
                        _m = _cfg.get("model") or {}
                        if isinstance(_m, dict) and _m.get("default"):
                            self.model = _m["default"]
                        if isinstance(_m, dict) and _m.get("provider"):
                            self.provider = _m["provider"]
                        self._smart_model_routing = _cfg.get("smart_model_routing") or {}
                        self.agent = None  # force re-init with new route
                    except Exception:
                        pass

                if self._app:
                    from prompt_toolkit.application import run_in_terminal
                    was_visible = self._status_bar_visible
                    self._status_bar_visible = False
                    self._app.invalidate()
                    try:
                        run_in_terminal(_run_multi)
                    finally:
                        self._status_bar_visible = was_visible
                        self._app.invalidate()
                else:
                    _run_multi()
                return

            else:
                # Simple mode: disable multi-model routing if it was on
                try:
                    from spark_cli.config import load_config as _lc3, save_config as _sc
                    _cfg = _lc3()
                    _smr = _cfg.get("smart_model_routing")
                    if isinstance(_smr, dict) and _smr.get("enabled"):
                        _smr["enabled"] = False
                        _sc(_cfg)
                        self._smart_model_routing = _cfg.get("smart_model_routing") or {}
                        self.agent = None
                        _cprint("  Multi-model routing disabled.")
                except Exception:
                    pass

            model_display = self.model or "unknown"
            provider_display = get_label(self.provider) if self.provider else "unknown"

            user_provs = None
            custom_provs = None
            try:
                from spark_cli.config import (
                    get_compatible_custom_providers,
                    load_config,
                )

                cfg = load_config()
                user_provs = cfg.get("providers")
                custom_provs = get_compatible_custom_providers(cfg)
            except Exception:
                pass

            try:
                providers = list_authenticated_providers(
                    current_provider=self.provider or "",
                    user_providers=user_provs,
                    custom_providers=custom_provs,
                    max_models=50,
                )
            except Exception:
                providers = []

            if not providers:
                _cprint("  No authenticated providers found.")
                _cprint("")
                _cprint("  /model <name>                        switch model")
                _cprint("  /model --provider <slug>             switch provider")
                return

            self._open_model_picker(
                providers,
                model_display,
                provider_display,
                user_provs=user_provs,
                custom_provs=custom_provs,
            )
            return

        # Perform the switch
        result = switch_model(
            raw_input=model_input,
            current_provider=self.provider or "",
            current_model=self.model or "",
            current_base_url=self.base_url or "",
            current_api_key=self.api_key or "",
            is_global=True,
            explicit_provider=explicit_provider,
            user_providers=user_provs,
            custom_providers=custom_provs,
        )

        if not result.success:
            _cprint(f"  ERROR: {result.error_message}")
            return

        # Apply to CLI state.
        # Update requested_provider so _ensure_runtime_credentials() doesn't
        # overwrite the switch on the next turn (it re-resolves from this).
        old_model = self.model
        self.model = result.new_model
        self.provider = result.target_provider
        self.requested_provider = result.target_provider
        if result.api_key:
            self.api_key = result.api_key
            self._explicit_api_key = result.api_key
        if result.base_url:
            self.base_url = result.base_url
            self._explicit_base_url = result.base_url
        if result.api_mode:
            self.api_mode = result.api_mode

        # Apply to running agent (in-place swap)
        if self.agent is not None:
            try:
                self.agent.switch_model(
                    new_model=result.new_model,
                    new_provider=result.target_provider,
                    api_key=result.api_key,
                    base_url=result.base_url,
                    api_mode=result.api_mode,
                )
            except Exception as exc:
                _cprint(
                    f"  WARN Agent swap failed ({exc}); change applied to next session."
                )

        # Store a note to prepend to the next user message so the model
        # knows a switch occurred (avoids injecting system messages mid-history
        # which breaks providers and prompt caching).
        self._pending_model_switch_note = (
            f"[Note: model was just switched from {old_model} to {result.new_model} "
            f"via {result.provider_label or result.target_provider}. "
            f"Adjust your self-identification accordingly.]"
        )

        # Display confirmation with full metadata
        provider_label = result.provider_label or result.target_provider
        _cprint(f"  OK: Model switched: {result.new_model}")
        _cprint(f"    Provider: {provider_label}")

        # Rich metadata from models.dev
        mi = result.model_info
        if mi:
            if mi.context_window:
                _cprint(f"    Context: {mi.context_window:,} tokens")
            if mi.max_output:
                _cprint(f"    Max output: {mi.max_output:,} tokens")
            if mi.has_cost_data():
                _cprint(f"    Cost: {mi.format_cost()}")
            _cprint(f"    Capabilities: {mi.format_capabilities()}")
        else:
            # Fallback to old context length lookup
            try:
                from agent.model_metadata import get_model_context_length

                ctx = get_model_context_length(
                    result.new_model,
                    base_url=result.base_url or self.base_url,
                    api_key=result.api_key or self.api_key,
                    provider=result.target_provider,
                )
                _cprint(f"    Context: {ctx:,} tokens")
            except Exception:
                pass

        # Cache notice
        cache_enabled = (
            "openrouter" in (result.base_url or "").lower()
            and "claude" in result.new_model.lower()
        ) or result.api_mode == "anthropic_messages"
        if cache_enabled:
            _cprint("    Prompt caching: enabled")

        # Warning from validation
        if result.warning_message:
            _cprint(f"    WARN {result.warning_message}")

        # Persistence
        try:
            from spark_cli.model_config import write_model_switch_result

            write_model_switch_result(result)
            _cprint("    Saved to config.yaml")
        except Exception as exc:
            _cprint(f"    WARN Failed to save model config: {exc}")

    def _should_handle_model_command_inline(
        self, text: str, has_images: bool = False
    ) -> bool:
        """Return True when /model should be handled immediately on the UI thread."""
        if not text or has_images or not _looks_like_slash_command(text):
            return False
        try:
            from spark_cli.commands import resolve_command

            base = text.split(None, 1)[0].lower().lstrip("/")
            cmd = resolve_command(base)
            return bool(cmd and cmd.name == "model")
        except Exception:
            return False

    def _show_model_and_providers(self):
        """Show current model + provider and list all authenticated providers.

        Shows current model + provider, then lists all authenticated
        providers with their available models.
        """
        from spark_cli.models import (
            curated_models_for_provider,
            list_available_providers,
            normalize_provider,
            _PROVIDER_LABELS,
            get_pricing_for_provider,
            format_model_pricing_table,
        )
        from spark_cli.auth import resolve_provider as _resolve_provider

        # Resolve current provider
        raw_provider = normalize_provider(self.provider)
        if raw_provider == "auto":
            try:
                current = _resolve_provider(
                    self.requested_provider,
                    explicit_api_key=self._explicit_api_key,
                    explicit_base_url=self._explicit_base_url,
                )
            except Exception:
                current = "openrouter"
        else:
            current = raw_provider
        current_label = _PROVIDER_LABELS.get(current, current)

        print(f"\n  Current: {self.model} via {current_label}")
        print()

        # Show all authenticated providers with their models
        providers = list_available_providers()
        authed = [p for p in providers if p["authenticated"]]
        unauthed = [p for p in providers if not p["authenticated"]]

        if authed:
            print("  Authenticated providers & models:")
            for p in authed:
                is_active = p["id"] == current
                marker = " ← active" if is_active else ""
                print(f"    [{p['id']}]{marker}")
                curated = curated_models_for_provider(p["id"])
                pricing_map = (
                    get_pricing_for_provider(p["id"])
                    if p["id"] == "openrouter"
                    else {}
                )
                if curated and pricing_map:
                    cur_model = self.model if is_active else ""
                    for line in format_model_pricing_table(
                        curated, pricing_map, current_model=cur_model
                    ):
                        print(line)
                elif curated:
                    for mid, desc in curated:
                        current_marker = (
                            " ← current" if (is_active and mid == self.model) else ""
                        )
                        print(f"      {mid}{current_marker}")
                elif p["id"] == "custom":
                    from spark_cli.models import _get_custom_base_url

                    custom_url = _get_custom_base_url()
                    if custom_url:
                        print(f"      endpoint: {custom_url}")
                    if is_active:
                        print(f"      model: {self.model} ← current")
                    print("      (use spark model to change)")
                else:
                    print("      (use spark model to change)")
                print()

        if unauthed:
            names = ", ".join(p["label"] for p in unauthed)
            print(f"  Not configured: {names}")
            print("  Run: spark setup")
            print()

        print("  To change model or provider, use: spark model")

