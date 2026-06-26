---
sidebar_position: 5
title: "Adding Providers"
description: "How to add a new inference provider to Spark Agent - auth, runtime resolution, CLI flows, adapters, tests, and docs"
---

# Adding Providers

Before you start: Spark already talks to any OpenAI-compatible endpoint through the custom provider path. Adding a built-in provider only makes sense when you need first-class treatment — provider-specific auth, a curated model catalog, setup wizard entries, `provider:model` shorthand syntax, or a non-OpenAI API shape that needs an adapter.

If the service is just "another OpenAI-compatible base URL and API key", a named custom provider is probably enough.

## Two Implementation Paths

### Path A — OpenAI-compatible provider

The provider accepts standard chat-completions requests. You add auth metadata, a model catalog, runtime resolution, and CLI wiring. No new adapter or `api_mode` needed.

### Path B — Native provider

The provider has its own protocol (like Anthropic Messages or OpenAI Codex Responses). Path B includes everything in Path A, plus a new adapter file and branches in `run_agent.py`.

Existing native providers in the codebase: `codex_responses`, `anthropic_messages`.

## How the Layers Connect

A built-in provider must be consistent across all five of these:

1. `spark_cli/auth.py` — decides how credentials are found
2. `spark_cli/runtime_provider.py` — turns credentials into runtime data: `provider`, `api_mode`, `base_url`, `api_key`, `source`
3. `run_agent.py` — uses `api_mode` to build and send requests
4. `spark_cli/models.py` and `spark_cli/main.py` — make the provider show up in menus and `provider:model` syntax
5. `agent/auxiliary_client.py` and `agent/model_metadata.py` — keep side tasks and token budgeting working

## File Checklist

### Every built-in provider needs these

1. `spark_cli/auth.py`
2. `spark_cli/models.py`
3. `spark_cli/runtime_provider.py`
4. `spark_cli/main.py`
5. `agent/auxiliary_client.py`
6. `agent/model_metadata.py`
7. Tests
8. User-facing docs under `docs/`

:::tip
`spark_cli/setup.py` does **not** need changes. The setup wizard delegates provider and model selection to `select_provider_and_model()` in `main.py` — any provider added there appears in both `spark model` and `spark setup` automatically.
:::

### Native providers additionally need

9. `agent/<provider>_adapter.py`
10. `run_agent.py`
11. `pyproject.toml` if a provider SDK is required

## Step 1: Pick One Canonical Provider ID

Choose a single string ID and use it everywhere. Examples from the repo: `openai-codex`, `kimi-coding`, `minimax-cn`.

That ID must appear consistently in:

- `PROVIDER_REGISTRY` in `spark_cli/auth.py`
- `_PROVIDER_LABELS` in `spark_cli/models.py`
- `_PROVIDER_ALIASES` in both `spark_cli/auth.py` and `spark_cli/models.py`
- CLI `--provider` choices in `spark_cli/main.py`
- Setup and model selection branches
- Auxiliary model defaults
- Tests

A mismatch between files is the most common cause of a "half-wired" provider — auth works but `/model` or runtime resolution silently misses it.

## Step 2: Auth Metadata (`spark_cli/auth.py`)

Add a `ProviderConfig` entry to `PROVIDER_REGISTRY`:

```python
ProviderConfig(
    id="your-provider",
    name="Your Provider",
    auth_type="api_key",
    inference_base_url="https://api.yourprovider.com/v1",
    api_key_env_vars=["YOUR_PROVIDER_API_KEY"],
)
```

Also add aliases to `_PROVIDER_ALIASES`.

Reference patterns in the existing providers:
- Simple API-key: Z.AI, MiniMax
- API-key with endpoint detection: Kimi, Z.AI
- Native token resolution: Anthropic
- OAuth / auth-store: OpenAI Codex

Decide these before writing code:
- Which env vars does Spark check, and in what priority order?
- Does the provider need base-URL overrides?
- Does it need endpoint probing or token refresh?
- What should the auth error message say when credentials are missing?

## Step 3: Model Catalog (`spark_cli/models.py`)

Update these so the provider works in menus and in `provider:model` syntax:

- `_PROVIDER_MODELS` — static model list
- `_PROVIDER_LABELS` — display name
- `_PROVIDER_ALIASES` — shorthand aliases
- Provider display order inside `list_available_providers()`
- `provider_model_ids()` if the provider supports a live `/models` fetch

If the provider has a live model list, prefer that and keep `_PROVIDER_MODELS` as the static fallback.

Without this step, auth may resolve correctly but `anthropic:claude-sonnet-4-6`-style inputs will fail.

## Step 4: Runtime Resolution (`spark_cli/runtime_provider.py`)

`resolve_runtime_provider()` is the shared path used by CLI, gateway, cron, ACP, and helper clients. Add a branch that returns at minimum:

```python
{
    "provider": "your-provider",
    "api_mode": "chat_completions",  # or your native mode
    "base_url": "https://...",
    "api_key": "...",
    "source": "env|portal|auth-store|explicit",
    "requested_provider": requested_provider,
}
```

Be explicit about which key goes to which base URL. Spark already contains logic to avoid leaking an OpenRouter key to unrelated endpoints — your provider should be equally strict.

## Step 5: CLI Wiring (`spark_cli/main.py`)

A provider isn't discoverable until it appears in `spark model`. Update:

