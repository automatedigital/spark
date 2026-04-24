---
sidebar_position: 4
title: "Toolsets Reference"
description: "Reference for Spark core, composite, platform, and dynamic toolsets"
---

# Toolsets Reference

Toolsets are named bundles of tools. Enabling a toolset makes all its tools available to the agent. They're the primary way to control what the agent can do across different platforms, sessions, and tasks.

## Three Kinds of Toolsets

- **Core** — One logical group of related tools. For example, `file` bundles `read_file`, `write_file`, `patch`, and `search_files`.
- **Composite** — Combines multiple core toolsets for a common scenario. For example, `debugging` bundles file, terminal, and web tools.
- **Platform** — The complete tool configuration for a specific deployment context. For example, `spark-cli` is the default for interactive CLI sessions.

## Configure Toolsets

### For a single session

```bash
spark chat --toolsets web,file,terminal
spark chat --toolsets debugging        # composite — expands to file + terminal + web
spark chat --toolsets all              # everything
```

### Per platform in config.yaml

```yaml
toolsets:
  - spark-cli          # default for CLI
  # - spark-telegram   # override for Telegram gateway
```

### Interactively

```bash
spark tools                            # curses UI to enable/disable per platform
```

Or while in a session:

```
/tools list
/tools disable browser
/tools enable rl
```

## Core Toolsets

| Toolset | Tools | Purpose |
|---------|-------|---------|
| `browser` | `browser_back`, `browser_click`, `browser_console`, `browser_get_images`, `browser_navigate`, `browser_press`, `browser_scroll`, `browser_snapshot`, `browser_type`, `browser_vision`, `web_search` | Full browser automation. Includes `web_search` as a fallback for quick lookups. |
| `clarify` | `clarify` | Ask the user a question when the agent needs input before proceeding. |
| `code_execution` | `execute_code` | Run Python scripts that call Spark tools programmatically. |
| `cronjob` | `cronjob` | Schedule and manage recurring tasks. |
| `delegation` | `delegate_task` | Spawn isolated subagent instances for parallel work. |
| `file` | `patch`, `read_file`, `search_files`, `write_file` | File reading, writing, searching, and editing. |
| `homeassistant` | `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services` | Smart home control via Home Assistant. Only available when `HASS_TOKEN` is set. |
| `image_gen` | `image_generate` | Text-to-image generation via FAL.ai. |
| `memory` | `memory` | Persistent cross-session memory management. |
| `messaging` | `send_message` | Send messages to other platforms (Telegram, Discord, etc.) from within a session. |
| `moa` | `mixture_of_agents` | Multi-model consensus via Mixture of Agents. |
| `rl` | `rl_check_status`, `rl_edit_config`, `rl_get_current_config`, `rl_get_results`, `rl_list_environments`, `rl_list_runs`, `rl_select_environment`, `rl_start_training`, `rl_stop_training`, `rl_test_inference` | RL training environment management (Atropos). |
| `search` | `web_search` | Web search without page extraction. |
| `session_search` | `session_search` | Search past conversation sessions. |
| `skills` | `skill_manage`, `skill_view`, `skills_list` | Skill creation, editing, and browsing. |
| `terminal` | `process`, `terminal` | Shell command execution and background process management. |
| `todo` | `todo` | Task list management within a session. |
| `tts` | `text_to_speech` | Text-to-speech audio generation. |
| `vision` | `vision_analyze` | Image analysis via vision-capable models. |
| `web` | `web_extract`, `web_search` | Web search and page content extraction. |

## Composite Toolsets

Shorthands that expand to multiple core toolsets:

| Toolset | Expands to | Best for |
|---------|-----------|----------|
| `debugging` | `patch`, `process`, `read_file`, `search_files`, `terminal`, `web_extract`, `web_search`, `write_file` | Debug sessions — file access, terminal, and web research without browser or delegation overhead. |
| `safe` | `image_generate`, `vision_analyze`, `web_extract`, `web_search` | Read-only research and media generation. No file writes, no terminal, no code execution. Good for constrained or untrusted environments. |

## Platform Toolsets

Platform toolsets define the complete tool configuration for a deployment target. Most messaging platforms match `spark-cli`:

| Toolset | Differences from `spark-cli` |
|---------|-------------------------------|
| `spark-cli` | Full toolset — all 36 tools including `clarify`. Default for interactive CLI sessions. |
| `spark-acp` | Drops `clarify`, `cronjob`, `image_generate`, `send_message`, `text_to_speech`, and Home Assistant tools. Focused on coding tasks in IDE context. |
| `spark-api-server` | Drops `clarify`, `send_message`, and `text_to_speech`. Keeps everything else — suitable for programmatic access where user interaction isn't possible. |
| `spark-telegram` | Same as `spark-cli`. |
| `spark-discord` | Same as `spark-cli`. |
| `spark-slack` | Same as `spark-cli`. |
| `spark-whatsapp` | Same as `spark-cli`. |
| `spark-signal` | Same as `spark-cli`. |
| `spark-matrix` | Same as `spark-cli`. |
| `spark-mattermost` | Same as `spark-cli`. |
| `spark-email` | Same as `spark-cli`. |
| `spark-sms` | Same as `spark-cli`. |
| `spark-dingtalk` | Same as `spark-cli`. |
| `spark-feishu` | Same as `spark-cli`. |
| `spark-wecom` | Same as `spark-cli`. |
| `spark-wecom-callback` | WeCom callback toolset — enterprise self-built app messaging (full access). |
| `spark-weixin` | Same as `spark-cli`. |
| `spark-bluebubbles` | Same as `spark-cli`. |
| `spark-qqbot` | Same as `spark-cli`. |
| `spark-homeassistant` | Same as `spark-cli`. |
| `spark-webhook` | Same as `spark-cli`. |
| `spark-gateway` | Union of all messaging platform toolsets. Used internally when the gateway needs the broadest possible tool set. |

## Dynamic Toolsets

### MCP server toolsets

Each configured MCP server generates a `mcp-<server>` toolset at runtime. Configure a `github` server and you get a `mcp-github` toolset containing every tool that server exposes.

```yaml
# config.yaml
mcp:
  servers:
    github:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-github"]
```

Reference `mcp-github` in `--toolsets` or platform configs just like any built-in toolset.

### Plugin toolsets

Plugins register their own toolsets via `ctx.register_tool()` during initialization. They appear alongside built-in toolsets and work the same way — enable or disable them with `/tools` or in `config.yaml`.

### Custom toolsets

Define project-specific bundles in `config.yaml`:

```yaml
toolsets:
  - spark-cli
custom_toolsets:
  data-science:
    - file
    - terminal
    - code_execution
    - web
    - vision
```

### Wildcards

- `all` or `*` — expands to every registered toolset: built-in, dynamic, and plugin

## Fine-Grained Tool Control

`spark tools` opens a curses-based UI for toggling individual tools on or off per platform. This operates at the tool level (finer than toolsets) and persists to `config.yaml`. Disabled tools are filtered out even if their parent toolset is enabled.

See also: [Tools Reference](./tools-reference.md) for the complete list of individual tools and their parameters.
