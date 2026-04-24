---
sidebar_position: 3
title: "FAQ & Troubleshooting"
description: "Frequently asked questions and solutions to common issues with Spark Agent"
---

# FAQ & Troubleshooting

---

## Common Questions

### Which LLM providers can I use?

Any OpenAI-compatible API works. Here's what's supported out of the box:

| Provider | What you get |
|----------|-------------|
| [OpenRouter](https://openrouter.ai/) | Hundreds of models through a single API key — recommended for flexibility |
| Spark Portal | Automate Digital's own inference endpoint |
| OpenAI | GPT-4o, o1, o3, and more |
| Anthropic | Claude models (via OpenRouter or compatible proxy) |
| Google | Gemini models (via OpenRouter or compatible proxy) |
| z.ai / ZhipuAI | GLM models |
| Kimi / Moonshot AI | Kimi models |
| MiniMax | Global and China endpoints |
| Local models | [Ollama](https://ollama.com/), [vLLM](https://docs.vllm.ai/), [llama.cpp](https://github.com/ggerganov/llama.cpp), [SGLang](https://github.com/sgl-project/sglang), and any OpenAI-compatible server |

Switch providers with `spark model` or by editing `~/.spark/.env`. See the [Environment Variables](./environment-variables.md) reference for all provider keys.

---

### Does Spark run on Windows?

Not natively — it requires a Unix-like environment. On Windows, install [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and run Spark from inside it. The standard installer works fine:

```bash
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash
```

---

### Where does my data go?

API calls go **only to the LLM provider you configure** — OpenRouter, a local Ollama instance, etc. Spark collects no telemetry, usage data, or analytics. Your conversations, memory, and skills are stored locally in `~/.spark/`.

---

### Can I run it fully offline with a local model?

Yes. Run `spark model`, select **Custom endpoint**, and point it at your server:

```bash
spark model
# Select: Custom endpoint (enter URL manually)
# API base URL: http://localhost:11434/v1
# API key: ollama
# Model name: qwen3.5:27b
# Context length: 32768   <- match your server's actual context window
```

Or edit `config.yaml` directly:

```yaml
model:
  default: qwen3.5:27b
  provider: custom
  base_url: http://localhost:11434/v1
```

Spark persists the endpoint across restarts. If your local server has exactly one model loaded, `/model custom` auto-detects it.

This works with Ollama, vLLM, llama.cpp server, SGLang, LocalAI, and others. See the [Configuration guide](../configuration.md) for details.

:::tip Ollama context size
If you set a custom `num_ctx` in Ollama (e.g., `ollama run --num_ctx 16384`), set the matching context length in Spark too. Ollama's `/api/show` reports the model's *maximum* context, not the effective `num_ctx` you configured.
:::

:::tip Timeout issues with local models
Spark auto-detects local endpoints and relaxes streaming timeouts (read timeout raised from 120s to 1800s, stale stream detection disabled). If you still hit timeouts on very large contexts, set `SPARK_STREAM_READ_TIMEOUT=1800` in your `.env`. See the [Local LLM guide](../guides/run-local-llm.md#timeouts) for details.
:::

---

### How much does it cost?

Spark Agent itself is **free and open-source** (MIT license). You pay only for the LLM API usage from your chosen provider. Local models cost nothing to run.

---

### Can multiple people share one instance?

Yes. The [messaging gateway](../chat-platforms/index.md) lets multiple users talk to the same instance via Telegram, Discord, Slack, WhatsApp, or Home Assistant. Access is controlled through allowlists (specific user IDs) or DM pairing (first person to message claims access).

---

### What's the difference between memory and skills?

| | What it stores | How it's used |
|-|----------------|---------------|
| **Memory** | Facts — things about you, your projects, preferences | Recalled automatically based on relevance |
| **Skills** | Procedures — step-by-step instructions for recurring tasks | Loaded when the agent encounters a matching task |

Both survive across sessions. See [Memory](../memory/index.md) and [Skills](../skills/index.md) for details.

---

### Can I use Spark in a Python project?

Yes. Import `AIAgent` and call it directly:

```python
from run_agent import AIAgent

agent = AIAgent(model="openrouter/nous/spark-3-llama-3.1-70b")
response = agent.chat("Explain quantum computing briefly")
```

See the [Python Library guide](../tools/code-execution.md) for the full API.

---

## Installation Problems

### `spark: command not found` after installing

Your shell hasn't reloaded the updated PATH.

```bash
source ~/.bashrc    # bash
source ~/.zshrc     # zsh
```

Or just open a new terminal. If it still fails, check the install location:

```bash
which spark
ls ~/.local/bin/spark
```

:::tip
The installer adds `~/.local/bin` to your PATH. If you use a non-standard shell config, add `export PATH="$HOME/.local/bin:$PATH"` manually.
:::

---

### Python version too old

Spark requires Python 3.11 or newer.

```bash
python3 --version   # check what you have

# Install a newer version:
sudo apt install python3.12   # Ubuntu/Debian
brew install python@3.12      # macOS
```

---

### `uv: command not found`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

---

### Permission denied during install

Don't use `sudo` with the installer — it installs to `~/.local/bin`. If you previously installed with sudo, clean up first:

```bash
sudo rm /usr/local/bin/spark
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash
```

---

## Provider & Model Problems

### API key not working

```bash
spark config show               # see what's configured
spark model                     # reconfigure your provider
spark config set OPENROUTER_API_KEY sk-or-v1-xxxxxxxxxxxx   # or set directly
```

:::warning
Make sure the key matches the provider. An OpenAI key won't work with OpenRouter. Check `~/.spark/.env` for conflicting entries.
:::

---

### Model not found

```bash
spark model                                                # browse available models
spark config set SPARK_MODEL openrouter/nous/spark-3-llama-3.1-70b
spark chat --model openrouter/meta-llama/llama-3.1-70b-instruct   # per-session override
```

---

### Rate limiting (429 errors)

You've hit your provider's rate limits. Wait and retry. For sustained usage:
- Upgrade your provider plan
- Switch to a different model or provider
- Use `spark chat --provider <alternative>` to route to another backend

---

### Context length exceeded

The conversation outgrew the model's context window, or Spark detected the wrong context size.

```bash
/compress                                              # compress current session
spark chat                                             # start fresh
spark chat --model openrouter/google/gemini-3-flash-preview   # larger context
```

Check the detected context length in the CLI startup line (e.g., `Context limit: 128000 tokens`), or use `/usage` mid-session.

To fix context detection, set it explicitly in `~/.spark/config.yaml`:

```yaml
model:
  default: your-model-name
  context_length: 131072
```

For custom endpoints, per-model overrides:

```yaml
custom_providers:
  - name: "My Server"
    base_url: "http://localhost:11434/v1"
    models:
      qwen3.5:27b:
        context_length: 32768
```

See [Context Length Detection](../integrations/providers.md#context-length-detection) for how auto-detection works.

---

## Terminal Problems

### Command blocked as dangerous

Spark flagged a potentially destructive command (e.g., `rm -rf`, `DROP TABLE`). This is intentional.

Review the command and type `y` to approve it. Or ask the agent to use a safer alternative.

:::tip
This is working as intended — Spark never silently runs destructive commands. The approval prompt shows exactly what will execute.
:::

---

### `sudo` not working via messaging gateway

The messaging gateway runs without an interactive terminal, so `sudo` can't prompt for a password.

Options:
- Avoid `sudo` in messaging — ask the agent for alternatives
- Configure passwordless sudo for specific commands in `/etc/sudoers`
- Use `spark chat` for tasks that require admin access

---

### Docker backend not connecting

```bash
docker info                        # verify Docker is running
sudo usermod -aG docker $USER      # add your user to the docker group
newgrp docker
docker run hello-world             # verify it works
```

---

## Messaging Problems

### Bot not responding

```bash
spark gateway status               # check if it's running
spark gateway start                # start it
cat ~/.spark/logs/gateway.log | tail -50   # check logs
```

Make sure your user ID is in the allowlist for that platform.

---

### Messages not delivering

- Verify your bot token with `spark gateway setup`
- Check logs: `cat ~/.spark/logs/gateway.log | tail -50`
- For webhook-based platforms (Slack, WhatsApp), your server must be publicly reachable

---

### Who can talk to the bot?

| Mode | How it works |
|------|-------------|
| **Allowlist** | Only user IDs in config can interact |
| **DM pairing** | First user to DM claims exclusive access |
| **Open** | Anyone can interact — not recommended for production |

Configure this in `~/.spark/config.yaml` under your platform's settings. See the [Messaging docs](../chat-platforms/index.md).

---

### Gateway won't start

```bash
pip install "spark-agent[telegram]"   # or [discord], [slack], [whatsapp]
lsof -i :8080                         # check for port conflicts
spark config show                     # verify config
```

---

### WSL: Gateway keeps disconnecting

WSL's systemd support is unreliable. Use foreground mode instead:

```bash
# Option 1: Direct foreground (simplest)
spark gateway run

# Option 2: Persistent via tmux
tmux new -s spark 'spark gateway run'
# Reattach: tmux attach -t spark

# Option 3: Background via nohup
nohup spark gateway run > ~/.spark/logs/gateway.log 2>&1 &
```

If you want systemd anyway, enable it first:

1. Open (or create) `/etc/wsl.conf`
2. Add:
   ```ini
   [boot]
   systemd=true
   ```
3. From PowerShell: `wsl --shutdown`
4. Reopen your WSL terminal
5. Verify: `systemctl is-system-running`

:::tip Auto-start on Windows boot
Use Windows Task Scheduler to launch WSL + the gateway on login. Create a task that runs `wsl -d Ubuntu -- bash -lc 'spark gateway run'` and trigger it on user logon.
:::

---

### macOS: Node.js / ffmpeg not found by gateway

launchd services inherit a minimal PATH that doesn't include Homebrew, nvm, or other user-installed tools. The gateway captures your shell PATH when you run `spark gateway install`. If you installed tools after setting up the gateway, re-run it:

```bash
spark gateway install    # re-snapshots your current PATH
spark gateway start      # detects the updated plist and reloads
```

Verify the plist has the right PATH:

```bash
/usr/libexec/PlistBuddy -c "Print :EnvironmentVariables:PATH" \
  ~/Library/LaunchAgents/ai.spark.gateway.plist
```

---

*More help: [Configuration](../configuration.md), [CLI commands](../cli/commands-reference.md), [Messaging](../chat-platforms/index.md).*
