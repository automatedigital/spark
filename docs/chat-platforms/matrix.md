---
sidebar_position: 9
title: "Matrix"
description: "Set up Spark Agent as a Matrix bot"
---

# Matrix

Run Spark as a bot on Matrix — the open, federated messaging protocol. You keep full control of your communications whether you run your own homeserver (Synapse, Conduit, Dendrite) or use a public one like matrix.org.

Spark connects via the `mautrix` Python SDK and handles text, file attachments, images, audio, video, and optional end-to-end encryption. It works with any spec-compliant Matrix homeserver.

## How Spark Behaves Once Connected

| Context | Behavior |
|---------|----------|
| **DMs** | Spark responds to every message. No `@mention` needed. Each DM has its own session. Set `MATRIX_DM_MENTION_THREADS=true` to start a thread when the bot is `@mentioned` in a DM. |
| **Rooms** | Spark requires an `@mention` by default. Set `MATRIX_REQUIRE_MENTION=false` or add room IDs to `MATRIX_FREE_RESPONSE_ROOMS` to remove that requirement. Room invites are auto-accepted. |
| **Threads** | Spark supports Matrix threads (MSC3440). Replying in a thread keeps context isolated from the main room timeline. Threads where the bot already participated don't require a mention. |
| **Auto-threading** | By default, Spark creates a thread for each response in a room. Set `MATRIX_AUTO_THREAD=false` to disable. |
| **Shared rooms** | By default, each user in a shared room gets their own isolated session history. Two people in the same room don't share a transcript unless you explicitly disable this. |

:::tip
The bot automatically joins rooms when invited. Just invite it and it starts responding.
:::

## Session Isolation

By default, each DM, thread, and user in a shared room gets their own session. This is controlled by `config.yaml`:

```yaml
group_sessions_per_user: true
```

Set it to `false` only if you want one shared conversation for the entire room:

```yaml
group_sessions_per_user: false
```

Shared sessions are useful for collaborative rooms, but come with tradeoffs:

- Users share context growth and token costs
- One person's long tool-heavy task bloats everyone else's context
- One in-flight run can interrupt another person's follow-up

## Configure Mention and Threading Behavior

You can tune these via environment variables or `config.yaml`:

```yaml
matrix:
  require_mention: true           # Require @mention in rooms (default: true)
  free_response_rooms:            # Rooms exempt from mention requirement
    - "!abc123:matrix.org"
  auto_thread: true               # Auto-create threads for responses (default: true)
  dm_mention_threads: false       # Create thread when @mentioned in DM (default: false)
```

Or via environment variables:

```bash
MATRIX_REQUIRE_MENTION=true
MATRIX_FREE_RESPONSE_ROOMS=!abc123:matrix.org,!def456:matrix.org
MATRIX_AUTO_THREAD=true
MATRIX_DM_MENTION_THREADS=false
```

:::note
If you're upgrading from a version without `MATRIX_REQUIRE_MENTION`, the bot previously responded to all room messages. To keep that behavior, set `MATRIX_REQUIRE_MENTION=false`.
:::

## Step 1: Create a Bot Account

You need a Matrix user account for the bot. Three options:

### Option A: Register on Your Homeserver (Recommended)

If you run your own homeserver (Synapse, Conduit, Dendrite):

```bash
# Synapse example
register_new_matrix_user -c /etc/synapse/homeserver.yaml http://localhost:8008
```

Pick a username like `spark` — the full user ID will be `@spark:your-server.org`.

### Option B: Use matrix.org or Another Public Homeserver

