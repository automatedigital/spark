# Spark OAuth Relay

A tiny first-party OAuth broker so self-hosted Spark instances on **arbitrary VPS
hosts** can do one-click Google connect without each user registering their own
OAuth client. The relay owns the single registered `redirect_uri` for a shared
Google OAuth client and brokers the flow back to whichever instance started it.

## Why this exists

Google requires every `redirect_uri` to be pre-registered exactly — impossible
for unknown self-host URLs. The device flow (no redirect) doesn't support Gmail/
Calendar scopes. So a shared-client one-click flow needs a relay with one fixed
callback. (Users who'd rather not depend on the relay can use the **bring-your-
own-client** path instead — see the Connectors tab setup helper.)

## Security properties

- The shared **`client_secret` never leaves the relay** — the relay performs the
  token exchange.
- **PKCE** verifier is generated and held on the relay (keyed by a signed
  `state`); it never travels with the browser.
- Tokens reach the instance via a **one-time, short-lived ticket** (`/claim`),
  not via the browser redirect.
- `state` is **HMAC-signed**; only relay-issued callbacks are honored.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/session` | Instance starts a flow (`{instance_callback, scopes?}`) → `{auth_url}` |
| GET  | `/callback` | Google redirects here; relay exchanges code → 302 to instance with `?ticket=` |
| POST | `/claim` | Instance redeems the one-time ticket → tokens |
| GET  | `/healthz` | Liveness + missing-config report |

## Configuration (environment variables)

| Var | Required | Description |
|-----|----------|-------------|
| `RELAY_GOOGLE_CLIENT_ID` | ✓ | Shared OAuth client ID (type: **Web application**) |
| `RELAY_GOOGLE_CLIENT_SECRET` | ✓ | Shared OAuth client secret |
| `RELAY_SIGNING_SECRET` | ✓ | Random secret for signing `state` (`openssl rand -hex 32`) |
| `RELAY_REDIRECT_URI` | ✓ | The relay's own public callback, e.g. `https://auth.yourdomain.com/callback` |
| `RELAY_SCOPES` | — | Comma-separated scope override. Defaults to send-only/sensitive (no CASA). |

## Setup

1. Create **one** Google OAuth client (type **Web application**) in the Spark
   project's Google Cloud project.
2. Register `https://auth.yourdomain.com/callback` as its Authorized redirect URI.
3. Deploy this service (see `Dockerfile`) behind TLS at that domain.
4. Point Spark instances at it: set `connectors.google.relay_url:
   https://auth.yourdomain.com` in `config.yaml` (instance-side wiring).

## Scopes & verification

Default scopes are **send-only / sensitive** (Gmail send, Drive.file, Calendar,
Docs, Sheets, Slides) — free, no CASA. To let the shared client **read Gmail**,
the Spark OAuth app must pass Google verification + the annual CASA assessment;
then add `gmail.modify`/`gmail.readonly` to `RELAY_SCOPES`.

## Run locally

```bash
RELAY_GOOGLE_CLIENT_ID=... RELAY_GOOGLE_CLIENT_SECRET=... \
RELAY_SIGNING_SECRET=$(openssl rand -hex 32) \
RELAY_REDIRECT_URI=http://localhost:8088/callback \
uvicorn spark_relay.app:app --port 8088
```
