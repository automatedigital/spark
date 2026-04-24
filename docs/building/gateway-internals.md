---
sidebar_position: 7
title: "Gateway Internals"
description: "How the messaging gateway boots, authorizes users, routes sessions, and delivers messages"
---

# Gateway Internals

The gateway is a single long-running process that connects Spark to 14+ messaging platforms at once. Understanding how it routes messages, guards sessions, and manages authorization will help you extend it confidently.

## Files at a Glance

| File | What it does |
|------|-------------|
| `gateway/run.py` | `GatewayRunner` — main loop, slash commands, message dispatch (~9,000 lines) |
| `gateway/session.py` | `SessionStore` — conversation persistence and session key construction |
| `gateway/delivery.py` | Outbound message delivery to target platforms/channels |
| `gateway/pairing.py` | DM pairing flow for user authorization |
| `gateway/channel_directory.py` | Maps chat IDs to human-readable names for cron delivery |
| `gateway/hooks.py` | Hook discovery, loading, and lifecycle event dispatch |
| `gateway/mirror.py` | Cross-session message mirroring for `send_message` |
| `gateway/status.py` | Token lock management for profile-scoped gateway instances |
| `gateway/builtin_hooks/` | Always-registered hooks (e.g., BOOT.md system prompt hook) |
| `gateway/platforms/` | Platform adapters — one per messaging platform |

## How a Message Travels Through the System

```text
                 GatewayRunner

             
   Telegram     Discord      Slack     ...  
   Adapter      Adapter     Adapter         
             

                     

              _handle_message()

                         
                                                 
   Slash command   AIAgent      Queue/BG            
    dispatch       creation     sessions            


              SessionStore
           (SQLite persistence)
```

Every inbound message follows these four steps:

1. **Platform adapter** receives the raw event and normalizes it into a `MessageEvent`.
2. **Base adapter** checks the active session guard:
   - If an agent is already running for this session — queue the message, set an interrupt event.
   - If the message is `/approve`, `/deny`, or `/stop` — bypass the guard and dispatch inline.
3. **`GatewayRunner._handle_message()`** takes over:
   - Builds a session key via `_session_key_for_source()`.
   - Runs authorization checks (see below).
   - Dispatches slash commands or creates an `AIAgent` to handle the message.
4. **Response** travels back through the platform adapter to the user.

## Session Keys

Session keys encode full routing context in a single string:

```
agent:main:{platform}:{chat_type}:{chat_id}
```

Example: `agent:main:telegram:private:123456789`

Thread-aware platforms (Telegram forum topics, Discord threads, Slack threads) embed thread IDs in the `chat_id` segment. Never construct session keys by hand — always call `build_session_key()` from `gateway/session.py`.

## The Two-Level Message Guard

When an agent is actively processing, two sequential guards protect it:

| Level | Where | What it checks |
|-------|-------|----------------|
| 1 | `gateway/platforms/base.py` | `_active_sessions` — queues the message in `_pending_messages`, sets interrupt event |
| 2 | `gateway/run.py` | `_running_agents` — intercepts `/stop`, `/new`, `/queue`, `/status`, `/approve`, `/deny`; everything else calls `running_agent.interrupt()` |

Commands that must reach the runner while an agent is blocked (like `/approve`) are dispatched **inline** via `await self._message_handler(event)`. This bypasses the background task system to avoid race conditions.

## Authorization

Authorization is evaluated in order — first match wins:

1. **Per-platform allow-all** (e.g., `TELEGRAM_ALLOW_ALL_USERS`) — all users on that platform are authorized.
2. **Platform allowlist** (e.g., `TELEGRAM_ALLOWED_USERS`) — comma-separated user IDs.
3. **DM pairing** — authenticated users can authorize new users via a pairing code.
4. **Global allow-all** (`GATEWAY_ALLOW_ALL_USERS`) — all users across all platforms.
5. **Default: deny** — if nothing matched, the user is rejected.

### DM Pairing Flow

```text
Admin: /pair
Gateway: "Pairing code: ABC123. Share with the user."
New user: ABC123
Gateway: "Paired! You're now authorized."
```

Pairing state lives in `gateway/pairing.py` and survives restarts.

## Slash Command Dispatch

Every slash command runs through the same pipeline:

1. `resolve_command()` (from `spark_cli/commands.py`) maps input to a canonical name — handles aliases and prefix matching.
2. The canonical name is checked against `GATEWAY_KNOWN_COMMANDS`.
3. The handler in `_handle_message()` dispatches by canonical name.
4. Commands gated on config check the `gateway_config_gate` field on `CommandDef`.

Commands that must not run while an agent is processing are rejected early:

```python
if _quick_key in self._running_agents:
    if canonical == "model":
        return " Agent is running - wait for it to finish or /stop first."
```