1. Go to [Element Web](https://app.element.io) and create a new account
2. Pick a username for the bot (e.g., `spark-bot`)

### Option C: Use Your Own Account

Run Spark as yourself. The bot posts as you — useful for a personal assistant setup.

## Step 2: Get an Access Token

### Option A: Access Token (Recommended)

**Via Element:**
1. Log in to [Element](https://app.element.io) with the bot account
2. Go to **Settings** -> **Help & About**
3. Expand **Advanced** — the access token is shown there
4. Copy it immediately

**Via the API:**

```bash
curl -X POST https://your-server/_matrix/client/v3/login \
  -H "Content-Type: application/json" \
  -d '{
    "type": "m.login.password",
    "user": "@spark:your-server.org",
    "password": "your-password"
  }'
```

Copy the `access_token` field from the response.

:::warning[Keep your access token safe]
The access token gives full access to the bot's Matrix account. Never share it publicly or commit it to Git. If compromised, revoke it by logging out all sessions for that user.
:::

### Option B: Password Login

Instead of a token, give Spark the bot's user ID and password. Spark logs in automatically on startup. Simpler, but the password lives in your `.env` file.

```bash
MATRIX_USER_ID=@spark:your-server.org
MATRIX_PASSWORD=your-password
```

## Step 3: Find Your Matrix User ID

Spark uses your Matrix User ID to control who can interact with the bot. Format: `@username:server`.

To find yours: open [Element](https://app.element.io), click your avatar -> **Settings**. Your User ID appears at the top of the profile page.

:::tip
Matrix User IDs always start with `@` and contain `:` followed by the server name. Example: `@alice:matrix.org`.
:::

## Step 4: Configure Spark

### Option A: Interactive Setup (Recommended)

```bash
spark gateway setup
```

Select **Matrix** when prompted. Provide your homeserver URL, access token (or user ID + password), and allowed user IDs.

### Option B: Manual Configuration

**Using an access token:**

```bash
# Required
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_ACCESS_TOKEN=***

# Optional: user ID (auto-detected from token if omitted)
# MATRIX_USER_ID=@spark:matrix.example.org

# Restrict who can interact with the bot
MATRIX_ALLOWED_USERS=@alice:matrix.example.org

# Multiple allowed users (comma-separated)
# MATRIX_ALLOWED_USERS=@alice:matrix.example.org,@bob:matrix.example.org
```

**Using password login:**

```bash
# Required
MATRIX_HOMESERVER=https://matrix.example.org
MATRIX_USER_ID=@spark:matrix.example.org
MATRIX_PASSWORD=***

# Security
MATRIX_ALLOWED_USERS=@alice:matrix.example.org
```

Optional in `~/.spark/config.yaml`:

```yaml
group_sessions_per_user: true
```

### Start the Gateway

```bash
spark gateway
```

The bot connects and starts syncing within seconds. Send it a DM or message it in a room to test.

:::tip
Run `spark gateway` as a systemd service for persistent operation. See the deployment docs for details.
:::

## End-to-End Encryption (E2EE)

Spark supports Matrix E2EE so you can chat in encrypted rooms.

### Install the Requirements

```bash
# Install mautrix with E2EE support
pip install 'mautrix[encryption]'

# Or install with spark extras
pip install 'spark-agent[matrix]'
```

You also need `libolm` on your system:

```bash
# Debian/Ubuntu
sudo apt install libolm-dev

# macOS
brew install libolm

# Fedora
sudo dnf install libolm-devel
```

### Enable E2EE

```bash
MATRIX_ENCRYPTION=true
```

When enabled, Spark stores encryption keys in `~/.spark/platforms/matrix/store/`, uploads device keys on first connection, and handles encrypt/decrypt automatically.

### Cross-Signing Verification (Recommended)

If your Matrix account uses cross-signing (the default in Element), provide your recovery key so the bot can self-sign its device on startup. Without this, other clients may refuse to share encryption sessions after a key rotation.

```bash
MATRIX_RECOVERY_KEY=EsT... your recovery key here
```

Find it in Element under **Settings** -> **Security & Privacy** -> **Encryption**. This is the key you saved when first setting up cross-signing.

Spark imports cross-signing keys from the homeserver's secure secret storage on each startup when this key is set. It's idempotent — safe to leave enabled permanently.

:::warning
Deleting `~/.spark/platforms/matrix/store/` removes the bot's encryption keys. You'll need to re-verify the device in your Matrix client. Back up this directory to preserve encrypted sessions.
:::

:::info
If `mautrix[encryption]` or `libolm` is missing, the bot falls back to plain (unencrypted) mode automatically with a warning in the logs.
:::

## Set a Home Room

Designate a home room for proactive messages — cron output, reminders, notifications.

### Using a Slash Command

Type `/sethome` in any room where the bot is present.

### Manual Configuration

```bash
MATRIX_HOME_ROOM=!abc123def456:matrix.example.org
```

:::tip
To find a Room ID in Element: go to the room -> **Settings** -> **Advanced** -> **Internal room ID** (starts with `!`).
:::

## Troubleshooting

### Bot is not responding

**Cause:** The bot hasn't joined the room, or your User ID isn't in `MATRIX_ALLOWED_USERS`.

**Fix:** Invite the bot to the room — it auto-joins. Verify your User ID uses the full `@user:server` format. Restart the gateway.

### "Failed to authenticate" / "whoami failed" on startup

**Cause:** Wrong access token or homeserver URL.

**Fix:** Verify `MATRIX_HOMESERVER` includes `https://` with no trailing slash. Test your token directly:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-server/_matrix/client/v3/account/whoami
```

A valid token returns your user info. An error means you need a new token.

### "mautrix not installed" error

```bash
pip install 'mautrix[encryption]'
# Or:
pip install 'spark-agent[matrix]'
```

### Encryption errors / "could not decrypt event"

1. Verify `libolm` is installed (see the E2EE section above)
2. Confirm `MATRIX_ENCRYPTION=true` is set
3. In Element, go to the bot's profile -> Sessions -> verify/trust the bot's device
4. The bot can only decrypt messages sent *after* it joined an encrypted room — older messages are inaccessible

### Upgrading from a Previous Version with E2EE

If you had a working E2EE setup with an older Spark version, the encryption identity may have changed. Your Matrix client may cache the old device keys and refuse to share sessions with the bot.

**Symptoms:** The bot shows "E2EE enabled" in logs but all messages show "could not decrypt event" and the bot never responds.

**What's happening:** The old encryption state (from a previous `matrix-nio` or serialization-based `mautrix` backend) is incompatible with the new SQLite crypto store. The bot creates a fresh identity, but your client cached old keys and treats the change as suspicious. This is a Matrix security feature.

**One-time migration:**

1. **Get a new access token** (new token = new device ID):

   ```bash
   curl -X POST https://your-server/_matrix/client/v3/login \
     -H "Content-Type: application/json" \
     -d '{
       "type": "m.login.password",
       "identifier": {"type": "m.id.user", "user": "@spark:your-server.org"},
       "password": "***",
       "initial_device_display_name": "Spark Agent"
     }'
   ```

   Update `MATRIX_ACCESS_TOKEN` in `~/.spark/.env` with the new token.

2. **Delete old encryption state:**

   ```bash
   rm -f ~/.spark/platforms/matrix/store/crypto.db
   rm -f ~/.spark/platforms/matrix/store/crypto_store.*
   ```

3. **Set your recovery key** so Element trusts the new device immediately:

   ```bash
   MATRIX_RECOVERY_KEY=EsT... your recovery key here
   ```

4. **Force Element to rotate the encryption session.** In the DM room with the bot, type `/discardsession`.

5. **Restart the gateway:**

   ```bash
   spark gateway run
   ```

   You should see `Matrix: cross-signing verified via recovery key` in the logs.

6. **Send a new message.** The bot should decrypt and respond normally.

:::note
Messages sent before the upgrade cannot be decrypted — the old keys are gone. Only new messages are affected going forward.
:::

:::tip
New installations are not affected. This migration only applies if you had a working E2EE setup with a previous Spark version.

Why a new access token? Each Matrix token is bound to a specific device ID. Reusing the same device ID with new keys makes other clients distrust it. A fresh token gets a clean device ID with no stale key history.
:::

### Sync issues / bot falls behind

**Cause:** Long tool executions can delay the sync loop, or your homeserver is slow.

**Fix:** The sync loop retries every 5 seconds on error. If the bot consistently falls behind, check that your homeserver has adequate resources.

### Bot is offline

**Cause:** The gateway isn't running or failed to connect.

**Fix:** Check that `spark gateway` is running. Look at terminal output for errors. Common causes: wrong homeserver URL, expired token, homeserver unreachable.

### "User not allowed" / Bot ignores you

**Cause:** Your User ID isn't in `MATRIX_ALLOWED_USERS`.

**Fix:** Add your full `@user:server` ID to `MATRIX_ALLOWED_USERS` in `~/.spark/.env` and restart the gateway.

## Security

:::warning
Always set `MATRIX_ALLOWED_USERS`. Without it, the gateway denies all users by default. Only add User IDs of people you trust — authorized users get full access to the agent's capabilities, including tool use and system access.
:::

## Notes

- **Any homeserver:** Works with Synapse, Conduit, Dendrite, matrix.org, or any spec-compliant homeserver.
- **Federation:** If your homeserver is federated, the bot can communicate with users from other servers — just add their full `@user:server` IDs to `MATRIX_ALLOWED_USERS`.
- **Auto-join:** The bot accepts all room invites and starts responding immediately.
- **Media support:** Spark sends and receives images, audio, video, and file attachments via the Matrix content repository API.
- **Native voice messages (MSC3245):** Outgoing TTS and voice audio are tagged with `org.matrix.msc3245.voice`, rendering as native voice bubbles in Element and other MSC3245-compatible clients. Incoming voice messages are correctly identified and routed to speech-to-text. No configuration needed.
