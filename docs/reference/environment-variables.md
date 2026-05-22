---
sidebar_position: 2
title: "Environment Variables"
description: "Complete reference of all environment variables used by Spark Agent"
---

# Environment Variables

Put these in `~/.spark/.env`. Or use `spark config set VAR value` — it handles the right file automatically.

:::tip
`spark config set` writes secrets to `.env` and everything else to `config.yaml`. You rarely need to edit either file by hand.
:::

---

## LLM Providers

Pick one (or more) provider and set its key. Spark auto-selects based on what's configured.

| Variable | What it unlocks |
|----------|-----------------|
| `OPENROUTER_API_KEY` | [OpenRouter](https://openrouter.ai/) — hundreds of models, one key. Recommended. |
| `OPENROUTER_BASE_URL` | Override the OpenRouter-compatible base URL |
| `AI_GATEWAY_API_KEY` | [Vercel AI Gateway](https://ai-gateway.vercel.sh) |
| `AI_GATEWAY_BASE_URL` | Override AI Gateway base URL (default: `https://ai-gateway.vercel.sh/v1`) |
| `OPENAI_API_KEY` | Custom OpenAI-compatible endpoint (pair with `OPENAI_BASE_URL`) |
| `OPENAI_BASE_URL` | Base URL for custom endpoint — vLLM, SGLang, etc. |
| `COPILOT_GITHUB_TOKEN` | GitHub Copilot — first priority. OAuth `gho_*` or fine-grained PAT `github_pat_*`. Classic PATs `ghp_*` are **not supported**. |
| `GH_TOKEN` | GitHub token — second priority for Copilot. Also used by the `gh` CLI. |
| `GITHUB_TOKEN` | GitHub token — third priority for Copilot |
| `SPARK_COPILOT_ACP_COMMAND` | Override Copilot ACP CLI binary path (default: `copilot`) |
| `COPILOT_CLI_PATH` | Alias for `SPARK_COPILOT_ACP_COMMAND` |
| `SPARK_COPILOT_ACP_ARGS` | Override Copilot ACP arguments (default: `--acp --stdio`) |
| `COPILOT_ACP_BASE_URL` | Override Copilot ACP base URL |
| `GLM_API_KEY` | [z.ai / ZhipuAI](https://z.ai) GLM models |
| `ZAI_API_KEY` | Alias for `GLM_API_KEY` |
| `Z_AI_API_KEY` | Alias for `GLM_API_KEY` |
| `GLM_BASE_URL` | Override z.ai base URL (default: `https://api.z.ai/api/paas/v4`) |
| `KIMI_API_KEY` | [Kimi / Moonshot AI](https://platform.moonshot.ai) |
| `KIMI_BASE_URL` | Override Kimi base URL (default: `https://api.moonshot.ai/v1`) |
| `KIMI_CN_API_KEY` | [Kimi / Moonshot China](https://platform.moonshot.cn) |
| `ARCEEAI_API_KEY` | [Arcee AI](https://chat.arcee.ai/) |
| `ARCEE_BASE_URL` | Override Arcee base URL (default: `https://api.arcee.ai/api/v1`) |
| `MINIMAX_API_KEY` | [MiniMax](https://www.minimax.io) — global endpoint |
| `MINIMAX_BASE_URL` | Override MiniMax base URL (default: `https://api.minimax.io/v1`) |
| `MINIMAX_CN_API_KEY` | [MiniMax China](https://www.minimaxi.com) |
| `MINIMAX_CN_BASE_URL` | Override MiniMax China base URL (default: `https://api.minimaxi.com/v1`) |
| `KILOCODE_API_KEY` | [Kilo Code](https://kilo.ai) |
| `KILOCODE_BASE_URL` | Override Kilo Code base URL (default: `https://api.kilo.ai/api/gateway`) |
| `XIAOMI_API_KEY` | [Xiaomi MiMo](https://platform.xiaomimimo.com) |
| `XIAOMI_BASE_URL` | Override Xiaomi MiMo base URL (default: `https://api.xiaomimimo.com/v1`) |
| `HF_TOKEN` | [Hugging Face](https://huggingface.co/settings/tokens) Inference Providers |
| `HF_BASE_URL` | Override Hugging Face base URL (default: `https://router.huggingface.co/v1`) |
| `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) — Gemini models |
| `GEMINI_API_KEY` | Alias for `GOOGLE_API_KEY` |
| `GEMINI_BASE_URL` | Override Google AI Studio base URL |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) — Claude models |
| `ANTHROPIC_TOKEN` | Manual or legacy Anthropic OAuth/setup-token override |
| `DASHSCOPE_API_KEY` | [Alibaba DashScope](https://modelstudio.console.alibabacloud.com/) — Qwen models |
| `DASHSCOPE_BASE_URL` | Custom DashScope base URL (default: `https://coding-intl.dashscope.aliyuncs.com/v1`) |
| `DEEPSEEK_API_KEY` | [DeepSeek](https://platform.deepseek.com/api_keys) direct access |
| `DEEPSEEK_BASE_URL` | Custom DeepSeek API base URL |
| `OPENCODE_ZEN_API_KEY` | [OpenCode Zen](https://opencode.ai/auth) — pay-as-you-go, curated models |
| `OPENCODE_ZEN_BASE_URL` | Override OpenCode Zen base URL |
| `OPENCODE_GO_API_KEY` | [OpenCode Go](https://opencode.ai/auth) — $10/month, open models |
| `OPENCODE_GO_BASE_URL` | Override OpenCode Go base URL |
| `CLAUDE_CODE_OAUTH_TOKEN` | Explicit Claude Code token override |
| `SPARK_MODEL` | Override model name at process level. Prefer `config.yaml` for normal use; this is mainly for the cron scheduler. |
| `VOICE_TOOLS_OPENAI_KEY` | Preferred OpenAI key for speech-to-text and text-to-speech |
| `SPARK_LOCAL_STT_COMMAND` | Local speech-to-text command template. Supports `{input_path}`, `{output_dir}`, `{language}`, `{model}` placeholders. |
| `SPARK_LOCAL_STT_LANGUAGE` | Default language for local STT (default: `en`) |
| `SPARK_HOME` | Override Spark config directory (default: `~/.spark`). Also scopes the gateway PID file and systemd service name — lets multiple installations run side by side. |

### Native Anthropic Auth (Claude Pro/Max)

Spark checks for Claude Code's own credential files first. Those credentials refresh automatically. `ANTHROPIC_TOKEN` is still valid as a manual override, but it's no longer the preferred path for Claude Pro/Max login.

| Variable | What it does |
|----------|--------------|
| `SPARK_INFERENCE_PROVIDER` | Force a specific provider. Options: `auto`, `openrouter`, `openai-codex`, `copilot`, `copilot-acp`, `anthropic`, `huggingface`, `zai`, `kimi-coding`, `kimi-coding-cn`, `minimax`, `minimax-cn`, `kilocode`, `xiaomi`, `arcee`, `alibaba`, `deepseek`, `opencode-zen`, `opencode-go`, `ai-gateway` (default: `auto`) |
| `SPARK_DUMP_REQUESTS` | Dump API request payloads to log files (`true`/`false`) |
| `SPARK_PREFILL_MESSAGES_FILE` | JSON file of ephemeral prefill messages injected at API-call time |
| `SPARK_TIMEZONE` | IANA timezone override (e.g. `America/New_York`) |

---

## Tool APIs

These unlock optional tools. None are required — only set what you use.

| Variable | What it enables |
|----------|-----------------|
| `PARALLEL_API_KEY` | AI-native web search via [Parallel](https://parallel.ai/) |
| `FIRECRAWL_API_KEY` | Web scraping and cloud browser via [Firecrawl](https://firecrawl.dev/) |
| `FIRECRAWL_API_URL` | Custom Firecrawl endpoint for self-hosted instances |
| `TAVILY_API_KEY` | AI-native search, extract, and crawl via [Tavily](https://app.tavily.com/home) |
| `EXA_API_KEY` | AI-native search and content retrieval via [Exa](https://exa.ai/) |
| `BROWSERBASE_API_KEY` | Cloud browser automation via [Browserbase](https://browserbase.com/) |
| `BROWSERBASE_PROJECT_ID` | Browserbase project ID |
| `BROWSER_USE_API_KEY` | Cloud browser via [Browser Use](https://browser-use.com/) |
| `FIRECRAWL_BROWSER_TTL` | Firecrawl browser session TTL in seconds (default: 300) |
| `BROWSER_CDP_URL` | Chrome DevTools Protocol URL for local browser. Set via `/browser connect` (e.g. `ws://localhost:9222`) |
| `CAMOFOX_URL` | Camofox anti-detection browser URL (default: `http://localhost:9377`) |
| `BROWSER_INACTIVITY_TIMEOUT` | Browser session inactivity timeout in seconds |
| `FAL_KEY` | Image generation via [fal.ai](https://fal.ai/) |
| `GROQ_API_KEY` | Groq Whisper speech-to-text via [Groq](https://groq.com/) |
| `ELEVENLABS_API_KEY` | Premium TTS voices via [ElevenLabs](https://elevenlabs.io/) |
| `STT_GROQ_MODEL` | Override the Groq STT model (default: `whisper-large-v3-turbo`) |
| `GROQ_BASE_URL` | Override the Groq OpenAI-compatible STT endpoint |
| `STT_OPENAI_MODEL` | Override the OpenAI STT model (default: `whisper-1`) |
| `STT_OPENAI_BASE_URL` | Override the OpenAI-compatible STT endpoint |
| `GITHUB_TOKEN` | GitHub token for Skills Hub — higher rate limits, skill publishing |
| `HONCHO_API_KEY` | Cross-session user modeling via [Honcho](https://honcho.dev/) |
| `HONCHO_BASE_URL` | Base URL for self-hosted Honcho (default: Honcho cloud). No key needed for local instances. |
| `SUPERMEMORY_API_KEY` | Semantic long-term memory via [Supermemory](https://supermemory.ai) |
| `TINKER_API_KEY` | RL training via [Tinker](https://tinker-console.thinkingmachines.ai/) |
| `WANDB_API_KEY` | RL training metrics via [W&B](https://wandb.ai/) |
| `DAYTONA_API_KEY` | Daytona cloud sandboxes via [Daytona](https://daytona.io/) |

---

## Terminal Backends

Control where Spark runs shell commands.

### Backend Selection

| Variable | Options |
|----------|---------|
| `TERMINAL_ENV` | `local` (default), `docker`, `ssh`, `singularity`, `modal`, `daytona` |

### Docker

| Variable | Default | Notes |
|----------|---------|-------|
| `TERMINAL_DOCKER_IMAGE` | `nikolaik/python-nodejs:python3.11-nodejs20` | Image to use |
| `TERMINAL_DOCKER_FORWARD_ENV` | — | JSON array of env var names to forward. Skill-declared vars forward automatically — only needed for others. |
| `TERMINAL_DOCKER_VOLUMES` | — | Extra volume mounts, comma-separated `host:container` pairs |
| `TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE` | `false` | Mount launch cwd into Docker `/workspace` |

### SSH

| Variable | Default | Notes |
|----------|---------|-------|
| `TERMINAL_SSH_HOST` | — | Remote server hostname |
| `TERMINAL_SSH_USER` | — | SSH username |
| `TERMINAL_SSH_PORT` | `22` | SSH port |
| `TERMINAL_SSH_KEY` | — | Path to private key |
| `TERMINAL_SSH_PERSISTENT` | Follows `TERMINAL_PERSISTENT_SHELL` | Override persistent shell for SSH |

### Container Resources (Docker, Singularity, Modal, Daytona)

| Variable | Default | Notes |
|----------|---------|-------|
| `TERMINAL_CONTAINER_CPU` | `1` | CPU cores |
| `TERMINAL_CONTAINER_MEMORY` | `5120` | Memory in MB |
| `TERMINAL_CONTAINER_DISK` | `51200` | Disk in MB |
| `TERMINAL_CONTAINER_PERSISTENT` | `true` | Persist filesystem across sessions |
| `TERMINAL_SANDBOX_DIR` | `~/.spark/sandboxes/` | Host dir for workspaces and overlays |

### Other Backend Variables

| Variable | Default | Notes |
|----------|---------|-------|
| `TERMINAL_SINGULARITY_IMAGE` | — | Singularity image or `.sif` path |
| `TERMINAL_MODAL_IMAGE` | — | Modal container image |
| `TERMINAL_DAYTONA_IMAGE` | — | Daytona sandbox image |
| `TERMINAL_TIMEOUT` | — | Command timeout in seconds |
| `TERMINAL_LIFETIME_SECONDS` | — | Max session lifetime. After expiry, Spark may recreate the sandbox. |
| `TERMINAL_CWD` | — | Working directory for all terminal sessions |
| `SUDO_PASSWORD` | — | Enable sudo without an interactive prompt |

### Persistent Shell

| Variable | Default | Notes |
|----------|---------|-------|
| `TERMINAL_PERSISTENT_SHELL` | `true` | Persistent shell for non-local backends. Also settable via `terminal.persistent_shell` in config.yaml. |
| `TERMINAL_LOCAL_PERSISTENT` | `false` | Persistent shell for the local backend |
| `TERMINAL_SSH_PERSISTENT` | Follows `TERMINAL_PERSISTENT_SHELL` | SSH-specific override |

---

## Messaging Platforms

Each platform needs its own token. Set only the ones you use.

### Telegram

| Variable | Notes |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated user IDs |
| `TELEGRAM_HOME_CHANNEL` | Default chat/channel for cron delivery |
| `TELEGRAM_HOME_CHANNEL_NAME` | Display name for the home channel |
| `TELEGRAM_WEBHOOK_URL` | Public HTTPS URL — enables webhook instead of polling |
| `TELEGRAM_WEBHOOK_PORT` | Local webhook listen port (default: `8443`) |
| `TELEGRAM_WEBHOOK_SECRET` | Token for verifying updates come from Telegram |
| `TELEGRAM_REACTIONS` | Emoji reactions during processing (default: `false`) |

### Discord

| Variable | Notes |
|----------|-------|
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `DISCORD_ALLOWED_USERS` | Comma-separated user IDs |
| `DISCORD_HOME_CHANNEL` | Default channel for cron delivery |
| `DISCORD_HOME_CHANNEL_NAME` | Display name for the home channel |
| `DISCORD_REQUIRE_MENTION` | Require @mention in server channels |
| `DISCORD_FREE_RESPONSE_CHANNELS` | Channel IDs where mention is not required |
| `DISCORD_AUTO_THREAD` | Auto-thread long replies |
| `DISCORD_REACTIONS` | Emoji reactions during processing (default: `true`) |
| `DISCORD_IGNORED_CHANNELS` | Channel IDs where the bot never responds |
| `DISCORD_NO_THREAD_CHANNELS` | Channel IDs where bot responds without threading |
| `DISCORD_REPLY_TO_MODE` | Reply-reference style: `off`, `first` (default), or `all` |

### Slack

| Variable | Notes |
|----------|-------|
| `SLACK_BOT_TOKEN` | Bot token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | App-level token (`xapp-...`) — required for Socket Mode |
| `SLACK_ALLOWED_USERS` | Comma-separated user IDs |
| `SLACK_HOME_CHANNEL` | Default channel for cron delivery |
| `SLACK_HOME_CHANNEL_NAME` | Display name for the home channel |

### WhatsApp

| Variable | Notes |
|----------|-------|
| `WHATSAPP_ENABLED` | Enable the WhatsApp bridge (`true`/`false`) |
| `WHATSAPP_MODE` | `bot` (separate number) or `self-chat` (message yourself) |
| `WHATSAPP_ALLOWED_USERS` | Comma-separated phone numbers with country code, no `+`. Or `*` to allow all. |
| `WHATSAPP_ALLOW_ALL_USERS` | Skip the allowlist entirely (`true`/`false`) |
| `WHATSAPP_DEBUG` | Log raw message events (`true`/`false`) |

### Signal

| Variable | Notes |
|----------|-------|
| `SIGNAL_HTTP_URL` | signal-cli daemon endpoint (e.g. `http://127.0.0.1:8080`) |
| `SIGNAL_ACCOUNT` | Bot phone number in E.164 format |
| `SIGNAL_ALLOWED_USERS` | Comma-separated E.164 numbers or UUIDs |
| `SIGNAL_GROUP_ALLOWED_USERS` | Comma-separated group IDs, or `*` for all groups |
| `SIGNAL_HOME_CHANNEL_NAME` | Display name for the home channel |
| `SIGNAL_IGNORE_STORIES` | Ignore Signal stories/status updates |
| `SIGNAL_ALLOW_ALL_USERS` | Skip the allowlist entirely |

### SMS (Twilio)

| Variable | Notes |
|----------|-------|
| `TWILIO_ACCOUNT_SID` | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token — also used for webhook signature validation |
| `TWILIO_PHONE_NUMBER` | Your Twilio number in E.164 format |
| `SMS_WEBHOOK_URL` | Public URL matching the webhook URL in Twilio Console (required) |
| `SMS_WEBHOOK_PORT` | Webhook listener port (default: `8080`) |
| `SMS_WEBHOOK_HOST` | Webhook bind address (default: `0.0.0.0`) |
| `SMS_INSECURE_NO_SIGNATURE` | Disable Twilio signature validation — local dev only |
| `SMS_ALLOWED_USERS` | Comma-separated E.164 numbers |
| `SMS_ALLOW_ALL_USERS` | Skip the allowlist |
| `SMS_HOME_CHANNEL` | Number for cron/notification delivery |
| `SMS_HOME_CHANNEL_NAME` | Display name for the home channel |

### Email

| Variable | Notes |
|----------|-------|
| `EMAIL_ADDRESS` | Email address for the gateway adapter |
| `EMAIL_PASSWORD` | Password or app password |
| `EMAIL_IMAP_HOST` | IMAP hostname |
| `EMAIL_IMAP_PORT` | IMAP port |
| `EMAIL_SMTP_HOST` | SMTP hostname |
| `EMAIL_SMTP_PORT` | SMTP port |
| `EMAIL_ALLOWED_USERS` | Comma-separated email addresses |
| `EMAIL_HOME_ADDRESS` | Default recipient for proactive delivery |
| `EMAIL_HOME_ADDRESS_NAME` | Display name for the email home target |
| `EMAIL_POLL_INTERVAL` | Polling interval in seconds |
| `EMAIL_ALLOW_ALL_USERS` | Allow all inbound senders |

### DingTalk

| Variable | Notes |
|----------|-------|
| `DINGTALK_CLIENT_ID` | Bot AppKey from [open.dingtalk.com](https://open.dingtalk.com) |
| `DINGTALK_CLIENT_SECRET` | Bot AppSecret |
| `DINGTALK_ALLOWED_USERS` | Comma-separated user IDs |

### Feishu / Lark

| Variable | Notes |
|----------|-------|
| `FEISHU_APP_ID` | App ID from [open.feishu.cn](https://open.feishu.cn/) |
| `FEISHU_APP_SECRET` | App Secret |
| `FEISHU_DOMAIN` | `feishu` (China) or `lark` (international). Default: `feishu` |
| `FEISHU_CONNECTION_MODE` | `websocket` (recommended) or `webhook`. Default: `websocket` |
| `FEISHU_ENCRYPT_KEY` | Encryption key for webhook mode (optional) |
| `FEISHU_VERIFICATION_TOKEN` | Verification token for webhook mode (optional) |
| `FEISHU_ALLOWED_USERS` | Comma-separated user IDs |
| `FEISHU_HOME_CHANNEL` | Chat ID for cron delivery |

### WeCom (Enterprise WeChat)

| Variable | Notes |
|----------|-------|
| `WECOM_BOT_ID` | AI Bot ID from admin console |
| `WECOM_SECRET` | AI Bot secret |
| `WECOM_WEBSOCKET_URL` | Custom WebSocket URL (default: `wss://openws.work.weixin.qq.com`) |
| `WECOM_ALLOWED_USERS` | Comma-separated user IDs |
| `WECOM_HOME_CHANNEL` | Chat ID for cron delivery |
| `WECOM_CALLBACK_CORP_ID` | Corp ID for callback self-built app |
| `WECOM_CALLBACK_CORP_SECRET` | Corp secret for the self-built app |
| `WECOM_CALLBACK_AGENT_ID` | Agent ID of the self-built app |
| `WECOM_CALLBACK_TOKEN` | Callback verification token |
| `WECOM_CALLBACK_ENCODING_AES_KEY` | AES key for callback encryption |
| `WECOM_CALLBACK_HOST` | Callback server bind address (default: `0.0.0.0`) |
| `WECOM_CALLBACK_PORT` | Callback server port (default: `8645`) |
| `WECOM_CALLBACK_ALLOWED_USERS` | Comma-separated user IDs |
| `WECOM_CALLBACK_ALLOW_ALL_USERS` | Skip the allowlist (`true`) |

### Weixin (Personal WeChat via iLink)

| Variable | Notes |
|----------|-------|
| `WEIXIN_ACCOUNT_ID` | Account ID from QR login via iLink Bot API |
| `WEIXIN_TOKEN` | Auth token from QR login |
| `WEIXIN_BASE_URL` | Override iLink base URL (default: `https://ilinkai.weixin.qq.com`) |
| `WEIXIN_CDN_BASE_URL` | Override CDN base URL for media (default: `https://novac2c.cdn.weixin.qq.com/c2c`) |
| `WEIXIN_DM_POLICY` | DM access policy: `open`, `allowlist`, `pairing`, `disabled` (default: `open`) |
| `WEIXIN_GROUP_POLICY` | Group access policy: `open`, `allowlist`, `disabled` (default: `disabled`) |
| `WEIXIN_ALLOWED_USERS` | Comma-separated user IDs |
| `WEIXIN_GROUP_ALLOWED_USERS` | Comma-separated group IDs |
| `WEIXIN_HOME_CHANNEL` | Chat ID for cron delivery |
| `WEIXIN_HOME_CHANNEL_NAME` | Display name for the home channel |
| `WEIXIN_ALLOW_ALL_USERS` | Skip the allowlist (`true`/`false`) |

### BlueBubbles (iMessage bridge)

| Variable | Notes |
|----------|-------|
| `BLUEBUBBLES_SERVER_URL` | BlueBubbles server URL (e.g. `http://192.168.1.10:1234`) |
| `BLUEBUBBLES_PASSWORD` | BlueBubbles server password |
| `BLUEBUBBLES_WEBHOOK_HOST` | Webhook listener bind address (default: `127.0.0.1`) |
| `BLUEBUBBLES_WEBHOOK_PORT` | Webhook listener port (default: `8645`) |
| `BLUEBUBBLES_HOME_CHANNEL` | Phone/email for cron/notification delivery |
| `BLUEBUBBLES_ALLOWED_USERS` | Comma-separated authorized users |
| `BLUEBUBBLES_ALLOW_ALL_USERS` | Skip the allowlist (`true`/`false`) |

### QQ Bot

| Variable | Notes |
|----------|-------|
| `QQ_APP_ID` | App ID from [q.qq.com](https://q.qq.com) |
| `QQ_CLIENT_SECRET` | App Secret |
| `QQ_STT_API_KEY` | External STT fallback API key (optional) |
| `QQ_STT_BASE_URL` | External STT provider base URL (optional) |
| `QQ_STT_MODEL` | External STT model name (optional) |
| `QQ_ALLOWED_USERS` | Comma-separated user openIDs |
| `QQ_GROUP_ALLOWED_USERS` | Comma-separated group IDs |
| `QQ_ALLOW_ALL_USERS` | Skip the allowlist (`true`/`false`) |
| `QQ_HOME_CHANNEL` | User/group openID for cron delivery |

### Mattermost

| Variable | Notes |
|----------|-------|
| `MATTERMOST_URL` | Server URL (e.g. `https://mm.example.com`) |
| `MATTERMOST_TOKEN` | Bot token or personal access token |
| `MATTERMOST_ALLOWED_USERS` | Comma-separated user IDs |
| `MATTERMOST_HOME_CHANNEL` | Channel ID for cron/notifications |
| `MATTERMOST_REQUIRE_MENTION` | Require `@mention` in channels (default: `true`) |
| `MATTERMOST_FREE_RESPONSE_CHANNELS` | Channel IDs where bot responds without `@mention` |
| `MATTERMOST_REPLY_MODE` | `thread` or `off` (default) |

### Matrix

| Variable | Notes |
|----------|-------|
| `MATRIX_HOMESERVER` | Homeserver URL (e.g. `https://matrix.org`) |
| `MATRIX_ACCESS_TOKEN` | Bot access token |
| `MATRIX_USER_ID` | Bot user ID (e.g. `@spark:matrix.org`) — required for password login |
| `MATRIX_PASSWORD` | Alternative to access token |
| `MATRIX_ALLOWED_USERS` | Comma-separated user IDs (e.g. `@alice:matrix.org`) |
| `MATRIX_HOME_ROOM` | Room ID for cron delivery (e.g. `!abc123:matrix.org`) |
| `MATRIX_ENCRYPTION` | Enable E2E encryption (`true`/`false`, default: `false`) |
| `MATRIX_REQUIRE_MENTION` | Require `@mention` in rooms (default: `true`) |
| `MATRIX_FREE_RESPONSE_ROOMS` | Room IDs where bot responds without `@mention` |
| `MATRIX_AUTO_THREAD` | Auto-create threads (default: `true`) |
| `MATRIX_DM_MENTION_THREADS` | Thread when bot is `@mentioned` in a DM (default: `false`) |
| `MATRIX_RECOVERY_KEY` | Recovery key for cross-signing. Recommended for E2EE with cross-signing enabled. |

### Home Assistant

| Variable | Notes |
|----------|-------|
| `HASS_TOKEN` | Long-Lived Access Token — enables the HA platform and tools |
| `HASS_URL` | Home Assistant URL (default: `http://homeassistant.local:8123`) |

### Webhook & API Server

| Variable | Notes |
|----------|-------|
| `WEBHOOK_ENABLED` | Enable the webhook platform adapter (`true`/`false`) |
| `WEBHOOK_PORT` | HTTP server port (default: `8644`) |
| `WEBHOOK_SECRET` | Global HMAC secret for signature validation |
| `API_SERVER_ENABLED` | Enable the OpenAI-compatible API server (`true`/`false`) |
| `API_SERVER_KEY` | Bearer token for auth — enforced for non-loopback binding |
| `API_SERVER_CORS_ORIGINS` | Browser origins allowed to call the API server directly (e.g. `http://localhost:3000`) |
| `API_SERVER_PORT` | API server port (default: `8642`) |
| `API_SERVER_HOST` | Bind address (default: `127.0.0.1`). Use `0.0.0.0` only with `API_SERVER_KEY` set. |
| `API_SERVER_MODEL_NAME` | Model name advertised on `/v1/models`. Useful for multi-user setups. |
| `MESSAGING_CWD` | Working directory for terminal commands in messaging mode (default: `~/.spark/workspace`) |
| `GATEWAY_ALLOWED_USERS` | Comma-separated user IDs across all platforms |
| `GATEWAY_ALLOW_ALL_USERS` | Skip all allowlists (`true`/`false`, default: `false`) |

---

## Agent Behavior

Tune how the agent runs.

| Variable | Default | Notes |
|----------|---------|-------|
| `SPARK_MAX_ITERATIONS` | `90` | Max tool-calling iterations per conversation |
| `SPARK_TOOL_PROGRESS` | — | Deprecated — use `display.tool_progress` in `config.yaml` |
| `SPARK_TOOL_PROGRESS_MODE` | — | Deprecated — use `display.tool_progress` in `config.yaml` |
| `SPARK_HUMAN_DELAY_MODE` | `off` | Response pacing: `off`, `natural`, `custom` |
| `SPARK_HUMAN_DELAY_MIN_MS` | — | Custom delay minimum (ms) |
| `SPARK_HUMAN_DELAY_MAX_MS` | — | Custom delay maximum (ms) |
| `SPARK_QUIET` | `false` | Suppress non-essential output |
| `SPARK_API_TIMEOUT` | `1800` | LLM API call timeout in seconds |
| `SPARK_STREAM_READ_TIMEOUT` | `120` | Streaming socket read timeout. Auto-increased to `SPARK_API_TIMEOUT` for local providers. |
| `SPARK_STREAM_STALE_TIMEOUT` | `180` | Kills the connection if no chunks arrive within this window. Auto-disabled for local providers. |
| `SPARK_EXEC_ASK` | — | Enable execution approval prompts in gateway mode (`true`/`false`) |
| `SPARK_ENABLE_PROJECT_PLUGINS` | `false` | Auto-discover plugins from `./.spark/plugins/` |
| `SPARK_BACKGROUND_NOTIFICATIONS` | `all` | Background process notifications in gateway: `all`, `result`, `error`, `off` |
| `SPARK_EPHEMERAL_SYSTEM_PROMPT` | — | System prompt injected at API-call time — never persisted to sessions |

---

## Cron Scheduler

| Variable | Default | Notes |
|----------|---------|-------|
| `SPARK_CRON_TIMEOUT` | `600` | Inactivity timeout for cron agent runs in seconds. The agent can run indefinitely while actively using tools — this only triggers when idle. Set to `0` for unlimited. |
| `SPARK_CRON_SCRIPT_TIMEOUT` | `120` | Timeout for pre-run scripts in seconds. Also configurable via `cron.script_timeout_seconds` in `config.yaml`. |

---

## Session Settings

| Variable | Default | Notes |
|----------|---------|-------|
| `SESSION_IDLE_MINUTES` | `1440` | Reset sessions after N minutes of inactivity |
| `SESSION_RESET_HOUR` | `4` | Daily reset hour (24h format, 4 = 4am) |

---

## Config-Only Settings

These cannot be set via environment variables — use `~/.spark/config.yaml` directly.

### Context Compression

```yaml
compression:
  enabled: true
  threshold: 0.50
  target_ratio: 0.20         # fraction of threshold to preserve as recent tail
  protect_last_n: 20         # minimum recent messages to keep uncompressed
```

Summarization model lives under `auxiliary.compression:`.

:::info Legacy migration
Older configs with `compression.summary_model`, `compression.summary_provider`, and `compression.summary_base_url` migrate automatically to `auxiliary.compression.*` on first load.
:::

### Auxiliary Task Model Overrides

Override the model Spark uses for specific background tasks.

| Variable | What it overrides |
|----------|------------------|
| `AUXILIARY_VISION_PROVIDER` | Provider for vision tasks |
| `AUXILIARY_VISION_MODEL` | Model for vision tasks |
| `AUXILIARY_VISION_BASE_URL` | Direct OpenAI-compatible endpoint for vision tasks |
| `AUXILIARY_VISION_API_KEY` | API key paired with `AUXILIARY_VISION_BASE_URL` |
| `AUXILIARY_WEB_EXTRACT_PROVIDER` | Provider for web extraction/summarization |
| `AUXILIARY_WEB_EXTRACT_MODEL` | Model for web extraction/summarization |
| `AUXILIARY_WEB_EXTRACT_BASE_URL` | Direct endpoint for web extraction/summarization |
| `AUXILIARY_WEB_EXTRACT_API_KEY` | API key paired with `AUXILIARY_WEB_EXTRACT_BASE_URL` |

For task-specific direct endpoints, Spark uses the task's configured API key or `OPENAI_API_KEY`. It does not reuse `OPENROUTER_API_KEY`.

### Fallback Model

Automatic failover when your main model hits errors:

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

See [Fallback Providers](../providers/fallback.md) for details.

### Provider Routing

Control which providers OpenRouter uses when routing requests:

```yaml
provider_routing:
  sort: "price"           # "price" (default), "throughput", or "latency"
  only: ["anthropic", "google"]   # allowlist
  ignore: ["openai"]              # blocklist
  order: ["anthropic", "google"]  # try in order
  require_parameters: true        # only providers supporting all request params
  data_collection: "deny"         # exclude data-storing providers
```
