"""Config loading + persistence for the Spark CLI.

Extracted from core/cli/__init__.py (Phase 3). Owns ``CLI_CONFIG`` — the process
config dict, loaded once at import and read across the CLI. De-globalized here so
extracted submodules and SparkCLI mixins can share it via a single import rather
than reaching into the cli package namespace.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict

import yaml

from core.spark_constants import get_spark_home

logger = logging.getLogger(__name__)

_spark_home = get_spark_home()


def load_cli_config() -> Dict[str, Any]:
    """
    Load CLI configuration from config files.

    Config lookup order:
    1. ~/"spark/config.yaml (user config - preferred)
    2. ./cli-config.yaml (project config - fallback)

    Environment variables take precedence over config file values.
    Returns default values if no config file exists.
    """
    # Check user config first ({SPARK_HOME}/config.yaml)
    user_config_path = _spark_home / "config.yaml"
    project_config_path = Path(__file__).parent / "cli-config.yaml"

    # Use user config if it exists, otherwise project config
    if user_config_path.exists():
        config_path = user_config_path
    else:
        config_path = project_config_path

    # Default configuration
    defaults = {
        "model": {
            "default": "",
            "base_url": "",
            "provider": "auto",
        },
        "terminal": {
            "env_type": "local",
            "cwd": ".",  # "." is resolved to os.getcwd() at runtime
            "timeout": 60,
            "lifetime_seconds": 300,
            "docker_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "docker_forward_env": [],
            "singularity_image": "docker://nikolaik/python-nodejs:python3.11-nodejs20",
            "modal_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "daytona_image": "nikolaik/python-nodejs:python3.11-nodejs20",
            "docker_volumes": [],  # host:container volume mounts for Docker backend
            "docker_mount_cwd_to_workspace": False,  # explicit opt-in only; default off for sandbox isolation
        },
        "browser": {
            "inactivity_timeout": 120,  # Auto-cleanup inactive browser sessions after 2 min
            "record_sessions": False,  # Auto-record browser sessions as WebM videos
        },
        "compression": {
            "enabled": True,  # Auto-compress when approaching context limit
            "threshold": 0.50,  # Compress at 50% of model's context limit
        },
        "smart_model_routing": {
            "enabled": False,
            "max_simple_chars": 160,
            "max_simple_words": 28,
            "cheap_model": {},
        },
        "agent": {
            "max_turns": 90,  # Default max tool-calling iterations (shared with subagents)
            "verbose": False,
            "system_prompt": "",
            "prefill_messages_file": "",
            "reasoning_effort": "",
            "service_tier": "",
            "personalities": {
                "helpful": "You are a helpful, friendly AI assistant.",
                "concise": "You are a concise assistant. Keep responses brief and to the point.",
                "technical": "You are a technical expert. Provide detailed, accurate technical information.",
                "creative": "You are a creative assistant. Think outside the box and offer innovative solutions.",
                "teacher": "You are a patient teacher. Explain concepts clearly with examples.",
                "kawaii": "You are a kawaii assistant. Keep a warm, upbeat tone and use playful language without special symbols.",
                "catgirl": "You are Neko-chan, an anime catgirl AI assistant, nya~! Add 'nya' and cat-like expressions to your speech. Use kaomoji like (=^･ω･^=) and ฅ^•ﻌ•^ฅ. Be playful and curious like a cat, nya~!",
                "pirate": "Arrr! Ye be talkin' to Captain Spark, the most tech-savvy pirate to sail the digital seas! Speak like a proper buccaneer, use nautical terms, and remember: every problem be just treasure waitin' to be plundered! Yo ho ho!",
                "shakespeare": "Hark! Thou speakest with an assistant most versed in the bardic arts. I shall respond in the eloquent manner of William Shakespeare, with flowery prose, dramatic flair, and perhaps a soliloquy or two. What light through yonder terminal breaks?",
                "surfer": "Duuude! You're chatting with the chillest AI on the web, bro! Everything's gonna be totally rad. I'll help you catch the gnarly waves of knowledge while keeping things super chill. Cowabunga!",
                "noir": "The rain hammered against the terminal like regrets on a guilty conscience. They call me Spark - I solve problems, find answers, dig up the truth that hides in the shadows of your codebase. In this city of silicon and secrets, everyone's got something to hide. What's your story, pal?",
                "uwu": "hewwo! i'm your fwiendwy assistant uwu~ i wiww twy my best to hewp you! *nuzzles your code* OwO what's this? wet me take a wook! i pwomise to be vewy hewpful >w<",
                "philosopher": "Greetings, seeker of wisdom. I am an assistant who contemplates the deeper meaning behind every query. Let us examine not just the 'how' but the 'why' of your questions. Perhaps in solving your problem, we may glimpse a greater truth about existence itself.",
                "hype": "YOOO LET'S GOOOO!!! I am SO PUMPED to help you today! Every question is AMAZING and we're gonna CRUSH IT together! This is gonna be LEGENDARY! ARE YOU READY?! LET'S DO THIS!",
            },
        },
        "display": {
            "compact": False,
            "resume_display": "full",
            "show_reasoning": False,
            "streaming": True,
            "busy_input_mode": "interrupt",
            "skin": "default",
        },
        "clarify": {
            "timeout": 120,  # Seconds to wait for a clarify answer before auto-proceeding
        },
        "code_execution": {
            "timeout": 300,  # Max seconds a sandbox script can run before being killed (5 min)
            "max_tool_calls": 50,  # Max RPC tool calls per execution
        },
        "auxiliary": {
            "vision": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
            },
            "web_extract": {
                "provider": "auto",
                "model": "",
                "base_url": "",
                "api_key": "",
            },
        },
        "delegation": {
            "max_iterations": 45,  # Max tool-calling turns per child agent
            "default_toolsets": [
                "terminal",
                "file",
                "web",
            ],  # Default toolsets for subagents
            "model": "",  # Subagent model override (empty = inherit parent model)
            "provider": "",  # Subagent provider override (empty = inherit parent provider)
            "base_url": "",  # Direct OpenAI-compatible endpoint for subagents
            "api_key": "",  # API key for delegation.base_url (falls back to OPENAI_API_KEY)
        },
    }

    # Track whether the config file explicitly set terminal config.
    # When using defaults (no config file / no terminal section), we should NOT
    # overwrite env vars that were already set by .env -- only a user's config
    # file should be authoritative.
    _file_has_terminal_config = False

    # Load from file if exists
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}

            _file_has_terminal_config = "terminal" in file_config

            # Handle model config - can be string (new format) or dict (old format)
            if "model" in file_config:
                if isinstance(file_config["model"], str):
                    # New format: model is just a string, convert to dict structure
                    defaults["model"]["default"] = file_config["model"]
                elif isinstance(file_config["model"], dict):
                    # Old format: model is a dict with default/base_url
                    defaults["model"].update(file_config["model"])
                    # If the user config sets model.model but not model.default,
                    # promote model.model to model.default so the user's explicit
                    # choice isn't shadowed by the hardcoded default.  Without this,
                    # profile configs that only set "model:" (not "default:") silently
                    # fall back to claude-opus because the merge preserves the
                    # hardcoded default and SparkCLI.__init__ checks "default" first.
                    if (
                        "model" in file_config["model"]
                        and "default" not in file_config["model"]
                    ):
                        defaults["model"]["default"] = file_config["model"]["model"]

            # Legacy root-level provider/base_url fallback.
            # Some users (or old code) put provider: / base_url: at the
            # config root instead of inside the model: section.  These are
            # only used as a FALLBACK when model.provider / model.base_url
            # is not already set - never as an override.  The canonical
            # location is model.provider (written by `spark model`).
            if not defaults["model"].get("provider"):
                root_provider = file_config.get("provider")
                if root_provider:
                    defaults["model"]["provider"] = root_provider
            if not defaults["model"].get("base_url"):
                root_base_url = file_config.get("base_url")
                if root_base_url:
                    defaults["model"]["base_url"] = root_base_url

            # Deep merge file_config into defaults.
            # First: merge keys that exist in both (deep-merge dicts, overwrite scalars)
            for key in defaults:
                if key == "model":
                    continue  # Already handled above
                if key in file_config:
                    if isinstance(defaults[key], dict) and isinstance(
                        file_config[key], dict
                    ):
                        defaults[key].update(file_config[key])
                    else:
                        defaults[key] = file_config[key]

            # Second: carry over keys from file_config that aren't in defaults
            # (e.g. platform_toolsets, provider_routing, memory, honcho, etc.)
            for key in file_config:
                if key not in defaults and key != "model":
                    defaults[key] = file_config[key]

            # Handle legacy root-level max_turns (backwards compat) - copy to
            # agent.max_turns whenever the nested key is missing.
            agent_file_config = file_config.get("agent")
            if "max_turns" in file_config and not (
                isinstance(agent_file_config, dict)
                and agent_file_config.get("max_turns") is not None
            ):
                defaults["agent"]["max_turns"] = file_config["max_turns"]
        except Exception as e:
            logger.warning("Failed to load cli-config.yaml: %s", e)

    # Expand ${ENV_VAR} references in config values before bridging to env vars.
    from spark_cli.config import _expand_env_vars

    defaults = _expand_env_vars(defaults)

    # Apply terminal config to environment variables (so terminal_tool picks them up)
    terminal_config = defaults.get("terminal", {})

    # Normalize config key: the new config system (spark_cli/config.py) and all
    # documentation use "backend", the legacy cli-config.yaml uses "env_type".
    # Accept both, with "backend" taking precedence (it's the documented key).
    if "backend" in terminal_config:
        terminal_config["env_type"] = terminal_config["backend"]

    # Handle special cwd values: "." or "auto" means use current working directory.
    # Only resolve to the host's CWD for the local backend where the host
    # filesystem is directly accessible.  For ALL remote/container backends
    # (ssh, docker, modal, singularity), the host path doesn't exist on the
    # target -- remove the key so terminal_tool.py uses its per-backend default.
    if terminal_config.get("cwd") in (".", "auto", "cwd"):
        effective_backend = terminal_config.get("env_type", "local")
        if effective_backend == "local":
            terminal_config["cwd"] = os.getcwd()
            defaults["terminal"]["cwd"] = terminal_config["cwd"]
        else:
            # Remove so TERMINAL_CWD stays unset → tool picks backend default
            terminal_config.pop("cwd", None)

    env_mappings = {
        "env_type": "TERMINAL_ENV",
        "cwd": "TERMINAL_CWD",
        "timeout": "TERMINAL_TIMEOUT",
        "lifetime_seconds": "TERMINAL_LIFETIME_SECONDS",
        "docker_image": "TERMINAL_DOCKER_IMAGE",
        "docker_forward_env": "TERMINAL_DOCKER_FORWARD_ENV",
        "singularity_image": "TERMINAL_SINGULARITY_IMAGE",
        "modal_image": "TERMINAL_MODAL_IMAGE",
        "daytona_image": "TERMINAL_DAYTONA_IMAGE",
        # SSH config
        "ssh_host": "TERMINAL_SSH_HOST",
        "ssh_user": "TERMINAL_SSH_USER",
        "ssh_port": "TERMINAL_SSH_PORT",
        "ssh_key": "TERMINAL_SSH_KEY",
        # Container resource config (docker, singularity, modal, daytona -- ignored for local/ssh)
        "container_cpu": "TERMINAL_CONTAINER_CPU",
        "container_memory": "TERMINAL_CONTAINER_MEMORY",
        "container_disk": "TERMINAL_CONTAINER_DISK",
        "container_persistent": "TERMINAL_CONTAINER_PERSISTENT",
        "docker_volumes": "TERMINAL_DOCKER_VOLUMES",
        "docker_mount_cwd_to_workspace": "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE",
        "sandbox_dir": "TERMINAL_SANDBOX_DIR",
        # Persistent shell (non-local backends)
        "persistent_shell": "TERMINAL_PERSISTENT_SHELL",
        # Sudo support (works with all backends)
        "sudo_password": "SUDO_PASSWORD",
    }

    # Apply config values to env vars so terminal_tool picks them up.
    # If the config file explicitly has a [terminal] section, those values are
    # authoritative and override any .env settings.  When using defaults only
    # (no config file or no terminal section), don't overwrite env vars that
    # were already set by .env -- the user's .env is the fallback source.
    for config_key, env_var in env_mappings.items():
        if config_key in terminal_config:
            if _file_has_terminal_config or env_var not in os.environ:
                val = terminal_config[config_key]
                if isinstance(val, list):
                    import json

                    os.environ[env_var] = json.dumps(val)
                else:
                    os.environ[env_var] = str(val)

    # Apply browser config to environment variables
    browser_config = defaults.get("browser", {})
    browser_env_mappings = {
        "inactivity_timeout": "BROWSER_INACTIVITY_TIMEOUT",
    }

    for config_key, env_var in browser_env_mappings.items():
        if config_key in browser_config:
            os.environ[env_var] = str(browser_config[config_key])

    # Apply auxiliary model/direct-endpoint overrides to environment variables.
    # Vision and web_extract each have their own provider/model/base_url/api_key tuple.
    # Compression config is read directly from config.yaml by run_agent.py and
    # auxiliary_client.py - no env var bridging needed.
    # Only set env vars for non-empty / non-default values so auto-detection
    # still works.
    auxiliary_config = defaults.get("auxiliary", {})
    auxiliary_task_env = {
        # config key → env var mapping
        "vision": {
            "provider": "AUXILIARY_VISION_PROVIDER",
            "model": "AUXILIARY_VISION_MODEL",
            "base_url": "AUXILIARY_VISION_BASE_URL",
            "api_key": "AUXILIARY_VISION_API_KEY",
        },
        "web_extract": {
            "provider": "AUXILIARY_WEB_EXTRACT_PROVIDER",
            "model": "AUXILIARY_WEB_EXTRACT_MODEL",
            "base_url": "AUXILIARY_WEB_EXTRACT_BASE_URL",
            "api_key": "AUXILIARY_WEB_EXTRACT_API_KEY",
        },
        "approval": {
            "provider": "AUXILIARY_APPROVAL_PROVIDER",
            "model": "AUXILIARY_APPROVAL_MODEL",
            "base_url": "AUXILIARY_APPROVAL_BASE_URL",
            "api_key": "AUXILIARY_APPROVAL_API_KEY",
        },
    }

    for task_key, env_map in auxiliary_task_env.items():
        task_cfg = auxiliary_config.get(task_key, {})
        if not isinstance(task_cfg, dict):
            continue
        prov = str(task_cfg.get("provider", "")).strip()
        model = str(task_cfg.get("model", "")).strip()
        base_url = str(task_cfg.get("base_url", "")).strip()
        api_key = str(task_cfg.get("api_key", "")).strip()
        if prov and prov != "auto":
            os.environ[env_map["provider"]] = prov
        if model:
            os.environ[env_map["model"]] = model
        if base_url:
            os.environ[env_map["base_url"]] = base_url
        if api_key:
            os.environ[env_map["api_key"]] = api_key

    # Security settings
    security_config = defaults.get("security", {})
    if isinstance(security_config, dict):
        redact = security_config.get("redact_secrets")
        if redact is not None:
            os.environ["SPARK_REDACT_SECRETS"] = str(redact).lower()

    return defaults


# Loaded once at import; read across the CLI.
CLI_CONFIG = load_cli_config()


def save_config_value(key_path: str, value: any) -> bool:
    """
    Save a value to the active config file at the specified key path.

    Respects the same lookup order as load_cli_config():
    1. ~/"spark/config.yaml (user config - preferred, used if it exists)
    2. ./cli-config.yaml (project config - fallback)

    Args:
        key_path: Dot-separated path like "agent.system_prompt"
        value: Value to save

    Returns:
        True if successful, False otherwise
    """
    # Use the same precedence as load_cli_config: user config first, then project config.
    # Always call get_spark_home() here (not the module-level cache) so that a changed
    # SPARK_HOME env var (e.g. during tests or profile switches) is respected.
    from core.spark_constants import get_spark_home as _get_spark_home
    user_config_path = _get_spark_home() / "config.yaml"
    project_config_path = Path(__file__).parent / "cli-config.yaml"
    config_path = user_config_path if user_config_path.exists() else project_config_path

    try:
        # Ensure parent directory exists (for ~/"spark/config.yaml on first use)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}

        # Navigate to the key and set value
        keys = key_path.split(".")
        current = config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

        # Save back atomically - write to temp file + fsync + os.replace
        # so an interrupt never leaves config.yaml truncated or empty.
        from core.utils import atomic_yaml_write

        atomic_yaml_write(config_path, config)

        # Enforce owner-only permissions on config files (contain API keys)
        try:
            os.chmod(config_path, 0o600)
        except (OSError, NotImplementedError):
            pass

        return True
    except Exception as e:
        logger.error("Failed to save config: %s", e)
        return False
