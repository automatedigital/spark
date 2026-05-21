---
sidebar_position: 4
title: "Memory Providers"
description: "External memory provider plugins - Honcho, OpenViking, Mem0, Hindsight, Holographic, RetainDB, ByteRover, Supermemory"
---

# Memory Providers

Spark's built-in memory (MEMORY.md / USER.md) keeps key facts close. External memory providers go further — knowledge graphs, semantic search, automatic fact extraction, cross-session user modeling. Eight providers are included. Pick one.

Only one external provider can be active at a time. Built-in memory always stays on.

## Switch Providers in Seconds

```bash
spark memory setup      # interactive picker + guided configuration
spark memory status     # see what's currently active
spark memory off        # disable external provider
```

You can also go through `spark plugins` → Provider Plugins → Memory Provider, or set it directly:

```yaml
# ~/.spark/config.yaml
memory:
  provider: openviking   # honcho | mem0 | hindsight | holographic | retaindb | byterover | supermemory
```

## How Providers Integrate

When a provider is active, Spark automatically does all of this:

1. Injects provider context into the system prompt at session start
2. Prefetches relevant memories before each turn (non-blocking background fetch)
3. Syncs each conversation turn to the provider after response
4. Extracts memories on session end (where supported)
5. Mirrors built-in memory writes to the external provider
6. Adds provider-specific tools for search, storage, and management

Your existing built-in memory continues to work exactly as before.

---

## The Providers

### Honcho

**Best for:** Multi-agent setups and deep cross-session user modeling.

Honcho builds a persistent model of who you are using dialectic Q&A and semantic reasoning. It doesn't just store facts — it derives conclusions about your patterns over time.

