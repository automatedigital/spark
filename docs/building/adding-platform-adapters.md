---
sidebar_position: 9
---

# Adding a Platform Adapter

You want users to interact with Spark through a new messaging service. This guide shows you how to wire a new platform adapter into the gateway — from the adapter file itself to CLI integration, toolsets, and documentation.

:::tip
The adapter file is roughly 40% of the work. The remaining 60% is wiring it into the gateway runner, CLI config, toolsets, and docs. Use this guide as a checklist.
:::

## How Adapters Fit In

```
User ↔ Messaging Platform ↔ Platform Adapter ↔ Gateway Runner ↔ AIAgent
```

Every adapter extends `BasePlatformAdapter` from `gateway/platforms/base.py` and implements five methods:

| Method | What it does |
|--------|-------------|
| `connect()` | Establish connection (WebSocket, long-poll, HTTP server, etc.) |
| `disconnect()` | Clean shutdown |
| `send()` | Send a text message to a chat |
| `send_typing()` | Show typing indicator (optional) |
| `get_chat_info()` | Return chat metadata |

Inbound messages flow through `self.handle_message(event)`, which the base class routes to the gateway runner.

## Step-by-Step Checklist

### 1. Platform Enum

Add your platform to `Platform` in `gateway/config.py`:

```python
class Platform(str, Enum):
    # ... existing platforms ...
    NEWPLAT = "newplat"
```

### 2. Adapter File

Create `gateway/platforms/newplat.py`:

```python
from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import (
    BasePlatformAdapter, MessageEvent, MessageType, SendResult,
)

def check_newplat_requirements() -> bool:
    """Return True if dependencies are available."""
    return SOME_SDK_AVAILABLE

class NewPlatAdapter(BasePlatformAdapter):
    def __init__(self, config: PlatformConfig):
        super().__init__(config, Platform.NEWPLAT)
        extra = config.extra or {}
        self._api_key = extra.get("api_key") or os.getenv("NEWPLAT_API_KEY", "")

    async def connect(self) -> bool:
        # Set up connection, start polling/webhook
        self._mark_connected()
        return True

    async def disconnect(self) -> None:
        self._running = False
        self._mark_disconnected()

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        return SendResult(success=True, message_id="...")

    async def get_chat_info(self, chat_id):
        return {"name": chat_id, "type": "dm"}
```

To forward inbound messages, build a `MessageEvent` and call `self.handle_message(event)`:

```python
source = self.build_source(
    chat_id=chat_id,
    chat_name=name,
    chat_type="dm",  # or "group"
    user_id=user_id,
    user_name=user_name,
)
event = MessageEvent(
    text=content,
    message_type=MessageType.TEXT,
    source=source,
    message_id=msg_id,
)
await self.handle_message(event)
```

### 3. Gateway Config (`gateway/config.py`)

Three touchpoints:

1. **`get_connected_platforms()`** — add a credentials check for your platform
2. **`load_gateway_config()`** — add token env map entry: `Platform.NEWPLAT: "NEWPLAT_TOKEN"`
3. **`_apply_env_overrides()`** — map all `NEWPLAT_*` env vars to config

### 4. Gateway Runner (`gateway/run.py`)

Six touchpoints:

1. **`_create_adapter()`** — add `elif platform == Platform.NEWPLAT:` branch
2. **`_is_user_authorized()` allowed_users map** — `Platform.NEWPLAT: "NEWPLAT_ALLOWED_USERS"`
3. **`_is_user_authorized()` allow_all map** — `Platform.NEWPLAT: "NEWPLAT_ALLOW_ALL_USERS"`
4. **Early env check `_any_allowlist` tuple** — add `"NEWPLAT_ALLOWED_USERS"`
5. **Early env check `_allow_all` tuple** — add `"NEWPLAT_ALLOW_ALL_USERS"`
6. **`_UPDATE_ALLOWED_PLATFORMS` frozenset** — add `Platform.NEWPLAT`

### 5. Cross-Platform Delivery

1. **`gateway/platforms/webhook.py`** — add `"newplat"` to the delivery type tuple
2. **`cron/scheduler.py`** — add to `_KNOWN_DELIVERY_PLATFORMS` frozenset and `_deliver_result()` platform map

### 6. CLI Integration

