---
sidebar_position: 13
title: "Webhooks"
description: "Receive events from GitHub, GitLab, and other services to trigger Spark agent runs"
---

# Trigger Spark from Webhooks

Connect GitHub, GitLab, JIRA, Stripe, or any service that sends webhooks. When an event arrives, Spark runs the agent against the payload and delivers the response wherever you want — a PR comment, a Telegram message, a Slack channel, or a log line.

The webhook adapter runs an HTTP server, validates HMAC signatures, renders your prompt template with data from the payload, and routes the agent's response to the target you specify.

---

## Quick Start

```bash
# 1. Enable webhooks
spark gateway setup   # or set WEBHOOK_ENABLED=true in .env

# 2. Define a route in config.yaml (or create one dynamically)
spark webhook subscribe my-route ...

# 3. Point your service at the endpoint
http://your-server:8644/webhooks/<route-name>
```

---

## Enable the Adapter

### Option A: Setup wizard

```bash
spark gateway setup
```

Follow the prompts to enable webhooks, set the port, and configure a global HMAC secret.

### Option B: Environment variables

```bash
# Add to ~/.spark/.env
WEBHOOK_ENABLED=true
WEBHOOK_PORT=8644        # default
WEBHOOK_SECRET=your-global-secret
```

### Verify it's running

```bash
curl http://localhost:8644/health
# {"status": "ok", "platform": "webhook"}
```

---

## Define Routes {#configuring-routes}

Routes live under `platforms.webhook.extra.routes` in `~/.spark/config.yaml`. Each named route maps an incoming webhook to an agent prompt and a delivery target.

### Route properties

