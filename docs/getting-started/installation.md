---
sidebar_position: 2
title: "Installation"
description: "Install Spark Agent on Linux, macOS, or WSL2."
---

# Installation

## One-command install

Paste this into your terminal. The installer handles Python 3.11, Node, ripgrep, ffmpeg, the repo, and a virtual environment for you:

```bash
curl -fsSL https://raw.githubusercontent.com/automatedigital/spark/main/scripts/install.sh | bash
```

Reload your shell when it's done, then launch:

```bash
spark
```

:::warning Using Windows?
Native Windows isn't supported. Use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) and run the installer from there.
:::

## Finish setting up

Once installed, run whichever of these apply to you:

```bash
spark model          # choose your AI provider and model
spark tools          # pick which toolsets to enable
spark gateway setup  # connect to Telegram, Slack, etc. (optional)
spark config set     # adjust individual settings
spark setup          # or run the full setup wizard
```

## Verify it works

```bash
spark version && spark doctor && spark chat -q "What tools do you have?"
```

## Manual install

Prefer to do it yourself? Here's the full process:

1. **Clone the repo** (with submodules):
   ```bash
   git clone --recurse-submodules https://github.com/automatedigital/spark.git && cd spark
   ```

2. **Create a virtual environment**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv venv venv --python 3.11
   export VIRTUAL_ENV="$(pwd)/venv"
   ```

3. **Install dependencies**:
   ```bash
   uv pip install -e ".[all]"   # everything
   # or: uv pip install -e "."  # core only
   ```

4. **Optional extras**:
   ```bash
   uv pip install -e "./tinker-atropos"   # RL training
   npm install                             # browser tools or WhatsApp
   ```

5. **Create your config folder**: `mkdir -p ~/.spark/{cron,sessions,logs,memories,skills,...}` — see [Configuration](/docs/configuration). Copy `docs/cli-config.yaml.example` to `~/.spark/config.yaml` and add your API keys to `~/.spark/.env`.

6. **Add to PATH**:
   ```bash
   ln -sf "$(pwd)/venv/bin/spark" ~/.local/bin/spark
   ```
   Make sure `~/.local/bin` is in your `PATH`.

## Optional feature extras

Install only what you need. Combine multiple extras in one command:

```bash
uv pip install -e ".[messaging,cron,mcp]"
```

| Extra | What it adds |
|-------|---------|
| `all` | Everything |
| `dev` | Development tools (pytest, ruff, mypy, etc.) |
| `messaging` | Telegram, Discord, and Slack gateway support |
| `cron` | Schedule tasks using natural language |
| `mcp` | Connect to MCP tool servers |
| `acp` | Use Spark inside VS Code, Zed, or JetBrains |
| `voice` | Local speech-to-text (powered by faster-whisper) |
| `tts-premium` | ElevenLabs text-to-speech |
| `cli`, `pty`, `honcho`, `matrix`, … | See `pyproject.toml` for the full list |

## Contributing to Spark

```bash
pip install -e ".[dev]"
ruff check src/                  # run the linter
mypy src/agent/ src/spark_cli/   # check types
python -m pytest tests/ -q       # run tests
```

## Troubleshooting

| Problem | Fix |
|-------|-----|
| `spark: not found` | Run `source ~/.bashrc` (or `~/.zshrc`) and check that `~/.local/bin` is in your `PATH` |
| Missing API key error | Run `spark model` to set up a provider, or `spark config set OPENROUTER_API_KEY …` |
| Config looks wrong | Run `spark config check` or `spark config migrate` |