1. **`spark_cli/config.py`** — add all `NEWPLAT_*` vars to `_EXTRA_ENV_KEYS`
2. **`spark_cli/gateway.py`** — add entry to `_PLATFORMS` list with key, label, emoji, token_var, setup_instructions, and vars
3. **`spark_cli/platforms.py`** — add `PlatformInfo` entry with label and default_toolset
4. **`spark_cli/setup.py`** — add `_setup_newplat()` function and tuple to the messaging platforms list
5. **`spark_cli/status.py`** — add detection entry: `"NewPlat": ("NEWPLAT_TOKEN", "NEWPLAT_HOME_CHANNEL")`
6. **`spark_cli/dump.py`** — add `"newplat": "NEWPLAT_TOKEN"` to platform detection dict

### 7. Tools

1. **`tools/send_message_tool.py`** — add `"newplat": Platform.NEWPLAT` to platform map
2. **`tools/cronjob_tools.py`** — add `newplat` to the delivery target description string

### 8. Toolsets

1. **`toolsets.py`** — add `"spark-newplat"` toolset definition with `_SPARK_CORE_TOOLS`
2. **`toolsets.py`** — add `"spark-newplat"` to the `"spark-gateway"` includes list

### 9. Optional: Platform Hints

If your platform has specific rendering constraints (no markdown, message length limits, etc.), add an entry to `_PLATFORM_HINTS` in `agent/prompt_builder.py`. This injects platform-specific guidance into the system prompt:

```python
_PLATFORM_HINTS = {
    # ...
    "newplat": (
        "You are chatting via NewPlat. It supports markdown formatting "
        "but has a 4000-character message limit."
    ),
}
```

Not every platform needs a hint. Add one only when the agent's behavior should actively change.

### 10. Tests

Create `tests/gateway/test_newplat.py` covering:

- Adapter construction from config
- Message event building
- Send method (mock the external API)
- Platform-specific features (encryption, routing, etc.)

### 11. Documentation

| File | What to add |
|------|-------------|
| `docs/chat-platforms/newplat.md` | Full platform setup page |
| `docs/chat-platforms/index.md` | Platform comparison table, architecture diagram, toolsets table, security section, next-steps link |
| `docs/reference/environment-variables.md` | All NEWPLAT_* env vars |
| `docs/reference/toolsets-reference.md` | spark-newplat toolset |
| `docs/integrations/index.md` | Platform link |
| `docs/building/architecture.md` | Adapter count + listing |
| `docs/building/gateway-internals.md` | Adapter file listing |

## Parity Audit

Before marking a platform PR complete, verify you haven't missed anything:

```bash
# Files mentioning the reference platform
search_files "bluebubbles" output_mode="files_only" file_glob="*.py"

# Files mentioning your new platform
search_files "newplat" output_mode="files_only" file_glob="*.py"

# Anything in the first set but not the second is a potential gap
```

Repeat for `.md` and `.ts` files. For each gap, decide: is this a platform enumeration that needs updating, or a platform-specific reference you can skip?

## Common Patterns

### Long-Poll Adapters

If the platform uses long-polling (like Telegram or Weixin), run a background polling task:

```python
async def connect(self):
    self._poll_task = asyncio.create_task(self._poll_loop())
    self._mark_connected()

async def _poll_loop(self):
    while self._running:
        messages = await self._fetch_updates()
        for msg in messages:
            await self.handle_message(self._build_event(msg))
```

### Callback/Webhook Adapters

If the platform pushes messages to your endpoint (like WeCom Callback), run an HTTP server:

```python
async def connect(self):
    self._app = web.Application()
    self._app.router.add_post("/callback", self._handle_callback)
    # ... start aiohttp server
    self._mark_connected()

async def _handle_callback(self, request):
    event = self._build_event(await request.text())
    await self._message_queue.put(event)
    return web.Response(text="success")  # Acknowledge immediately
```

For platforms with tight response deadlines (WeCom's 5-second limit), always acknowledge immediately. Deliver the agent's reply via API later — agent sessions run 3–30 minutes, so inline replies within a callback window aren't feasible.

### Token Locks

If your adapter holds a persistent connection with a unique credential, use a scoped lock to prevent two profiles from using the same credential simultaneously:

```python
from gateway.status import acquire_scoped_lock, release_scoped_lock

async def connect(self):
    if not acquire_scoped_lock("newplat", self._token):
        logger.error("Token already in use by another profile")
        return False
    # ... connect

async def disconnect(self):
    release_scoped_lock("newplat", self._token)
```

## Reference Implementations

| Adapter | Pattern | Good reference for |
|---------|---------|-------------------|
| `bluebubbles.py` | REST + webhook | Simple REST API integration |
| `weixin.py` | Long-poll + CDN | Media handling, encryption |
| `wecom_callback.py` | Callback/webhook | HTTP server, AES crypto, multi-app |
| `telegram.py` | Long-poll + Bot API | Full-featured adapter with groups, threads |
