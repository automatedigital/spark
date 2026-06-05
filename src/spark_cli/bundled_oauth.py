"""Bundled Google OAuth client for the desktop app (one-click connect).

The desktop app ships with a single shared **Desktop-type** Google OAuth client
so users can connect with one click — no per-user Google Cloud setup. This is
safe because Google treats a Desktop client's secret as **non-confidential by
design** (security comes from PKCE + the localhost loopback redirect).

Scope of use (deliberately narrow):
  * Only applied on **local/desktop** installs — never on a server/VPS, where a
    bundled localhost client wouldn't work anyway and BYO credentials are
    required. The gate is ``is_server_environment()`` in ``google_connector``.
  * Acts only as a **fallback**: an explicit env var or ``config.yaml`` client
    always takes precedence (so a user can still BYO on desktop).

Filling in the real credentials (maintainers): create a Desktop OAuth client in
the Spark project's Google Cloud project and either
  (a) set the constants below at build time, or
  (b) export ``SPARK_DESKTOP_GOOGLE_CLIENT_ID`` / ``SPARK_DESKTOP_GOOGLE_CLIENT_SECRET``
      when packaging the desktop bundle.
Leaving them empty simply means desktop has no bundled client (users BYO).
"""

from __future__ import annotations

import os

# Filled in at build/release time for the desktop bundle. Empty by default so
# source checkouts and the server build have no bundled client.
BUNDLED_GOOGLE_CLIENT_ID = ""
BUNDLED_GOOGLE_CLIENT_SECRET = ""


def get_bundled_client() -> tuple[str, str]:
    """Return (client_id, client_secret) for the bundled desktop client.

    Env vars override the baked-in constants so the desktop packaging step can
    inject credentials without editing source. Returns ("", "") when none is
    configured.
    """
    client_id = os.environ.get("SPARK_DESKTOP_GOOGLE_CLIENT_ID") or BUNDLED_GOOGLE_CLIENT_ID
    client_secret = (
        os.environ.get("SPARK_DESKTOP_GOOGLE_CLIENT_SECRET") or BUNDLED_GOOGLE_CLIENT_SECRET
    )
    return client_id, client_secret


def has_bundled_client() -> bool:
    cid, csecret = get_bundled_client()
    return bool(cid and csecret)
