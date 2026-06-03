---
title: "Integrations"
sidebar_label: "Overview"
sidebar_position: 0
---

# Integrations

Spark connects to a wide surface area of external systems — AI providers, tool servers, editors, chat platforms, and more. Here's what's available and where to dig in.

## AI Providers & Routing

Pick your inference backend with `spark model`, or set it directly in `config.yaml`. Mix and match.

| Topic | What you get |
|-------|-------------|
| **[AI Providers](../providers/routing.md)** | OpenRouter, Anthropic, OpenAI, Google, GitHub Copilot, Ollama, vLLM, and any OpenAI-compatible endpoint. Capabilities like vision and tool use are auto-detected per provider. |
| **[Provider Routing](../providers/routing.md)** | Control which sub-providers OpenRouter uses. Sort by cost, speed, or quality. Allowlist, blocklist, or explicitly order providers. |
| **[Fallback Providers](../providers/fallback.md)** | Automatic failover when your primary model fails. Separate fallback chains for vision, compression, and web extraction. |

## Connecting to Platforms — Order of Preference

When wiring Spark to an external platform (Google Workspace, Slack, Notion, HubSpot, GitHub, …), reach for these in order. Skills and CLIs are preferred because they need no long-lived OAuth server, store their own credentials, and are installable on demand.

1. **Skills (preferred).** Install a connector skill and call it from chat or as a slash command.
   - Browse/search/install: `spark skills` (or `/skills` in the TUI), backed by `skills_hub.py`. Skills land in `~/.spark/skills/` and register slash commands via `src/agent/skill_commands.py`.
   - Bundled skill families include `gws-*` (Google Workspace — Gmail, Calendar, Drive, Docs, Sheets, Slides, …), `email`, and many more under `skills/`.
   - Enable per platform with `spark skills` and the toolset config in `tools_config.py`; gateway menus surface them from `commands.py`.
2. **CLI wrappers.** When a vendor ships a CLI (e.g. `openskills`, `gh`), wrap it as a skill/tool rather than re-implementing OAuth. The CLI owns the credential lifecycle.
3. **OAuth connectors (Web UI).** Only when no skill/CLI fits — see below. Built for Google today (`google_connector.py`, `connectors_routes.py`); callback URLs are environment-aware (`localhost` locally, public host in server environments, or `connectors.oauth_redirect_base` override).
4. **MCP servers (fallback).** Last resort when none of the above exists.

## Tool Servers (MCP)

- **[MCP Servers](../tools/mcp.md)** — Connect Spark to any external tool server via Model Context Protocol. GitHub, databases, file systems, browser stacks, internal APIs — no native tool writing required. Supports stdio and SSE transports, per-server tool filtering, and capability-aware resource/prompt registration. Per the order above, prefer a skill or CLI before adding an MCP server.

## Web Search Backends

`web_search` and `web_extract` support four backends. Set one explicitly or let Spark auto-detect from available API keys.

| Backend | Env Var | Search | Extract | Crawl |
|---------|---------|--------|---------|-------|
| **Firecrawl** (default) | `FIRECRAWL_API_KEY` |  |  |  |
| **Parallel** | `PARALLEL_API_KEY` |  |  | - |
| **Tavily** | `TAVILY_API_KEY` |  |  |  |
| **Exa** | `EXA_API_KEY` |  |  | - |

```yaml
web:
  backend: firecrawl    # firecrawl | parallel | tavily | exa
```

Self-hosted Firecrawl is supported via `FIRECRAWL_API_URL`.

## Browser Automation

Full browser control with four backend options:

- **Browserbase** — Managed cloud browsers with anti-bot tooling, CAPTCHA solving, and residential proxies
- **Browser Use** — Alternative cloud browser provider
- **Local Chrome via CDP** — Connect to your running Chrome with `/browser connect`
- **Local Chromium** — Headless local browser via the `agent-browser` CLI

See [Browser Automation](../tools/browser.md) for setup details.

## Voice & TTS