- `provider_labels` dict
- `providers` list in `select_provider_and_model()`
- Provider dispatch (`if selected_provider == ...`)
- `--provider` argument choices
- Login/logout choices if the provider supports those flows
- A `_model_flow_<provider>()` function (or reuse `_model_flow_api_key_provider()`)

## Step 6: Auxiliary Tasks

Two files keep side tasks working:

**`agent/auxiliary_client.py`** — Add a cheap/fast default aux model to `_API_KEY_PROVIDER_AUX_MODELS`. Auxiliary tasks include vision summarization, web extraction, context compression, session search, and memory flushes. If there's no sensible aux default, side tasks may fall back unexpectedly to the main (expensive) model.

**`agent/model_metadata.py`** — Add context lengths for the provider's models so token budgeting, compression thresholds, and limits are correct.

## Step 7: Native Provider Adapter (Path B only)

Isolate provider-specific logic in `agent/<provider>_adapter.py`. Keep `run_agent.py` focused on orchestration — it should call adapter helpers, not hand-build payloads inline.

### Adapter responsibilities

- Build the SDK/HTTP client
- Resolve tokens
- Convert OpenAI-style messages to the provider's request format
- Convert tool schemas if needed
- Normalize provider responses back to what `run_agent.py` expects
- Extract usage and finish-reason data

### `run_agent.py` audit

Search for `api_mode` and check every switch point:

- `__init__` sets the new `api_mode`
- `_build_api_kwargs()` formats requests correctly
- `_api_call_with_interrupt()` dispatches to the right client call
- Interrupt/client rebuild paths work
- Response validation accepts the provider's shape
- Finish-reason and token-usage extraction are correct
- Fallback-model activation can switch into the new provider cleanly

Also search for `self.client.` — any code that assumes the standard OpenAI client can break when a native provider uses a different client object or `self.client = None`.

### Provider-specific request fields

Prompt caching and provider-specific knobs are easy to regress. Only send fields the provider actually understands. Examples already in-tree:
- Anthropic has a native prompt-caching path
- OpenRouter gets provider-routing fields
- Not every provider should receive every request-side option

## Step 8: Tests

At minimum, update these test files:

- `tests/spark_cli/test_runtime_provider_resolution.py`
- `tests/cli/test_cli_provider_resolution.py`
- `tests/spark_cli/test_codex_cli_model_picker.py`
- `tests/spark_cli/test_setup.py`
- `tests/run_agent/test_provider_parity.py`
- `tests/run_agent/test_run_agent.py`
- `tests/test_<provider>_adapter.py` for a native provider

Run with xdist disabled:

```bash
source venv/bin/activate
python -m pytest tests/spark_cli/test_runtime_provider_resolution.py tests/cli/test_cli_provider_resolution.py tests/spark_cli/test_codex_cli_model_picker.py tests/spark_cli/test_setup.py -n0 -q
```

## Step 9: Smoke Test

```bash
source venv/bin/activate
python -m spark_cli.main chat -q "Say hello" --provider your-provider --model your-model
```

Test interactive flows if you changed menus:

```bash
python -m spark_cli.main model
python -m spark_cli.main setup
```

For native providers, test at least one tool call — not just plain text.

## Step 10: User Docs

Update:

- `docs/getting-started/quickstart.md`
- `docs/configuration.md`
- `docs/reference/environment-variables.md`

A perfectly wired provider is useless if users can't discover the required env vars or setup flow.

## Checklists

### OpenAI-compatible provider

- [ ] `ProviderConfig` added in `spark_cli/auth.py`
- [ ] Aliases added in `spark_cli/auth.py` and `spark_cli/models.py`
- [ ] Model catalog added in `spark_cli/models.py`
- [ ] Runtime branch added in `spark_cli/runtime_provider.py`
- [ ] CLI wiring added in `spark_cli/main.py`
- [ ] Aux model added in `agent/auxiliary_client.py`
- [ ] Context lengths added in `agent/model_metadata.py`
- [ ] Runtime/CLI tests updated
- [ ] User docs updated

### Native provider (all of the above, plus)

- [ ] Adapter added in `agent/<provider>_adapter.py`
- [ ] New `api_mode` supported in `run_agent.py`
- [ ] Interrupt/rebuild path works
- [ ] Usage and finish-reason extraction works
- [ ] Fallback path works
- [ ] Adapter tests added
- [ ] Live smoke test passes

## Common Pitfalls

| Pitfall | What goes wrong |
|---------|----------------|
| Auth added but not model parsing | Credentials resolve; `/model` and `provider:model` fail |
| `config["model"]` not normalized | Provider code breaks when model is a dict vs string |
| Building a built-in for an OpenAI-compatible service | Unnecessary maintenance burden |
| Forgetting auxiliary paths | Main chat works; summarization, memory, vision fail |
| Native-provider branches missed in `run_agent.py` | Search `api_mode` and `self.client.` thoroughly |
| OpenRouter-only fields sent to other providers | Providers reject or ignore unknown fields |
| `spark model` updated but not `spark setup` | Users find the provider in one flow but not the other |

## Good Search Targets

When hunting for all the places a provider touches, grep for these symbols:

- `PROVIDER_REGISTRY`
- `_PROVIDER_ALIASES`
- `_PROVIDER_MODELS`
- `resolve_runtime_provider`
- `_model_flow_`
- `select_provider_and_model`
- `api_mode`
- `_API_KEY_PROVIDER_AUX_MODELS`
- `self.client.`

## Related Docs

- [Provider Runtime Resolution](./provider-runtime.md)
- [Architecture](./architecture.md)
