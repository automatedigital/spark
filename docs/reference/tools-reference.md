---
sidebar_position: 3
title: "Built-in Tools Reference"
description: "Authoritative reference for Spark built-in tools, grouped by toolset"
---

# Built-in Tools Reference

Every built-in tool Spark ships with, organized by toolset. 47 tools total. Availability depends on your platform, configured credentials, and enabled toolsets.

**Quick counts:** 10 browser tools, 4 file tools, 10 RL tools, 4 Home Assistant tools, 2 terminal tools, 2 web tools, and 15 standalone tools across other toolsets.

:::tip MCP Tools
Spark can also load tools dynamically from MCP servers. MCP tools appear with a server-name prefix (e.g., `github_create_issue` for the `github` MCP server). See [MCP Integration](/docs/tools/mcp) for configuration.
:::

## `browser` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `browser_back` | Navigate back to the previous page in browser history. Requires `browser_navigate` first. | — |
| `browser_click` | Click an element by its ref ID from the snapshot (e.g., `@e5`). Ref IDs appear in square brackets in snapshot output. Requires `browser_navigate` and `browser_snapshot` first. | — |
| `browser_console` | Get browser console output and JavaScript errors from the current page. Returns `console.log`/`warn`/`error`/`info` messages and uncaught JS exceptions. Useful for detecting silent errors, failed API calls, and application warnings. | — |
| `browser_get_images` | List all images on the current page with URLs and alt text. Good for finding images to pass to the vision tool. Requires `browser_navigate` first. | — |
| `browser_navigate` | Load a URL in the browser. Initializes the session. Must be called before other browser tools. For simple information retrieval, prefer `web_search` or `web_extract` — they're faster and cheaper. Use browser tools when you need interactive control. | — |
| `browser_press` | Press a keyboard key. Useful for submitting forms (Enter), navigation (Tab), or keyboard shortcuts. Requires `browser_navigate` first. | — |
| `browser_scroll` | Scroll the page up or down to reveal content outside the current viewport. Requires `browser_navigate` first. | — |
| `browser_snapshot` | Get a text-based accessibility tree snapshot of the current page. Returns interactive elements with ref IDs (`@e1`, `@e2`, etc.) for use with `browser_click` and `browser_type`. `full=false` (default): compact view. `full=true`: complete tree. | — |
| `browser_type` | Type text into an input field by ref ID. Clears the field first, then types. Requires `browser_navigate` and `browser_snapshot` first. | — |
| `browser_vision` | Screenshot the current page and analyze it with vision AI. Use when you need to visually understand layout — especially for CAPTCHAs, visual verification challenges, or when the text snapshot is insufficient. | — |

## `clarify` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `clarify` | Ask the user a question when you need clarification, feedback, or a decision before proceeding. Two modes: **Multiple choice** — up to 4 choices, user picks or types their own via a 5th "Other" option. **Free text** — open-ended input. | — |

## `code_execution` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `execute_code` | Run a Python script that calls Spark tools programmatically. Use when you need 3+ tool calls with processing logic between them, need to filter large tool outputs before they enter context, or need conditional branching. | — |

## `cronjob` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `cronjob` | Unified scheduled-task manager. Use `action="create"`, `"list"`, `"update"`, `"pause"`, `"resume"`, `"run"`, or `"remove"` to manage jobs. Supports skill-backed jobs. Cron runs happen in fresh sessions with no current-chat context. | — |

## `delegation` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `delegate_task` | Spawn one or more subagents to work on tasks in isolated contexts. Each subagent gets its own conversation, terminal session, and toolset. Only the final summary is returned — intermediate tool results never enter your context window. | — |

## `file` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `patch` | Targeted find-and-replace edits in files. Use instead of `sed`/`awk`. Uses fuzzy matching (9 strategies) so minor whitespace differences won't break it. Returns a unified diff. Auto-runs syntax checks after edits. | — |
| `read_file` | Read a text file with line numbers and pagination. Use instead of `cat`/`head`/`tail`. Format: `LINE_NUM\|CONTENT`. Suggests similar filenames if the path isn't found. Use `offset` and `limit` for large files. | — |
| `search_files` | Search file contents or find files by name. Use instead of `grep`/`rg`/`find`/`ls`. Ripgrep-backed. Content search supports regex with line numbers; file search finds by name pattern. | — |
| `write_file` | Write content to a file, completely replacing existing content. Use instead of `echo`/cat heredoc. Creates parent directories automatically. **Overwrites the entire file** — use `patch` for targeted edits. | — |

## `homeassistant` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `ha_call_service` | Call a Home Assistant service to control a device. Use `ha_list_services` to discover available services and parameters per domain. | — |
| `ha_get_state` | Get the detailed state of a single Home Assistant entity, including all attributes (brightness, color, temperature, sensor readings, etc.). | — |
| `ha_list_entities` | List Home Assistant entities. Filter by domain (`light`, `switch`, `climate`, `sensor`, etc.) or by area name (`living room`, `kitchen`, etc.). | — |
| `ha_list_services` | List available Home Assistant services for device control. Shows what actions each device type supports and what parameters they accept. | — |

