"""Spark OAuth Relay — a tiny first-party broker for one-click connectors.

Self-hosted Spark instances live on arbitrary VPS hosts whose URLs can't be
pre-registered with Google. This relay solves that: it owns the single
registered ``redirect_uri`` for a shared OAuth client and brokers the flow back
to whichever instance started it.

Flow (token-safe — the shared client_secret never leaves the relay, and tokens
reach the relay only transiently):

    instance  --POST /session {instance_callback}-->  relay
              <--{auth_url}---------------------------
    browser   --opens auth_url, user consents-->  Google
    Google    --GET /callback?code&state------->  relay   (exchanges code)
    relay     --302 instance_callback?ticket=...-->  browser → instance
    instance  --POST /claim {ticket}---------->  relay
              <--{tokens}-------------------------  (one-time)

Deploy as a container; see ``Dockerfile`` and ``README.md`` in this package.
Configuration is via environment variables (see ``app.config_from_env``).
"""

from spark_relay.crypto import sign_state, verify_state
from spark_relay.store import TTLStore

__all__ = ["sign_state", "verify_state", "TTLStore"]