Text-to-speech and speech-to-text across all messaging platforms.

| Provider | Quality | Cost | API Key |
|----------|---------|------|---------|
| **Edge TTS** (default) | Good | Free | None |
| **ElevenLabs** | Excellent | Paid | `ELEVENLABS_API_KEY` |
| **OpenAI TTS** | Good | Paid | `VOICE_TOOLS_OPENAI_KEY` |
| **MiniMax** | Good | Paid | `MINIMAX_API_KEY` |
| **NeuTTS** | Good | Free | None |

Speech-to-text: local Whisper (free, on-device), Groq (fast cloud), OpenAI Whisper API. Voice message transcription works across Telegram, Discord, WhatsApp, and other platforms. See [Voice & TTS](../voice/tts.md) and [Voice Mode](../voice/voice-mode.md).

## IDE & Editor Integration

- **[ACP Integration](acp.md)** — Run Spark inside VS Code, Zed, or JetBrains as an ACP server. Chat messages, tool activity, file diffs, and terminal commands all render natively in your editor.

## Programmatic Access

- **[API Server](api-server.md)** — Expose Spark as an OpenAI-compatible HTTP endpoint. Open WebUI, LobeChat, LibreChat, NextChat, ChatBox — anything that speaks OpenAI format can connect and use Spark's full toolset as a backend.

## Memory & Personalization

- **[Built-in Memory](../memory/index.md)** — Persistent memory via `MEMORY.md` and `USER.md`. The agent maintains bounded stores of personal notes and user profile data that carry over between sessions.
- **[Memory Providers](../memory/providers.md)** — Plug in external memory backends for deeper personalization. Eight providers: Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, and Supermemory.

## Messaging Platforms

Spark runs as a gateway bot on 15+ platforms, all configured through the same `gateway` subsystem:

**[Telegram](../chat-platforms/telegram.md)** · **[Discord](../chat-platforms/discord.md)** · **[Slack](../chat-platforms/slack.md)** · **[WhatsApp](../chat-platforms/whatsapp.md)** · **[Signal](../chat-platforms/signal.md)** · **[Matrix](../chat-platforms/matrix.md)** · **[Mattermost](../chat-platforms/mattermost.md)** · **[Email](../chat-platforms/email.md)** · **[SMS](../chat-platforms/sms.md)** · **[DingTalk](../chat-platforms/dingtalk.md)** · **[Feishu/Lark](../chat-platforms/feishu.md)** · **[WeCom](../chat-platforms/wecom.md)** · **[WeCom Callback](../chat-platforms/wecom-callback.md)** · **[Weixin](../chat-platforms/weixin.md)** · **[BlueBubbles](../chat-platforms/bluebubbles.md)** · **[QQ Bot](../chat-platforms/qqbot.md)** · **[Home Assistant](../chat-platforms/homeassistant.md)** · **[Webhooks](../chat-platforms/webhooks.md)**

See the [Messaging Gateway overview](../chat-platforms/index.md) for the platform comparison table and setup guide.

## Home Automation

- **[Home Assistant](../chat-platforms/homeassistant.md)** — Control smart home devices via four dedicated tools: `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`. The toolset activates automatically when `HASS_TOKEN` is set.

## Plugins

- **[Plugin System](../automate/plugins.md)** — Add custom tools, lifecycle hooks, and CLI commands without touching core code. Plugins are discovered from `~/.spark/plugins/`, project-local `.spark/plugins/`, and pip entry points.
- **[Build a Plugin](../guides/build-a-plugin.md)** — Step-by-step guide for creating plugins with tools, hooks, and CLI commands.

## Training & Evaluation

- **[RL Training](../automate/model-training.md)** — Generate trajectory data from agent sessions for reinforcement learning and model fine-tuning. Supports Atropos environments with customizable reward functions.
- **[Batch Processing](../automate/batch.md)** — Run the agent across hundreds of prompts in parallel, generating structured ShareGPT-format trajectory data for training or evaluation.
