---
sidebar_position: 2
title: "Run Local LLMs on Mac"
description: "Set up a local OpenAI-compatible LLM server on macOS with llama.cpp or MLX, including model selection, memory optimization, and real benchmarks on Apple Silicon"
---

# Run Local LLMs on Mac

Run a full LLM server on your Mac and connect Spark to it. You get complete privacy, zero API costs, and — on Apple Silicon — surprisingly fast inference.

Two backends to choose from:

| Backend | Best at | Model format |
|---------|---------|--------------|
| **llama.cpp** | Lowest time-to-first-token, best memory efficiency | GGUF |
| **omlx** | Fastest token generation, native Metal optimization | MLX (safetensors) |

Both expose an OpenAI-compatible `/v1/chat/completions` endpoint. Spark connects to either with a single config change.

:::info Apple Silicon only
This guide targets M1 and later. Intel Macs can run llama.cpp but without GPU acceleration — expect much slower performance.
:::

---

## Pick a model

Start with **Qwen3.5-9B**. It's a capable reasoning model that fits comfortably into 8 GB+ of unified memory with quantization applied.

| Variant | Disk size | RAM at 128K context | Backend |
|---------|-----------|---------------------|---------|
| Qwen3.5-9B-Q4_K_M (GGUF) | 5.3 GB | ~10 GB with q4 KV cache | llama.cpp |
| Qwen3.5-9B-mlx-lm-mxfp4 (MLX) | ~5 GB | ~12 GB | omlx |

**Memory math:** model size + KV cache. A Q4 9B model is ~5 GB. At 128K context with default (f16) KV cache that adds ~16 GB. Switch to q4 quantized KV cache and it drops to ~4 GB. That one change is what makes 128K context usable on 16 GB machines.

For 32 GB+ systems, 27B and 35B models are viable. The 9B is the sweet spot for 8–16 GB.

---

## Option A: llama.cpp

### Install

```bash
brew install llama.cpp
```

This puts `llama-server` on your PATH.

### Download the model

```bash
brew install huggingface-cli
huggingface-cli download unsloth/Qwen3.5-9B-GGUF Qwen3.5-9B-Q4_K_M.gguf --local-dir ~/models
```

:::tip Gated models
If you get a 401 or 404, run `huggingface-cli login` first.
:::

### Start the server

```bash
llama-server -m ~/models/Qwen3.5-9B-Q4_K_M.gguf \
  -ngl 99 \
  -c 131072 \
  -np 1 \
  -fa on \
  --cache-type-k q4_0 \
  --cache-type-v q4_0 \
  --host 0.0.0.0
```

| Flag | What it does |
|------|-------------|
| `-ngl 99` | Offload all layers to GPU via Metal |
| `-c 131072` | 128K context window. Lower this on constrained systems. |
| `-np 1` | One parallel slot. More slots split your memory budget. |
| `-fa on` | Flash attention — reduces memory and speeds up long-context inference |
| `--cache-type-k q4_0` | Quantize key cache to 4-bit. The biggest memory saver. |
| `--cache-type-v q4_0` | Quantize value cache to 4-bit. Together with above, cuts KV cache ~75% vs f16. |
| `--host 0.0.0.0` | Listen on all interfaces. Use `127.0.0.1` to keep it local. |

The server is ready when you see:
```
main: server is listening on http://0.0.0.0:8080
srv  update_slots: all slots are idle
```

### Memory by KV cache type (128K context, 9B model)

| KV cache type | Memory |
|---------------|--------|
| f16 (default) | ~16 GB |
| q8_0 | ~8 GB |
| **q4_0** | **~4 GB** |

On 8 GB: use q4_0 KV cache and reduce context to `-c 32768`. On 16 GB: 128K context works. On 32 GB+: try larger models or multiple parallel slots.

Still running out of memory? Reduce `-c` first, then try Q3_K_M quantization.

### Test it

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.5-9B-Q4_K_M.gguf",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }' | jq .choices[0].message.content
```

Forget the model name? Query the models endpoint:

```bash
curl -s http://localhost:8080/v1/models | jq '.data[].id'
```

---

## Option B: MLX via omlx

[omlx](https://omlx.ai) is a macOS-native app for managing and serving MLX models. MLX is Apple's own ML framework, built specifically for unified memory on Apple Silicon.

### Install

Download from [omlx.ai](https://omlx.ai) and install the app.

### Download the model

Use the omlx app to browse and download `Qwen3.5-9B-mlx-lm-mxfp4`. Models land in `~/.omlx/models/` by default.

### Start the server

Start serving from the app UI. omlx listens on `http://127.0.0.1:8000` by default.

### Test it

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3.5-9B-mlx-lm-mxfp4",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 50
  }' | jq .choices[0].message.content
```

omlx supports serving multiple models simultaneously:

```bash
curl -s http://127.0.0.1:8000/v1/models | jq '.data[].id'
```

---

## Benchmarks: llama.cpp vs MLX

Same machine (Apple M5 Max, 128 GB unified memory), same model (Qwen3.5-9B), comparable quantization (Q4_K_M vs mxfp4). Five diverse prompts, three runs each, backends tested sequentially.

| Metric | llama.cpp (Q4_K_M) | MLX (mxfp4) | Winner |
|--------|-------------------|-------------|--------|
| TTFT (avg) | **67 ms** | 289 ms | llama.cpp (4.3x faster) |
| TTFT (p50) | **66 ms** | 286 ms | llama.cpp (4.3x faster) |
| Generation (avg) | 70 tok/s | **96 tok/s** | MLX (37% faster) |
| Generation (p50) | 70 tok/s | **96 tok/s** | MLX (37% faster) |
| Total time (512 tokens) | 7.3s | **5.5s** | MLX (25% faster) |

**What this means in practice:**

- **llama.cpp** gets you the first token in ~66ms. For interactive chat where perceived responsiveness matters, this is a real advantage.
- **MLX** generates 37% more tokens per second once it starts. For batch work or long-form generation, it finishes sooner overall.
- Both backends show negligible variance across runs — these numbers are reliable.

### Choose based on your workload

| Use case | Pick |
|----------|------|
| Interactive chat, low-latency tools | llama.cpp |
| Long-form generation, bulk processing | MLX (omlx) |
| Memory-constrained systems (8–16 GB) | llama.cpp — quantized KV cache is unmatched |
| Serving multiple models at once | omlx — built-in multi-model support |
| Cross-platform (Linux too) | llama.cpp |

---

## Connect Spark to your local server

With the server running:

```bash
spark model
```

Select **Custom endpoint** and enter the base URL and model name from whichever backend you set up.

---

## Handling timeouts

Spark automatically detects local endpoints (localhost, LAN IPs) and relaxes streaming timeouts. No config needed for most setups.

If you still hit timeout errors on very large contexts or slow hardware:

```bash
# In your .env — raise the 120s default to 30 minutes
SPARK_STREAM_READ_TIMEOUT=1800
```

| Timeout | Default | Local auto-adjustment | Override via |
|---------|---------|----------------------|-------------|
| Stream read (socket-level) | 120s | Raised to 1800s | `SPARK_STREAM_READ_TIMEOUT` |
| Stale stream detection | 180s | Disabled entirely | `SPARK_STREAM_STALE_TIMEOUT` |
| API call (non-streaming) | 1800s | No change needed | `SPARK_API_TIMEOUT` |

The stream read timeout is the one that bites most often. During prefill on large contexts, local models may produce no output for minutes. The auto-detection handles this transparently — you only need the override for extreme cases.