Bypass commands — `/stop`, `/new`, `/approve`, `/deny`, `/queue`, `/status` — get special handling.

## Config Sources

| Source | What it provides |
|--------|-----------------|
| `~/.spark/.env` | API keys, bot tokens, platform credentials |
| `~/.spark/config.yaml` | Model settings, tool configuration, display options |
| Environment variables | Override any of the above |

The gateway reads `config.yaml` directly via YAML loader, not through `load_cli_config()`. Config keys that exist in the CLI's defaults dict but not in the user's file may behave differently between CLI and gateway.

## Platform Adapters

Each platform has an adapter in `gateway/platforms/`:

```text
gateway/platforms/
 base.py              # BaseAdapter - shared logic for all platforms
 telegram.py          # Telegram Bot API (long polling or webhook)
 discord.py           # Discord bot via discord.py
 slack.py             # Slack Socket Mode
 whatsapp.py          # WhatsApp Business Cloud API
 signal.py            # Signal via signal-cli REST API
 matrix.py            # Matrix via mautrix (optional E2EE)
 mattermost.py        # Mattermost WebSocket API
 email.py             # Email via IMAP/SMTP
 sms.py               # SMS via Twilio
 dingtalk.py          # DingTalk WebSocket
 feishu.py            # Feishu/Lark WebSocket or webhook
 wecom.py             # WeCom (WeChat Work) callback
 weixin.py            # Weixin (personal WeChat) via iLink Bot API
 bluebubbles.py       # Apple iMessage via BlueBubbles macOS server
 qqbot.py             # QQ Bot (Tencent QQ) via Official API v2
 webhook.py           # Inbound/outbound webhook adapter
 api_server.py        # REST API server adapter
 homeassistant.py     # Home Assistant conversation integration
```

Every adapter implements three methods:

- `connect()` / `disconnect()` — lifecycle management
- `send_message()` — outbound delivery
- `on_message()` — normalize inbound events into `MessageEvent`

Adapters that connect with unique credentials call `acquire_scoped_lock()` on connect and `release_scoped_lock()` on disconnect. This prevents two profiles from using the same bot token at the same time.

## Delivery Paths

`gateway/delivery.py` routes outgoing messages to four targets:

| Path | When used |
|------|-----------|
| Direct reply | Response to the originating chat |
| Home channel | Cron job outputs, background results |
| Explicit target | `send_message` tool with `telegram:-1001234567890` |
| Cross-platform | Deliver to a different platform than the source |

Cron job deliveries are intentionally NOT mirrored into gateway session history — they live in their own cron session to avoid message alternation violations.

## Lifecycle Hooks

Hooks are Python modules that respond to gateway events. Spark fires them at these points:

| Event | When |
|-------|------|
| `gateway:startup` | Gateway process starts |
| `session:start` | New conversation begins |
| `session:end` | Session completes or times out |
| `session:reset` | User resets with `/new` |
| `agent:start` | Agent begins processing a message |
| `agent:step` | Agent completes one tool-calling iteration |
| `agent:end` | Agent finishes and returns response |
| `command:*` | Any slash command executes |

Hooks are discovered from `gateway/builtin_hooks/` (always active) and `~/.spark/hooks/` (user-installed). Each hook is a directory containing a `HOOK.yaml` manifest and a `handler.py`.

## Memory Provider Integration

When a memory provider plugin is enabled, the call chain is:

```text
AIAgent._invoke_tool()
  -> self._memory_manager.handle_tool_call(name, args)
    -> provider.handle_tool_call(name, args)
```

On session end or reset, the flush lifecycle runs in order:

1. Built-in memories are flushed to disk.
2. The provider's `on_session_end()` hook fires.
3. A temporary `AIAgent` runs a memory-only conversation turn.
4. Context is discarded or archived.

## Background Maintenance

The gateway runs these tasks alongside message handling:

- **Cron ticking** — checks job schedules and fires due jobs
- **Session expiry** — cleans up abandoned sessions after timeout
- **Memory flush** — proactively flushes memory before session expiry
- **Cache refresh** — refreshes model lists and provider status

## Process Management

```bash
spark gateway start    # Start the gateway
spark gateway stop     # Stop the current profile's gateway
spark gateway stop --all  # Kill all gateway processes (used during updates)
```

The gateway is also manageable as a system service:
- Linux: `systemctl`
- macOS: `launchctl`

The PID file lives at `~/.spark/gateway.pid`, scoped per profile. `spark gateway stop --all` uses `ps aux` scanning instead of the PID file so it can find all running gateway processes regardless of profile.

## Related Docs

- [Session Storage](./session-storage.md)
- [Cron Internals](./cron-internals.md)
- [ACP Internals](./editor-extension-internals.md)
- [Agent Loop Internals](./agent-loop.md)
- [Messaging Gateway (User Guide)](/docs/chat-platforms)