| Property | Required | Description |
|----------|----------|-------------|
| `events` | No | Event types to accept (e.g. `["pull_request"]`). Reads from `X-GitHub-Event`, `X-GitLab-Event`, or `event_type` in the payload. Empty = accept all. |
| `secret` | Yes | HMAC secret for this route. Falls back to the global `secret`. Use `"INSECURE_NO_AUTH"` for testing only. |
| `prompt` | No | Template with dot-notation access to payload fields (e.g. `{pull_request.title}`). Omit to dump the full JSON payload. |
| `skills` | No | Skills to load for the agent run. |
| `deliver` | No | Where to send the response. See [Delivery Options](#delivery-options). Defaults to `log`. |
| `deliver_extra` | No | Extra delivery config (e.g. `repo`, `pr_number`, `chat_id`). Supports the same `{dot.notation}` templates as `prompt`. |

### Full example

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      port: 8644
      secret: "global-fallback-secret"
      routes:
        github-pr:
          events: ["pull_request"]
          secret: "github-webhook-secret"
          prompt: |
            Review this pull request:
            Repository: {repository.full_name}
            PR #{number}: {pull_request.title}
            Author: {pull_request.user.login}
            URL: {pull_request.html_url}
            Diff URL: {pull_request.diff_url}
            Action: {action}
          skills: ["github-code-review"]
          deliver: "github_comment"
          deliver_extra:
            repo: "{repository.full_name}"
            pr_number: "{number}"
        deploy-notify:
          events: ["push"]
          secret: "deploy-secret"
          prompt: "New push to {repository.full_name} branch {ref}: {head_commit.message}"
          deliver: "telegram"
```

### Prompt templates

Use dot-notation to pull values out of the webhook payload:

- `{pull_request.title}` → `payload["pull_request"]["title"]`
- `{repository.full_name}` → `payload["repository"]["full_name"]`
- `{__raw__}` → dumps the **entire payload** as indented JSON, truncated at 4000 characters
- Missing keys stay as the literal `{key}` string — no error thrown
- Nested dicts and lists are JSON-serialized and truncated at 2000 characters

Mix `{__raw__}` with specific fields:

```yaml
prompt: "PR #{pull_request.number} by {pull_request.user.login}: {__raw__}"
```

The same dot-notation works in `deliver_extra` values.

### Delivering to a Telegram forum topic

Target a specific forum topic by adding `message_thread_id` (or `thread_id`) to `deliver_extra`:

```yaml
webhooks:
  routes:
    alerts:
      events: ["alert"]
      prompt: "Alert: {__raw__}"
      deliver: "telegram"
      deliver_extra:
        chat_id: "-1001234567890"
        message_thread_id: "42"
```

If `chat_id` is omitted, Spark falls back to the home channel for that platform.

---

## GitHub PR Review Walkthrough {#github-pr-review}

Get automatic code review posted as a PR comment every time a pull request opens.

### 1. Create the webhook in GitHub

1. Go to your repo → **Settings** → **Webhooks** → **Add webhook**
2. Set **Payload URL** to `http://your-server:8644/webhooks/github-pr`
3. Set **Content type** to `application/json`
4. Set **Secret** to match your route config (e.g. `github-webhook-secret`)
5. Select **Let me select individual events** → check **Pull requests**
6. Click **Add webhook**

### 2. Add the route to config.yaml

Use the `github-pr` route from the [full example](#configuring-routes) above.

### 3. Authenticate the gh CLI

```bash
gh auth login
```

### 4. Open a pull request

That's it. The webhook fires, Spark processes the event, and a review comment appears on the PR.

---

## GitLab Setup {#gitlab-webhook-setup}

GitLab uses a different auth mechanism: it sends the secret as a plain `X-Gitlab-Token` header (exact string match, not HMAC).

### 1. Create the webhook in GitLab

1. Go to your project → **Settings** → **Webhooks**
2. Set **URL** to `http://your-server:8644/webhooks/gitlab-mr`
3. Enter your **Secret token**
4. Select **Merge request events**
5. Click **Add webhook**

### 2. Add the route

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      routes:
        gitlab-mr:
          events: ["merge_request"]
          secret: "your-gitlab-secret-token"
          prompt: |
            Review this merge request:
            Project: {project.path_with_namespace}
            MR !{object_attributes.iid}: {object_attributes.title}
            Author: {object_attributes.last_commit.author.name}
            URL: {object_attributes.url}
            Action: {object_attributes.action}
          deliver: "log"
```

---

## Delivery Options {#delivery-options}

The `deliver` field controls where the agent's response goes after processing the event.

| Value | What it does |
|-------|-------------|
| `log` | Logs the response to gateway output. Default. Useful for testing. |
| `github_comment` | Posts as a PR/issue comment via the `gh` CLI. Needs `deliver_extra.repo` and `deliver_extra.pr_number`. Run `gh auth login` first. |
| `telegram` | Sends to Telegram. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `discord` | Sends to Discord. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `slack` | Sends to Slack. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `signal` | Sends to Signal. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `sms` | Sends via Twilio SMS. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `whatsapp` | Sends to WhatsApp. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `matrix` | Sends to Matrix. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `mattermost` | Sends to Mattermost. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `homeassistant` | Sends to Home Assistant. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `email` | Sends via email. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `dingtalk` | Sends to DingTalk. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `feishu` | Sends to Feishu/Lark. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `wecom` | Sends to WeCom. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `weixin` | Sends to Weixin (WeChat). Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `bluebubbles` | Sends to BlueBubbles (iMessage). Uses the home channel, or specify `chat_id` in `deliver_extra`. |

The target platform must be enabled and connected in your gateway. If no `chat_id` is in `deliver_extra`, the response goes to that platform's home channel.

---

## Dynamic Subscriptions {#dynamic-subscriptions}

Don't want to edit `config.yaml` every time? Create subscriptions on the fly from the CLI — or let the agent create them for you.

### Create a subscription

```bash
spark webhook subscribe github-issues \
  --events "issues" \
  --prompt "New issue #{issue.number}: {issue.title}\nBy: {issue.user.login}\n\n{issue.body}" \
  --deliver telegram \
  --deliver-chat-id "-100123456789" \
  --description "Triage new GitHub issues"
```

This prints the webhook URL and an auto-generated HMAC secret. Point your service at that URL.

### Manage subscriptions

```bash
spark webhook list                  # See all active subscriptions
spark webhook remove github-issues  # Remove one
```

### Test a subscription

```bash
spark webhook test github-issues
spark webhook test github-issues --payload '{"issue": {"number": 42, "title": "Test"}}'
```

### How dynamic subscriptions work

- Stored in `~/.spark/webhook_subscriptions.json`
- The adapter hot-reloads this file on each request (mtime-gated, negligible overhead)
- Static routes from `config.yaml` always take precedence over dynamic ones with the same name
- No gateway restart required — subscribe and it's immediately active

### Agent-driven subscriptions

Ask the agent: "Set up a webhook for GitHub issues." With the `webhook-subscriptions` skill loaded, it will run `spark webhook subscribe` and wire everything up.

---

## Security {#security}

### Signature validation

The adapter validates every incoming request using the right method for each source:

| Source | Header | Method |
|--------|--------|--------|
| GitHub | `X-Hub-Signature-256` | HMAC-SHA256 hex digest prefixed with `sha256=` |
| GitLab | `X-Gitlab-Token` | Plain secret string match |
| Generic | `X-Webhook-Signature` | Raw HMAC-SHA256 hex digest |

Requests with no recognized signature header are rejected when a secret is configured.

Every route needs a secret — set on the route itself or inherited from the global `secret`. Routes without a secret cause startup failure. Use `"INSECURE_NO_AUTH"` only during development.

### Rate limiting

Each route allows **30 requests per minute** by default (fixed-window). Requests over the limit get a `429` response.

Adjust globally:

```yaml
platforms:
  webhook:
    extra:
      rate_limit: 60  # requests per minute
```

### Idempotency

Delivery IDs from `X-GitHub-Delivery`, `X-Request-ID`, or a timestamp fallback are cached for **1 hour**. Duplicate webhook deliveries are silently acknowledged with a `200` — no duplicate agent runs.

### Body size limits

Payloads over **1 MB** are rejected before the body is read. Adjust:

```yaml
platforms:
  webhook:
    extra:
      max_body_bytes: 2097152  # 2 MB
```

### Prompt injection

:::warning
Webhook payloads contain attacker-controlled data — PR titles, commit messages, issue bodies. Any of these could contain malicious instructions. Run the gateway in a sandboxed environment (Docker, VM) when it's exposed to the internet. Use the Docker or SSH terminal backend for isolation.
:::

---

## Troubleshooting {#troubleshooting}

| Problem | Fix |
|---------|-----|
| Webhook not arriving | Confirm the port is open and the URL path matches: `http://your-server:8644/webhooks/<route-name>`. Use `/health` to confirm the server is up. |
| Signature validation failing | Make sure the route secret exactly matches what's in the webhook source. Check gateway logs for `Invalid signature`. |
| Event being ignored | Verify the event type is in your route's `events` list. Empty `events` accepts everything. |
| Agent not responding | Run `spark gateway run` in the foreground to see logs. Check prompt template and delivery target config. |
| Duplicate responses | Confirm the webhook source sends a delivery ID header — the idempotency cache requires one. |
| `gh` CLI errors on GitHub comment delivery | Run `gh auth login` and verify the authenticated user has write access to the repo. |

---

## Environment Variables {#environment-variables}

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBHOOK_ENABLED` | Enable the webhook platform adapter | `false` |
| `WEBHOOK_PORT` | HTTP server port for receiving webhooks | `8644` |
| `WEBHOOK_SECRET` | Global HMAC secret (fallback when routes don't specify their own) | _(none)_ |
