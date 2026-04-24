---
title: Browser Automation
description: Control browsers with multiple providers, local Chrome via CDP, or cloud browsers for web interaction, form filling, scraping, and more.
sidebar_label: Browser
sidebar_position: 5
---

# Browser Automation

Stop hand-coding scrapers. Spark can drive a real browser — clicking buttons, filling forms, handling dynamic content, solving CAPTCHAs — using the same tools the agent uses for everything else.

## Pick Your Backend

Six options, from cloud-managed to fully local:

| Backend | How It Works | Best For |
|---------|-------------|----------|
| **Browserbase** | Managed cloud Chrome with anti-bot features | Production scraping, CAPTCHA-heavy sites |
| **Browser Use** | Alternative cloud browser REST API | Browserbase alternative |
| **Firecrawl** | Cloud browser with built-in scraping pipeline | Content extraction at scale |
| **Camofox** | Local Firefox with fingerprint spoofing | Privacy-first, no cloud costs |
| **CDP (local Chrome)** | Attach to your running Chrome | Real-time observation, your own sessions |
| **agent-browser** | Local Chromium via npm package | Simple local use, no cloud account |

## How Pages Are Represented

Pages arrive as **accessibility trees** — text snapshots showing interactive elements as refs like `@e1`, `@e2`. The agent uses those refs to click, type, and navigate. Large pages (over 8,000 characters) are automatically summarized by an LLM.

## Setup

### Browserbase

```bash
# Add to ~/.spark/.env
BROWSERBASE_API_KEY=***
BROWSERBASE_PROJECT_ID=your-project-id-here
```

