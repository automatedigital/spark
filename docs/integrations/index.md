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
| **[AI Providers](/docs/providers/routing)** | OpenRouter, Anthropic, OpenAI, Google, GitHub Copilot, Ollama, vLLM, and any OpenAI-compatible endpoint. Capabilities like vision and tool use are auto-detected per provider. |
| **[Provider Routing](/docs/providers/routing)** | Control which sub-providers OpenRouter uses. Sort by cost, speed, or quality. Allowlist, blocklist, or explicitly order providers. |
| **[Fallback Providers](/docs/providers/fallback)** | Automatic failover when your primary model fails. Separate fallback chains for vision, compression, and web extraction. |

## Tool Servers (MCP)

- **[MCP Servers](/docs/tools/mcp)** — Connect Spark to any external tool server via Model Context Protocol. GitHub, databases, file systems, browser stacks, internal APIs — no native tool writing required. Supports stdio and SSE transports, per-server tool filtering, and capability-aware resource/prompt registration.

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

See [Browser Automation](/docs/tools/browser) for setup details.

## Voice & TTS

Text-to-speech and speech-to-text across all messaging platforms.

| Provider | Quality | Cost | API Key |
|----------|---------|------|---------|
| **Edge TTS** (default) | Good | Free | None |
| **ElevenLabs** | Excellent | Paid | `ELEVENLABS_API_KEY` |
| **OpenAI TTS** | Good | Paid | `VOICE_TOOLS_OPENAI_KEY` |
| **MiniMax** | Good | Paid | `MINIMAX_API_KEY` |
| **NeuTTS** | Good | Free | None |

Speech-to-text: local Whisper (free, on-device), Groq (fast cloud), OpenAI Whisper API. Voice message transcription works across Telegram, Discord, WhatsApp, and other platforms. See [Voice & TTS](/docs/voice/tts) and [Voice Mode](/docs/voice/voice-mode).

## IDE & Editor Integration

- **[ACP Integration](/docs/integrations/acp)** — Run Spark inside VS Code, Zed, or JetBrains as an ACP server. Chat messages, tool activity, file diffs, and terminal commands all render natively in your editor.

## Programmatic Access

- **[API Server](/docs/integrations/api-server)** — Expose Spark as an OpenAI-compatible HTTP endpoint. Open WebUI, LobeChat, LibreChat, NextChat, ChatBox — anything that speaks OpenAI format can connect and use Spark's full toolset as a backend.

## Memory & Personalization

- **[Built-in Memory](/docs/memory)** — Persistent memory via `MEMORY.md` and `USER.md`. The agent maintains bounded stores of personal notes and user profile data that carry over between sessions.
- **[Memory Providers](/docs/memory/providers)** — Plug in external memory backends for deeper personalization. Eight providers: Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, and Supermemory.

## Messaging Platforms

Spark runs as a gateway bot on 15+ platforms, all configured through the same `gateway` subsystem:

**[Telegram](/docs/chat-platforms/telegram)** · **[Discord](/docs/chat-platforms/discord)** · **[Slack](/docs/chat-platforms/slack)** · **[WhatsApp](/docs/chat-platforms/whatsapp)** · **[Signal](/docs/chat-platforms/signal)** · **[Matrix](/docs/chat-platforms/matrix)** · **[Mattermost](/docs/chat-platforms/mattermost)** · **[Email](/docs/chat-platforms/email)** · **[SMS](/docs/chat-platforms/sms)** · **[DingTalk](/docs/chat-platforms/dingtalk)** · **[Feishu/Lark](/docs/chat-platforms/feishu)** · **[WeCom](/docs/chat-platforms/wecom)** · **[WeCom Callback](/docs/chat-platforms/wecom-callback)** · **[Weixin](/docs/chat-platforms/weixin)** · **[BlueBubbles](/docs/chat-platforms/bluebubbles)** · **[QQ Bot](/docs/chat-platforms/qqbot)** · **[Home Assistant](/docs/chat-platforms/homeassistant)** · **[Webhooks](/docs/chat-platforms/webhooks)**

See the [Messaging Gateway overview](/docs/chat-platforms) for the platform comparison table and setup guide.

## Home Automation

- **[Home Assistant](/docs/chat-platforms/homeassistant)** — Control smart home devices via four dedicated tools: `ha_list_entities`, `ha_get_state`, `ha_list_services`, `ha_call_service`. The toolset activates automatically when `HASS_TOKEN` is set.

## Plugins

- **[Plugin System](/docs/automate/plugins)** — Add custom tools, lifecycle hooks, and CLI commands without touching core code. Plugins are discovered from `~/.spark/plugins/`, project-local `.spark/plugins/`, and pip entry points.
- **[Build a Plugin](/docs/guides/build-a-plugin)** — Step-by-step guide for creating plugins with tools, hooks, and CLI commands.

## Training & Evaluation

- **[RL Training](/docs/automate/model-training)** — Generate trajectory data from agent sessions for reinforcement learning and model fine-tuning. Supports Atropos environments with customizable reward functions.
- **[Batch Processing](/docs/automate/batch)** — Run the agent across hundreds of prompts in parallel, generating structured ShareGPT-format trajectory data for training or evaluation.