:::note
**Honcho tools** (`honcho_conclude`, `honcho_context`, `honcho_profile`, `honcho_search`) are no longer built-in. They're available via the Honcho memory provider plugin at `plugins/memory/honcho/`. See [Plugins](../automate/plugins.md) for installation.
:::

## `image_gen` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `image_generate` | Generate high-quality images from text prompts using the FLUX 2 Pro model with automatic 2x upscaling. Returns a single upscaled image URL. | `FAL_KEY` |

## `memory` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `memory` | Save important information to persistent memory that survives across sessions. Memory appears in your system prompt at session start — it's how the agent remembers things about you between conversations. | — |

## `messaging` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `send_message` | Send a message to a connected messaging platform, or list available targets. When sending to a specific channel or person (not just a platform name), call `send_message(action='list')` first to see available targets. | — |

## `moa` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `mixture_of_agents` | Route a hard problem through multiple frontier LLMs collaboratively. Makes 5 API calls (4 reference models + 1 aggregator) with maximum reasoning effort. Use sparingly — best for complex math, advanced algorithms, and genuinely hard problems. | `OPENROUTER_API_KEY` |

## `rl` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `rl_check_status` | Get status and metrics for a training run. Rate limited: 30-minute minimum between checks for the same run. Returns WandB metrics: step, state, reward_mean, loss, percent_correct. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_edit_config` | Update a configuration field. Use `rl_get_current_config()` first to see available fields for the selected environment. Infrastructure settings are fixed. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_get_current_config` | Get the current environment configuration. Returns only modifiable fields: group_size, max_token_length, total_steps, steps_per_eval, use_wandb, wandb_name, max_num_workers. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_get_results` | Get final results and metrics for a completed training run. Returns final metrics and the path to trained weights. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_list_environments` | List all available RL environments with names, paths, and descriptions. Read the `file_path` with file tools to understand how each environment works. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_list_runs` | List all training runs (active and completed) with their status. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_select_environment` | Select an RL environment for training. Loads the environment's default configuration. Follow up with `rl_get_current_config()` and `rl_edit_config()`. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_start_training` | Start a new RL training run with the current environment and config. Use `rl_edit_config()` to set group_size, batch_size, wandb_project before starting. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_stop_training` | Stop a running training job. Use when metrics look bad, training is stagnant, or you want to try different settings. | `TINKER_API_KEY`, `WANDB_API_KEY` |
| `rl_test_inference` | Quick inference test for any environment. Defaults: 3 steps x 16 completions = 48 rollouts per model, testing 3 models = 144 total. Tests environment loading, prompt construction, and inference. | `TINKER_API_KEY`, `WANDB_API_KEY` |

## `session_search` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `session_search` | Search your long-term memory of past conversations. Every past session is searchable. Use proactively when the user says "we did this before", "remember when", or "last time". | — |

## `skills` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `skill_manage` | Create, update, or delete skills. Skills are procedural memory — reusable approaches for recurring task types. New skills go to `~/.spark/skills/`. | — |
| `skill_view` | Load a skill's full content or access its linked files (references, templates, scripts). First call returns SKILL.md content plus a list of linked files. | — |
| `skills_list` | List available skills with name and description. Use `skill_view(name)` to load full content. | — |

## `terminal` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `process` | Manage background processes started with `terminal(background=true)`. Actions: `list`, `poll`, `log`, `wait`, `kill`, `write`. | — |
| `terminal` | Execute shell commands. Filesystem persists between calls. Set `background=true` for long-running servers. Set `notify_on_complete=true` (with `background=true`) to get a notification when the process finishes. Do NOT use `cat`/`head`/`tail` — use `read_file`. Do NOT use `grep`/`rg`/`find` — use `search_files`. | — |

## `todo` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `todo` | Manage your task list for the current session. Use for complex tasks with 3+ steps or when the user provides multiple tasks. Call with no parameters to read the current list. | — |

## `vision` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `vision_analyze` | Analyze images using AI vision. Returns a comprehensive description and answers a specific question about the image content. | — |

## `web` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `web_search` | Search the web and return up to 5 relevant results with titles, URLs, and descriptions. | `EXA_API_KEY` or `PARALLEL_API_KEY` or `FIRECRAWL_API_KEY` or `TAVILY_API_KEY` |
| `web_extract` | Extract content from a URL as markdown. Works with PDF URLs too — pass the link directly and it converts to markdown text. Pages under 5000 chars return full markdown; larger pages are LLM-summarized. | `EXA_API_KEY` or `PARALLEL_API_KEY` or `FIRECRAWL_API_KEY` or `TAVILY_API_KEY` |

## `tts` toolset

| Tool | Description | Requires |
|------|-------------|----------|
| `text_to_speech` | Convert text to speech audio. Returns a `MEDIA:` path the platform delivers as a voice message. On Telegram it plays as a voice bubble; on Discord/WhatsApp as an audio attachment. In CLI mode, saves to `~/voice-memos/`. | — |