Get credentials at [browserbase.com](https://browserbase.com). If both Browserbase and Browser Use are configured, Browserbase wins.

Optional settings:

```bash
BROWSERBASE_PROXIES=true              # Residential proxies (default: true)
BROWSERBASE_ADVANCED_STEALTH=false    # Custom Chromium - Scale Plan required
BROWSERBASE_KEEP_ALIVE=true           # Reconnect on drops (paid plan)
BROWSERBASE_SESSION_TIMEOUT=600000    # Session timeout in ms
```

### Browser Use

```bash
# Add to ~/.spark/.env
BROWSER_USE_API_KEY=***
```

Get your key at [browser-use.com](https://browser-use.com).

### Firecrawl

```bash
# Add to ~/.spark/.env
FIRECRAWL_API_KEY=fc-***

# Optional
FIRECRAWL_API_URL=http://localhost:3002   # Self-hosted instance
FIRECRAWL_BROWSER_TTL=600                 # Session TTL in seconds (default: 300)
```

Get your key at [firecrawl.dev](https://firecrawl.dev), then select it:

```bash
spark setup tools
# -> Browser Automation -> Firecrawl
```

### Camofox (Local Anti-Detection Firefox)

[Camofox](https://github.com/jo-inc/camofox-browser) wraps Camoufox — a Firefox fork with C++ fingerprint spoofing — so you browse locally without cloud dependencies.

```bash
# Install and run
git clone https://github.com/jo-inc/camofox-browser && cd camofox-browser
npm install && npm start   # Downloads Camoufox (~300MB) on first run

# Or via Docker
docker run -d --network host -e CAMOFOX_PORT=9377 jo-inc/camofox-browser
```

Point Spark at your instance:

```bash
# ~/.spark/.env
CAMOFOX_URL=http://localhost:9377
```

Or configure interactively: `spark tools` -> Browser Automation -> Camofox.

**Persistent sessions** — by default, each session gets a fresh identity. To keep cookies and logins across restarts:

```yaml
# ~/.spark/config.yaml
browser:
  camofox:
    managed_persistence: true
```

:::note
The Camofox server must also be configured with `CAMOFOX_PROFILE_DIR` on the server side for persistence to work.
:::

**VNC live view** — when Camofox runs in headed mode, Spark automatically discovers the VNC port and includes a watch URL in navigation responses.

### Local Chrome via CDP

Attach Spark directly to your running Chrome. Useful when you want to watch the agent work in real-time, use your own cookies, or avoid cloud costs entirely.

```
/browser connect              # Connect to Chrome at ws://localhost:9222
/browser connect ws://host:port  # Custom endpoint
/browser status               # Check connection
/browser disconnect            # Return to cloud/local mode
```

If Chrome isn't already running with remote debugging, Spark will try to launch it automatically.

:::tip
To start Chrome manually:
```bash
# Linux
google-chrome --remote-debugging-port=9222

# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222
```
:::

### Local Browser (agent-browser)

No cloud credentials and no CDP? Spark falls back to a local Chromium install via the `agent-browser` npm package.

```bash
npm install -g agent-browser
```

### Inactivity & Cleanup

```bash
BROWSER_INACTIVITY_TIMEOUT=120   # Auto-close after N seconds idle (default: 120)
```

A background thread checks every 30 seconds for stale sessions. Emergency cleanup runs on process exit.

:::info
The `browser` toolset must be listed in your config's `toolsets` or enabled via `spark config set toolsets '["spark-cli", "browser"]'`.
:::

## Tools Reference

### `browser_navigate`

Open a URL. Must run before any other browser tool — initializes the session.

```
Navigate to https://github.com/trending
```

:::tip
For read-only content, `web_search` and `web_extract` are faster and cheaper. Use browser tools only when you need to **interact** with a page.
:::

### `browser_snapshot`

Get the accessibility tree of the current page. Returns ref IDs for all interactive elements.

- `full=false` (default) — compact view, interactive elements only
- `full=true` — full page content

### `browser_click`

Click an element by its ref ID.

```
Click @e5 to press the "Sign In" button
```

### `browser_type`

Type text into a field. Clears the field first, then types.

```
Type "spark agent" into @e3
```

### `browser_scroll`

Scroll the page to reveal more content.

### `browser_press`

Press a keyboard key: `Enter`, `Tab`, `Escape`, `ArrowDown`, `ArrowUp`, and more.

```
Press Enter to submit
```

### `browser_back`

Go back to the previous page.

### `browser_get_images`

List all images on the page with URLs and alt text.

### `browser_vision`

Take a screenshot and analyze it with vision AI. Best for CAPTCHAs, complex layouts, or anything the accessibility tree can't capture.

Screenshots save to `~/.spark/cache/screenshots/` and are cleaned up after 24 hours. On Telegram, Discord, Slack, and WhatsApp, the agent can send the screenshot as a native photo attachment.

```
What does the chart on this page show?
```

### `browser_console`

Read browser console output — logs, warnings, errors, and uncaught JS exceptions. Pass `clear=True` to reset after reading.

```
Check the browser console for JavaScript errors
```

## Worked Examples

### Sign Up Flow

```
User: Sign up on example.com with john@example.com

Agent:
1. browser_navigate("https://example.com/signup")
2. browser_snapshot()           -> sees form fields with refs
3. browser_type(@e3, "john@example.com")
4. browser_type(@e5, "SecurePass123")
5. browser_click(@e8)           -> "Create Account"
6. browser_snapshot()           -> confirms success
```

### Scrape Dynamic Content

```
User: What are the top trending repos on GitHub right now?

Agent:
1. browser_navigate("https://github.com/trending")
2. browser_snapshot(full=true)  -> reads the list
3. Returns formatted results
```

## Session Recording

Capture every session as a WebM video:

```yaml
browser:
  record_sessions: true   # default: false
```

Recording starts on the first `browser_navigate` and saves to `~/.spark/browser_recordings/` when the session closes. Works in both local and Browserbase modes. Files older than 72 hours are auto-deleted.

## Stealth Features (Browserbase)

| Feature | Default | Notes |
|---------|---------|-------|
| Basic Stealth | Always on | Random fingerprints, viewport randomization, CAPTCHA solving |
| Residential Proxies | On | Routes through residential IPs |
| Advanced Stealth | Off | Custom Chromium — Scale Plan required |
| Keep Alive | On | Session reconnection after drops |

:::note
If paid features aren't on your plan, Spark degrades gracefully — first drops `keepAlive`, then proxies. Free plans still work.
:::

## Limitations

- **Text-based** — relies on accessibility trees, not pixel coordinates
- **Page size** — snapshots over 8,000 characters get LLM-summarized
- **Session timeouts** — cloud sessions expire per your provider's plan
- **Cost** — cloud sessions consume provider credits. Use `/browser connect` for free local browsing
- **No file downloads** — can't download files from the browser
