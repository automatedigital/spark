# Preview Browser — Credential Storage & Threat Model

The preview pane runs a real browser so external sites (and logins) work. This
note documents where credentials live and what protects them.

## Where credentials are stored

| Path | Store | Contents |
|------|-------|----------|
| **macOS app (native)** | WKWebView data store, partitioned per workspace via `data_store_identifier` (derived from the workspace slug) | cookies, localStorage, IndexedDB |
| **WebUI (streamed)** | Chromium persistent profile at `SPARK_HOME/browser/<slug>/persistent` | cookies, localStorage, IndexedDB, cache |
| **Spark-managed secrets** | OS keychain via `keyring` (`secret_store.py`), service `spark-preview:<slug>` | any tokens/credentials Spark itself stores — never the browser's own jar |

Ephemeral ("private") sessions use WKWebView `incognito` / a throwaway
`SPARK_HOME/browser/<slug>/ephemeral` profile and persist nothing.

## At-rest protection

- **Cookie encryption:** On macOS, Chromium encrypts the cookie database with a
  random key stored in the login Keychain ("Chrome Safe Storage"); WKWebView
  stores live in the app's sandbox container. Spark relies on these
  platform-provided mechanisms — it does not roll its own cookie encryption.
- **Directory permissions:** Spark sets the streamed profile directory to `0700`
  (owner-only) so other local users cannot read it.
- **Per-workspace isolation:** Native uses a distinct data-store identifier per
  slug; streamed uses a distinct profile directory per slug. There is no shared
  cookie jar across workspaces.
- **Spark-managed secrets** never touch disk in plaintext — they go to the OS
  keychain.

## Threat model

In scope (mitigated):
- **Cross-workspace credential leakage** — prevented by per-slug partitioning.
- **Casual disk inspection / other local users** — mitigated by `0700`
  permissions and platform cookie encryption.
- **Plaintext secret sprawl** — Spark-managed secrets are keychain-only.

Out of scope (not mitigated by Spark):
- **A compromised user account / root** — anyone who can run code as the user can
  read the login Keychain and the live browser session; this is inherent to any
  local browser.
- **Full-disk encryption** — that's the user's OS responsibility (FileVault).
- **Malicious sites** — the non-loopback navigation confirm reduces silent
  agent-driven navigation, but sites are otherwise trusted as in any browser.
