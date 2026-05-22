---
title: "AI Providers"
sidebar_label: "AI Providers"
sidebar_position: 1
---

# AI Providers

You need at least one inference provider to use Spark. This page covers every supported provider — from major cloud APIs to local GPU servers — and how to configure each one.

Run `spark model` to switch providers interactively, or edit `config.yaml` directly.

The same command also manages model reasoning effort. The default is `medium` when unset:

```bash
spark model reasoning          # show current effort
spark model reasoning high     # none|minimal|low|medium|high|xhigh
```

You can also choose **Reasoning** from the first `spark model` menu. Spark applies this setting only where the selected provider/model supports reasoning controls; unsupported models ignore it safely.

## Provider Quick Reference

| Provider | How to set up |
|----------|---------------|
| **OpenAI Codex** | `spark model` (ChatGPT OAuth, Codex models) |
| **GitHub Copilot** | `spark model` (OAuth device code, `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, or `gh auth token`) |
| **GitHub Copilot ACP** | `spark model` (spawns local `copilot --acp --stdio`) |
| **Anthropic** | `spark model` (Claude Pro/Max OAuth, API key, or setup-token) |
| **OpenRouter** | `OPENROUTER_API_KEY` in `~/.spark/.env` |
| **AI Gateway** | `AI_GATEWAY_API_KEY` in `~/.spark/.env` (provider: `ai-gateway`) |
| **z.ai / GLM** | `GLM_API_KEY` in `~/.spark/.env` (provider: `zai`) |
| **Kimi / Moonshot** | `KIMI_API_KEY` in `~/.spark/.env` (provider: `kimi-coding`) |
| **Kimi China** | `KIMI_CN_API_KEY` in `~/.spark/.env` (provider: `kimi-coding-cn`) |
| **Arcee AI** | `ARCEEAI_API_KEY` in `~/.spark/.env` (provider: `arcee`) |
| **MiniMax** | `MINIMAX_API_KEY` in `~/.spark/.env` (provider: `minimax`) |
| **MiniMax China** | `MINIMAX_CN_API_KEY` in `~/.spark/.env` (provider: `minimax-cn`) |
| **Alibaba Cloud** | `DASHSCOPE_API_KEY` in `~/.spark/.env` (provider: `alibaba`) |
| **Kilo Code** | `KILOCODE_API_KEY` in `~/.spark/.env` (provider: `kilocode`) |
| **Xiaomi MiMo** | `XIAOMI_API_KEY` in `~/.spark/.env` (provider: `xiaomi`) |
| **OpenCode Zen** | `OPENCODE_ZEN_API_KEY` in `~/.spark/.env` (provider: `opencode-zen`) |
| **OpenCode Go** | `OPENCODE_GO_API_KEY` in `~/.spark/.env` (provider: `opencode-go`) |
| **DeepSeek** | `DEEPSEEK_API_KEY` in `~/.spark/.env` (provider: `deepseek`) |
| **Hugging Face** | `HF_TOKEN` in `~/.spark/.env` (provider: `huggingface`) |
| **Google / Gemini** | `GOOGLE_API_KEY` or `GEMINI_API_KEY` in `~/.spark/.env` (provider: `gemini`) |
| **Custom Endpoint** | `spark model` → "Custom endpoint" or edit `config.yaml` |

:::tip Model key alias
In the `model:` config section, `default:` and `model:` are interchangeable. Both `model: { default: my-model }` and `model: { model: my-model }` work identically.
:::

---

### Anthropic (Native)

Three ways to authenticate — pick the one that fits your setup:

```bash
# API key (pay-per-token)
export ANTHROPIC_API_KEY=***
spark chat --provider anthropic --model claude-sonnet-4-6

# Interactive setup — Spark prefers Claude Code's credential store when available
spark model

# Manual token override
export ANTHROPIC_TOKEN=***
spark chat --provider anthropic
```

When you authenticate via `spark model`, Spark uses Claude Code's own credential store rather than copying tokens into `.env`. That keeps refreshable Claude credentials refreshable.

Permanent config:
```yaml
model:
  provider: "anthropic"
  default: "claude-sonnet-4-6"
```

:::tip Aliases
`--provider claude` and `--provider claude-code` are shorthands for `--provider anthropic`.
:::

---

### GitHub Copilot

Two modes:

**`copilot`** (recommended) — Direct Copilot API. Uses your GitHub Copilot subscription to access GPT-5.x, Claude, Gemini, and more.

```bash
spark chat --provider copilot --model gpt-5.4
```

Authentication order:
1. `COPILOT_GITHUB_TOKEN`
2. `GH_TOKEN`
3. `GITHUB_TOKEN`
4. `gh auth token` CLI fallback
5. OAuth device code via `spark model`

:::warning Token types
Classic PATs (`ghp_*`) are not supported. Use OAuth tokens (`gho_*`) or fine-grained PATs (`github_pat_*`).
:::

**`copilot-acp`** — Spawns the local Copilot CLI as a subprocess:

```bash
spark chat --provider copilot-acp --model copilot-acp
# Requires: Copilot CLI in PATH + existing `copilot login` session
```

Permanent config:
```yaml
model:
  provider: "copilot"
  default: "gpt-5.4"
```

| Env var | Purpose |
|---------|---------|
| `COPILOT_GITHUB_TOKEN` | GitHub token (first priority) |
| `SPARK_COPILOT_ACP_COMMAND` | Override Copilot CLI binary (default: `copilot`) |
| `SPARK_COPILOT_ACP_ARGS` | Override ACP args (default: `--acp --stdio`) |

---

### First-Class Chinese AI Providers

```bash
# z.ai / ZhipuAI GLM
spark chat --provider zai --model glm-5

# Kimi / Moonshot AI (international)
spark chat --provider kimi-coding --model kimi-for-coding

# Kimi / Moonshot AI (China)
spark chat --provider kimi-coding-cn --model kimi-k2.5

# MiniMax (global)
spark chat --provider minimax --model MiniMax-M2.7

# MiniMax (China)
spark chat --provider minimax-cn --model MiniMax-M2.7

# Alibaba Cloud / DashScope (Qwen models)
spark chat --provider alibaba --model qwen3.5-plus

# Xiaomi MiMo
spark chat --provider xiaomi --model mimo-v2-pro

# Arcee AI
spark chat --provider arcee --model trinity-large-thinking
```

Or set permanently in `config.yaml`:
```yaml
model:
  provider: "zai"
  default: "glm-5"
```

Base URLs can be overridden with `GLM_BASE_URL`, `KIMI_BASE_URL`, `MINIMAX_BASE_URL`, `DASHSCOPE_BASE_URL`, `XIAOMI_BASE_URL`, etc.

:::note Z.AI Auto-Detection
Spark automatically probes multiple z.ai endpoints to find one that accepts your key. No need to set `GLM_BASE_URL` manually.
:::

---

### xAI (Grok) Prompt Caching

When your base URL contains `x.ai`, Spark automatically sends the `x-grok-conv-id` header with every request. This routes requests to the same server within a session, enabling xAI's infrastructure to reuse cached system prompts and conversation history. No configuration needed.

---

### Hugging Face Inference Providers

Routes to 20+ open models via a unified OpenAI-compatible endpoint (`router.huggingface.co/v1`) with automatic failover across Groq, Together, SambaNova, and more.

```bash
spark chat --provider huggingface --model Qwen/Qwen3-235B-A22B-Thinking-2507
# Alias:
spark chat --provider hf --model deepseek-ai/DeepSeek-V3.2
```

Get a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) — enable "Make calls to Inference Providers". Free tier includes $0.10/month credit.

Append routing suffixes to model names: `:fastest` (default), `:cheapest`, or `:provider_name` to pin a backend.

---

## Custom & Self-Hosted LLM Endpoints

Spark works with any OpenAI-compatible API. If a server implements `/v1/chat/completions`, you can point Spark at it.

### General Setup

```bash
# Interactive (recommended)
spark model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
```

```yaml
# config.yaml
model:
  default: your-model-name
  provider: custom
  base_url: http://localhost:8000/v1
  api_key: your-key-or-leave-empty-for-local
```

:::warning Legacy env vars
`OPENAI_BASE_URL` and `LLM_MODEL` are removed. Use `config.yaml` exclusively.
:::

### Switching Models Mid-Session

```
/model custom:qwen-2.5          # Switch to model on your custom endpoint
/model custom                    # Auto-detect from endpoint
/model openrouter:claude-sonnet-4 # Switch back to cloud
```

With named custom providers:
```
/model custom:local:qwen-2.5
/model custom:work:llama3
```

---

### Ollama — Local Models, Zero Config

```bash
ollama pull qwen2.5-coder:32b
ollama serve
```

```bash
spark model
# URL: http://localhost:11434/v1
# API key: (skip)
# Model: qwen2.5-coder:32b
```

Or in `config.yaml`:
```yaml
model:
  default: qwen2.5-coder:32b
  provider: custom
  base_url: http://localhost:11434/v1
  context_length: 32768
```

:::caution Ollama defaults to very low context lengths

| Available VRAM | Default context |
|----------------|----------------|
| Less than 24 GB | **4,096 tokens** |
| 24–48 GB | 32,768 tokens |
| 48+ GB | 256,000 tokens |

For agent use with tools, you need at least 16k–32k tokens. At 4k, just the system prompt and tool schemas can fill the window.

Fix it (pick one):

```bash
# Option 1: Environment variable
OLLAMA_CONTEXT_LENGTH=32768 ollama serve

# Option 2: systemd
sudo systemctl edit ollama.service
# Add: Environment="OLLAMA_CONTEXT_LENGTH=32768"

# Option 3: Custom model
echo -e "FROM qwen2.5-coder:32b\nPARAMETER num_ctx 32768" > Modelfile
ollama create qwen2.5-coder-32k -f Modelfile
```

You cannot set context length through the OpenAI-compatible API — it must be configured server-side.
:::

---

### vLLM — High-Performance GPU Inference

```bash
pip install vllm
vllm serve meta-llama/Llama-3.1-70B-Instruct \
  --port 8000 \
  --max-model-len 65536 \
  --tensor-parallel-size 2 \
  --enable-auto-tool-choice \
  --tool-call-parser spark
```

Tool calling requires explicit flags:

| Flag | Purpose |
|------|---------|
| `--enable-auto-tool-choice` | Required for `tool_choice: "auto"` |
| `--tool-call-parser <name>` | Parser for the model's tool call format |

Supported parsers: `spark`, `llama3_json`, `mistral`, `deepseek_v3`, `deepseek_v31`, `xlam`, `pythonic`.

---

### SGLang — Fast Serving with RadixAttention

```bash
pip install "sglang[all]"
python -m sglang.launch_server \
  --model meta-llama/Llama-3.1-70B-Instruct \
  --port 30000 \
  --context-length 65536 \
  --tp 2 \
  --tool-call-parser qwen
```

:::caution SGLang defaults to 128 max output tokens
Add `--default-max-tokens` if responses seem truncated.
:::

---

### llama.cpp / llama-server — CPU & Metal Inference

```bash
cmake -B build && cmake --build build --config Release
./build/bin/llama-server \
  --jinja -fa \
  -c 32768 \
  -ngl 99 \
  -m models/qwen2.5-coder-32b-instruct-Q4_K_M.gguf \
  --port 8080 --host 0.0.0.0
```

:::caution `--jinja` is required for tool calling
Without `--jinja`, llama-server ignores the `tools` parameter entirely and you'll see raw JSON in responses instead of actual tool calls.
:::

---

### LM Studio — Desktop App

Start the server from LM Studio's Developer tab, or use the CLI:

```bash
lms server start
lms load qwen2.5-coder --context-length 32768
```

Then point Spark at `http://localhost:1234/v1`.

:::caution Context often defaults to 2048
Set context length explicitly in LM Studio's model settings (gear icon → "Context Length" → at least 16384).
:::

---

### WSL2 Networking (Windows Users)

If Spark runs in WSL2 and your model server runs on the Windows host, `localhost` in WSL2 refers to the Linux VM — not Windows.

**Option 1: Mirrored Networking (Windows 11 22H2+)**

```ini
# %USERPROFILE%\.wslconfig
[wsl2]
networkingMode=mirrored
```

```powershell
wsl --shutdown
```

**Option 2: Use the Windows Host IP**

```bash
ip route show | grep -i default | awk '{ print $3 }'
# Example: 172.29.192.1
```

```yaml
model:
  base_url: http://172.29.192.1:11434/v1
```

When using the host IP, your model server must also bind to `0.0.0.0`, not `127.0.0.1`:

| Server | Fix |
|--------|-----|
| Ollama | Set `OLLAMA_HOST=0.0.0.0` |
| LM Studio | Enable "Serve on Network" in Developer tab |
| llama-server | Add `--host 0.0.0.0` |
| vLLM | Already binds to all interfaces |
| SGLang | Add `--host 0.0.0.0` |

---

### Troubleshooting Local Models

**Tool calls appear as text instead of executing**

| Server | Fix |
|--------|-----|
| llama.cpp | Add `--jinja` |
| vLLM | Add `--enable-auto-tool-choice --tool-call-parser spark` |
| SGLang | Add `--tool-call-parser qwen` |
| LM Studio | Update to 0.3.6+ |

**Model forgets context or gives incoherent responses**

Context window is too small. Set it to at least 32,768 tokens for agent use.

**"Context limit: 2048 tokens" at startup**

Override explicitly in `config.yaml`:

```yaml
model:
  default: your-model
  base_url: http://localhost:11434/v1
  context_length: 32768
```

**Responses cut off mid-sentence**

Either the output cap (`max_tokens`) is too low, or context is exhausted. SGLang defaults to 128 output tokens — set `--default-max-tokens` server-side.

---

### LiteLLM Proxy — Multi-Provider Gateway

```bash
pip install "litellm[proxy]"
litellm --model anthropic/claude-sonnet-4 --port 4000
```

Point Spark at `http://localhost:4000/v1` via `spark model` → Custom endpoint.

---

### ClawRouter — Cost-Optimized Routing

```bash
npx @blockrun/clawrouter    # Starts on port 8402
```

Point Spark at `http://localhost:8402/v1`, model name `blockrun/auto`.

| Profile | Strategy |
|---------|----------|
| `blockrun/auto` | Balanced quality/cost |
| `blockrun/eco` | Cheapest possible |
| `blockrun/premium` | Best quality |
| `blockrun/free` | Free models only |
| `blockrun/agentic` | Optimized for tool use |

---

### Other Compatible Endpoints

| Provider | Base URL |
|----------|----------|
| Together AI | `https://api.together.xyz/v1` |
| Groq | `https://api.groq.com/openai/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| Fireworks AI | `https://api.fireworks.ai/inference/v1` |
| Cerebras | `https://api.cerebras.ai/v1` |
| Mistral AI | `https://api.mistral.ai/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Azure OpenAI | `https://YOUR.openai.azure.com/` |
| LocalAI | `http://localhost:8080/v1` |
| Jan | `http://localhost:1337/v1` |

---

## Context Length Detection

:::note Two settings, easy to confuse
**`context_length`** — total context window (input + output). Spark uses this for compression and validation.

**`model.max_tokens`** — output cap per response. Unrelated to conversation history length.
:::

Spark uses a multi-source resolution chain:

1. Config override (`model.context_length` in `config.yaml`)
2. Custom provider per-model settings
3. Persistent cache from previous discovery
4. Endpoint `/models` API
5. Anthropic `/v1/models`
6. OpenRouter API
7. [models.dev](https://models.dev) community registry (3800+ models)
8. Broad fallback defaults (128K default)

Set it explicitly when auto-detection gets it wrong:

```yaml
model:
  default: "qwen3.5:9b"
  base_url: "http://localhost:8080/v1"
  context_length: 131072
```

Per-model overrides for custom endpoints:

```yaml
custom_providers:
  - name: "My Local LLM"
    base_url: "http://localhost:11434/v1"
    models:
      qwen3.5:27b:
        context_length: 32768
      deepseek-r1:70b:
        context_length: 65536
```

---

## Named Custom Providers

Manage multiple endpoints without switching config:

```yaml
custom_providers:
  - name: local
    base_url: http://localhost:8080/v1
  - name: work
    base_url: https://gpu-server.internal.corp/v1
    api_key: corp-api-key
  - name: anthropic-proxy
    base_url: https://proxy.example.com/anthropic
    api_key: proxy-key
    api_mode: anthropic_messages
```

Switch between them mid-session:

```
/model custom:local:qwen-2.5
/model custom:work:llama3-70b
```

---

## OpenRouter Provider Routing

```yaml
provider_routing:
  sort: "throughput"
  # only: ["anthropic"]
  # ignore: ["deepinfra"]
  # order: ["anthropic", "google"]
  # require_parameters: true
  # data_collection: "deny"
```

Append `:nitro` to any model name for throughput sorting, or `:floor` for price sorting.

---

## Fallback Model

```yaml
fallback_model:
  provider: openrouter
  model: anthropic/claude-sonnet-4
```

Activates automatically when your primary model fails with rate limits, server errors, or auth failures. Fires at most once per session. See [Fallback Providers](../providers/fallback.md) for full details.

---

## Smart Model Routing

Route short, simple turns to a cheaper model while keeping your main model for complex work:

```yaml
smart_model_routing:
  enabled: true
  max_simple_chars: 160
  max_simple_words: 28
  cheap_model:
    provider: openrouter
    model: google/gemini-2.5-flash
```

Conservative by design — only routes quick factual questions and lightweight summaries. Coding, debugging, and multi-line analysis always go to your primary model.

---

## Choosing the Right Setup

| Use Case | Recommended |
|----------|-------------|
| Just want it to work | OpenRouter or OpenAI Codex |
| Local models, easy setup | Ollama |
| Production GPU serving | vLLM or SGLang |
| Mac / no GPU | Ollama or llama.cpp |
| Multi-provider routing | LiteLLM Proxy or OpenRouter |
| Cost optimization | ClawRouter or OpenRouter with `sort: "price"` |
| Maximum privacy | Ollama, vLLM, or llama.cpp (fully local) |
| Enterprise / Azure | Azure OpenAI with custom endpoint |
| Chinese AI models | z.ai, Kimi, MiniMax, or Xiaomi MiMo |

---

## Optional API Keys

| Feature | Provider | Env Variable |
|---------|----------|--------------|
| Web scraping | [Firecrawl](https://firecrawl.dev/) | `FIRECRAWL_API_KEY`, `FIRECRAWL_API_URL` |
| Browser automation | [Browserbase](https://browserbase.com/) | `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` |
| Image generation | [FAL](https://fal.ai/) | `FAL_KEY` |
| Premium TTS | [ElevenLabs](https://elevenlabs.io/) | `ELEVENLABS_API_KEY` |
| OpenAI TTS + STT | [OpenAI](https://platform.openai.com/api-keys) | `VOICE_TOOLS_OPENAI_KEY` |
| Mistral TTS + STT | [Mistral](https://console.mistral.ai/) | `MISTRAL_API_KEY` |
| RL Training | [Tinker](https://tinker-console.thinkingmachines.ai/) + [WandB](https://wandb.ai/) | `TINKER_API_KEY`, `WANDB_API_KEY` |
| Cross-session user modeling | [Honcho](https://honcho.dev/) | `HONCHO_API_KEY` |
| Semantic long-term memory | [Supermemory](https://supermemory.ai) | `SUPERMEMORY_API_KEY` |

### Self-Hosting Firecrawl

Point Spark at your own Firecrawl instance instead of the cloud API:

1. Clone and start the Docker stack:
   ```bash
   git clone https://github.com/firecrawl/firecrawl
   cd firecrawl
   # In .env: USE_DB_AUTHENTICATION=false, HOST=0.0.0.0, PORT=3002
   docker compose up -d
   ```

2. Configure Spark:
   ```bash
   spark config set FIRECRAWL_API_URL http://localhost:3002
   ```

Trade-off: no API key or rate limits, but the self-hosted version uses basic fetch + Playwright instead of Firecrawl's proprietary anti-bot stack. Some protected sites may fail.

---

## See Also

- [Configuration](../configuration.md) — Directory structure, config precedence, context compression, and more
- [Environment Variables](../reference/environment-variables.md) — Complete reference