| | |
|---|---|
| **Storage** | Honcho Cloud or self-hosted |
| **Cost** | Honcho pricing (cloud) / free (self-hosted) |
| **Install** | `pip install honcho-ai` + [API key](https://app.honcho.dev) |

**Tools:** `honcho_profile`, `honcho_search`, `honcho_context`, `honcho_conclude`

**Setup:**
```bash
spark memory setup        # select "honcho"
# or legacy:
spark honcho setup
```

**Config file:** `$SPARK_HOME/honcho.json` (profile-local) or `~/.honcho/config.json` (global).

Resolution order: `$SPARK_HOME/honcho.json` > `~/.spark/honcho.json` > `~/.honcho/config.json`.

<details>
<summary>Key config options</summary>

| Key | Default | Description |
|-----|---------|-------------|
| `apiKey` | — | API key from [app.honcho.dev](https://app.honcho.dev) |
| `baseUrl` | — | Base URL for self-hosted Honcho |
| `peerName` | — | User peer identity |
| `aiPeer` | host key | AI peer identity (one per profile) |
| `workspace` | host key | Shared workspace ID |
| `recallMode` | `hybrid` | `hybrid` (auto-inject + tools), `context` (inject only), `tools` (tools only) |
| `observation` | all on | Per-peer `observeMe`/`observeOthers` booleans |
| `writeFrequency` | `async` | `async`, `turn`, `session`, or integer N |
| `sessionStrategy` | `per-directory` | `per-directory`, `per-repo`, `per-session`, `global` |
| `dialecticReasoningLevel` | `low` | `minimal`, `low`, `medium`, `high`, `max` |
| `dialecticDynamic` | `true` | Auto-bump reasoning level by query length |
| `messageMaxChars` | `25000` | Max chars per message (chunked if exceeded) |

</details>

<details>
<summary>Minimal honcho.json — cloud</summary>

```json
{
  "apiKey": "your-key-from-app.honcho.dev",
  "hosts": {
    "spark": {
      "enabled": true,
      "aiPeer": "spark",
      "peerName": "your-name",
      "workspace": "spark"
    }
  }
}
```

</details>

<details>
<summary>Minimal honcho.json — self-hosted</summary>

```json
{
  "baseUrl": "http://localhost:8000",
  "hosts": {
    "spark": {
      "enabled": true,
      "aiPeer": "spark",
      "peerName": "your-name",
      "workspace": "spark"
    }
  }
}
```

</details>

:::tip Migrating from `spark honcho`
Previously used `spark honcho setup`? Your config and all server-side data are intact. Re-enable via the setup wizard or set `memory.provider: honcho` manually.
:::

**Multi-profile setup:**

Each Spark profile gets its own Honcho AI peer while sharing the same workspace. All profiles see the same user representation, but each agent builds its own identity and observations.

```bash
spark profile create coder --clone   # creates honcho peer "coder", inherits config from default
```

`--clone` creates a `spark.coder` host block in `honcho.json` with `aiPeer: "coder"`, shared `workspace`, and inherited settings. The peer is created in Honcho before the first message.

For profiles created before Honcho was set up:

```bash
spark honcho sync   # creates host blocks for any profiles that are missing one
```

Idempotent — skips profiles that already have a block.

<details>
<summary>Full honcho.json — multi-profile example</summary>

```json
{
  "apiKey": "your-key",
  "workspace": "spark",
  "peerName": "eri",
  "hosts": {
    "spark": {
      "enabled": true,
      "aiPeer": "spark",
      "workspace": "spark",
      "peerName": "eri",
      "recallMode": "hybrid",
      "writeFrequency": "async",
      "sessionStrategy": "per-directory",
      "observation": {
        "user": { "observeMe": true, "observeOthers": true },
        "ai": { "observeMe": true, "observeOthers": true }
      },
      "dialecticReasoningLevel": "low",
      "dialecticDynamic": true,
      "dialecticMaxChars": 600,
      "messageMaxChars": 25000,
      "saveMessages": true
    },
    "spark.coder": {
      "enabled": true,
      "aiPeer": "coder",
      "workspace": "spark",
      "peerName": "eri",
      "recallMode": "tools",
      "observation": {
        "user": { "observeMe": true, "observeOthers": false },
        "ai": { "observeMe": true, "observeOthers": true }
      }
    },
    "spark.writer": {
      "enabled": true,
      "aiPeer": "writer",
      "workspace": "spark",
      "peerName": "eri"
    }
  },
  "sessions": {
    "/home/user/myproject": "myproject-main"
  }
}
```

</details>

See the [config reference](https://github.com/spark-ai/spark-agent/blob/main/plugins/memory/honcho/README.md) and [Honcho integration guide](https://docs.honcho.dev/v3/guides/integrations/spark).

---

### OpenViking

**Best for:** Self-hosted knowledge management with structured, browsable hierarchies.

Filesystem-style knowledge organization with tiered retrieval — load just a summary, then drill in only when you need the full document.

| | |
|---|---|
| **Storage** | Self-hosted |
| **Cost** | Free (open-source, AGPL-3.0) |
| **Install** | `pip install openviking` + running server |

**Tools:** `viking_search`, `viking_read`, `viking_browse`, `viking_remember`, `viking_add_resource`

**Setup:**
```bash
# Start the server first
pip install openviking
openviking-server

# Then point Spark at it
spark memory setup    # select "openviking"
# or manually:
spark config set memory.provider openviking
echo "OPENVIKING_ENDPOINT=http://localhost:1933" >> ~/.spark/.env
```

**Standout features:**
- Tiered context loading: L0 (~100 tokens) → L1 (~2k) → L2 (full document)
- Automatic extraction into 6 categories on session commit: profile, preferences, entities, events, cases, patterns
- `viking://` URI scheme for navigating the knowledge hierarchy

---

### Mem0

**Best for:** Hands-off memory management. Mem0 handles extraction automatically.

Send conversations in; get back relevant facts on demand. No configuration required to get good results.

| | |
|---|---|
| **Storage** | Mem0 Cloud |
| **Cost** | Mem0 pricing |
| **Install** | `pip install mem0ai` + API key |

**Tools:** `mem0_profile`, `mem0_search`, `mem0_conclude`

**Setup:**
```bash
spark memory setup    # select "mem0"
# or manually:
spark config set memory.provider mem0
echo "MEM0_API_KEY=your-key" >> ~/.spark/.env
```

**Config:** `$SPARK_HOME/mem0.json`

| Key | Default | Description |
|-----|---------|-------------|
| `user_id` | `spark-user` | User identifier |
| `agent_id` | `spark` | Agent identifier |

---

### Hindsight

**Best for:** Knowledge graph-based recall with entity relationships and cross-memory synthesis.

Hindsight builds a graph of entities and their relationships. The `hindsight_reflect` tool synthesizes across multiple memories — something no other provider offers. Full conversation turns including tool calls are retained automatically.

| | |
|---|---|
| **Storage** | Hindsight Cloud or local embedded PostgreSQL |
| **Cost** | Hindsight pricing (cloud) / free (local) |
| **Install** | Cloud: API key from [ui.hindsight.vectorize.io](https://ui.hindsight.vectorize.io). Local: LLM API key (OpenAI, Groq, OpenRouter, etc.) |

**Tools:** `hindsight_retain`, `hindsight_recall`, `hindsight_reflect`

**Setup:**
```bash
spark memory setup    # select "hindsight"
# or manually:
spark config set memory.provider hindsight
echo "HINDSIGHT_API_KEY=your-key" >> ~/.spark/.env
```

The setup wizard installs only what's needed (`hindsight-client` for cloud, `hindsight-all` for local). Requires `hindsight-client >= 0.4.22` — auto-upgraded on session start if outdated.

**Local mode UI:** `hindsight-embed -p spark ui start`

**Config:** `$SPARK_HOME/hindsight/config.json`

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `cloud` | `cloud` or `local` |
| `bank_id` | `spark` | Memory bank identifier |
| `recall_budget` | `mid` | Recall thoroughness: `low` / `mid` / `high` |
| `memory_mode` | `hybrid` | `hybrid`, `context`, or `tools` |
| `auto_retain` | `true` | Auto-retain conversation turns |
| `auto_recall` | `true` | Auto-recall before each turn |
| `retain_async` | `true` | Process retain asynchronously |
| `tags` | — | Tags applied when storing |
| `recall_tags` | — | Tags to filter on recall |

See the [plugin README](https://github.com/automatedigital/spark/blob/main/plugins/memory/hindsight/README.md) for the full reference.

---

### Holographic

**Best for:** Local-only memory with advanced retrieval. No external dependencies, no accounts, no cost.

SQLite-backed fact store with FTS5 full-text search, trust scoring, and HRR (Holographic Reduced Representations) for algebraic queries across multiple entities.

| | |
|---|---|
| **Storage** | Local SQLite |
| **Cost** | Free |
| **Install** | Nothing — SQLite is always available. NumPy optional for HRR algebra. |

**Tools:** `fact_store` (9 actions: add, search, probe, related, reason, contradict, update, remove, list), `fact_feedback`

**Setup:**
```bash
spark memory setup    # select "holographic"
# or manually:
spark config set memory.provider holographic
```

**Config:** `config.yaml` under `plugins.spark-memory-store`

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | `$SPARK_HOME/memory_store.db` | SQLite database path |
| `auto_extract` | `false` | Auto-extract facts at session end |
| `default_trust` | `0.5` | Default trust score (0.0–1.0) |

**What makes it unique:**
- `probe` — all facts about a specific entity
- `reason` — compositional AND queries across multiple entities
- `contradict` — automated detection of conflicting facts
- Trust scoring with asymmetric feedback: +0.05 helpful / -0.10 unhelpful

---

### RetainDB

**Best for:** Teams already using RetainDB infrastructure.

Hybrid search (Vector + BM25 + Reranking), 7 memory types, and delta compression. Purpose-built cloud memory API.

| | |
|---|---|
| **Storage** | RetainDB Cloud |
| **Cost** | $20/month |
| **Install** | RetainDB account + API key |

**Tools:** `retaindb_profile`, `retaindb_search`, `retaindb_context`, `retaindb_remember`, `retaindb_forget`

**Setup:**
```bash
spark memory setup    # select "retaindb"
# or manually:
spark config set memory.provider retaindb
echo "RETAINDB_API_KEY=your-key" >> ~/.spark/.env
```

---

### ByteRover

**Best for:** Developers who want portable, local-first memory with a CLI they can inspect and version.

A hierarchical knowledge tree managed through the `brv` CLI. Tiered retrieval goes from fuzzy text match to LLM-driven search. Works offline; optional cloud sync available.

| | |
|---|---|
| **Storage** | Local (default) or ByteRover Cloud (optional) |
| **Cost** | Free (local) / ByteRover pricing (cloud) |
| **Install** | ByteRover CLI: `npm install -g byterover-cli` or [install script](https://byterover.dev) |

**Tools:** `brv_query`, `brv_curate`, `brv_status`

**Setup:**
```bash
# Install the CLI first
curl -fsSL https://byterover.dev/install.sh | sh

# Then configure Spark
spark memory setup    # select "byterover"
# or manually:
spark config set memory.provider byterover
```

**Standout features:**
- Automatic pre-compression extraction — saves insights before context compression discards them
- Knowledge tree stored at `$SPARK_HOME/byterover/` (scoped per profile)
- SOC2 Type II certified cloud sync (optional)

---

### Supermemory

**Best for:** Semantic recall with profile tracking and session-level graph building.

Stores cleaned conversation turns, builds a user profile that stays current across sessions, and supports multi-container setups for isolating different contexts.

| | |
|---|---|
| **Storage** | Supermemory Cloud |
| **Cost** | Supermemory pricing |
| **Install** | `pip install supermemory` + [API key](https://supermemory.ai) |

**Tools:** `supermemory_store`, `supermemory_search`, `supermemory_forget`, `supermemory_profile`

**Setup:**
```bash
spark memory setup    # select "supermemory"
# or manually:
spark config set memory.provider supermemory
echo 'SUPERMEMORY_API_KEY=***' >> ~/.spark/.env
```

**Config:** `$SPARK_HOME/supermemory.json`

| Key | Default | Description |
|-----|---------|-------------|
| `container_tag` | `spark` | Container tag for search and writes. Supports `{identity}` for profile-scoped tags. |
| `auto_recall` | `true` | Inject relevant context before turns |
| `auto_capture` | `true` | Store cleaned turns after each response |
| `max_recall_results` | `10` | Max recalled items to format into context |
| `profile_frequency` | `50` | Include profile facts on first turn and every N turns |
| `capture_mode` | `all` | Skip trivial turns by default |
| `search_mode` | `hybrid` | `hybrid`, `memories`, or `documents` |
| `api_timeout` | `5.0` | Timeout for SDK and ingest requests |

**Environment variables:** `SUPERMEMORY_API_KEY` (required), `SUPERMEMORY_CONTAINER_TAG` (overrides config).

**Standout features:**
- Automatic context fencing — strips recalled memories from captured turns to prevent recursive pollution
- Session-end conversation ingest for richer graph-level knowledge
- Profile-scoped containers: use `{identity}` in `container_tag` (e.g. `spark-{identity}` → `spark-coder`)
- Multi-container mode: enable `enable_custom_container_tags` with a `custom_containers` list to read/write across named containers

<details>
<summary>Multi-container example</summary>

```json
{
  "container_tag": "spark",
  "enable_custom_container_tags": true,
  "custom_containers": ["project-alpha", "shared-knowledge"],
  "custom_container_instructions": "Use project-alpha for coding context."
}
```

</details>

**Support:** [Discord](https://supermemory.link/discord) · [support@supermemory.com](mailto:support@supermemory.com)

---

## Side-by-Side Comparison

| Provider | Storage | Cost | Tools | Dependencies | What makes it unique |
|----------|---------|------|-------|-------------|----------------------|
| **Honcho** | Cloud | Paid | 4 | `honcho-ai` | Dialectic user modeling |
| **OpenViking** | Self-hosted | Free | 5 | `openviking` + server | Filesystem hierarchy + tiered loading |
| **Mem0** | Cloud | Paid | 3 | `mem0ai` | Server-side LLM extraction |
| **Hindsight** | Cloud/Local | Free/Paid | 3 | `hindsight-client` | Knowledge graph + reflect synthesis |
| **Holographic** | Local | Free | 2 | None | HRR algebra + trust scoring |
| **RetainDB** | Cloud | $20/mo | 5 | `requests` | Delta compression |
| **ByteRover** | Local/Cloud | Free/Paid | 3 | `brv` CLI | Pre-compression extraction |
| **Supermemory** | Cloud | Paid | 4 | `supermemory` | Context fencing + session graph + multi-container |

## Data Isolation Per Profile

Each provider's data is scoped to the active [profile](../cli/profiles.md):

- **Local providers** (Holographic, ByteRover) — use `$SPARK_HOME/` paths, which differ per profile
- **Config file providers** (Honcho, Mem0, Hindsight, Supermemory) — config stored in `$SPARK_HOME/`, so each profile has its own credentials
- **Cloud providers** (RetainDB) — auto-derive profile-scoped project names
- **Env var providers** (OpenViking) — configured via each profile's `.env` file

## Build Your Own Provider

See the [Developer Guide: Memory Provider Plugins](../building/memory-provider-plugin.md) to create a custom provider.
