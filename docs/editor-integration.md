# Spark Agent — Editor Integration via ACP

Connect Spark Agent to your editor using the **Agent Client Protocol (ACP)**. Once connected, you send tasks from your IDE and Spark responds with file edits, terminal commands, and explanations — all shown natively in the editor UI.

---

## Prerequisites

- Spark Agent installed and working (`spark setup` completed)
- An API key / provider set up in `~/.spark/.env` or via `spark login`
- Python 3.11+

Install the ACP extra:

```bash
pip install -e ".[acp]"
```

---

## VS Code

### 1. Install the ACP Client extension

```bash
code --install-extension anysphere.acp-client
```

Or: press `Ctrl+Shift+X` (`Cmd+Shift+X` on macOS), search **"ACP Client"**, and click Install.

### 2. Configure settings.json

Open VS Code settings (`Ctrl+,` -> click `{}` for JSON) and add:

```json
{
  "acpClient.agents": [
    {
      "name": "spark-agent",
      "registryDir": "/path/to/spark-agent/acp_adapter/registry"
    }
  ]
}
```

Replace `/path/to/spark-agent` with the actual path to your Spark Agent installation (e.g. `~/.spark/spark-agent`).

### 3. Restart VS Code

**Spark Agent** will appear in the ACP agent picker in the chat/agent panel.

---

## Zed

Zed has built-in ACP support.

### 1. Configure settings.json

Open Zed settings (`Cmd+,` on macOS or `Ctrl+,` on Linux) and add:

```json
{
  "agent_servers": {
    "spark-agent": {
      "type": "custom",
      "command": "spark",
      "args": ["acp"],
    },
  },
}
```

### 2. Restart Zed

Spark Agent appears in the agent panel. Select it and start a conversation.

---

## JetBrains (IntelliJ, PyCharm, WebStorm, etc.)

### 1. Install the ACP plugin

Open **Settings** -> **Plugins** -> **Marketplace**, search for **"ACP"** or **"Agent Client Protocol"**, install, and restart.

### 2. Configure the agent

Go to **Settings** -> **Tools** -> **ACP Agents**, click **+**, and set the registry directory to:

```
/path/to/spark-agent/acp_adapter/registry
```

### 3. Use the agent

Open the ACP panel (usually in the right sidebar) and select **Spark Agent**.

---

## What You Get in the Editor

Once connected, your editor provides a native interface with four components:

**Chat Panel** — describe tasks, ask questions, give instructions. Spark explains what it's doing alongside taking action.

**File Diffs** — when Spark edits files, you see standard diffs. Accept individual changes, reject ones you don't want, or review the full diff before anything applies.

**Terminal Commands** — when Spark needs to run shell commands (builds, tests, installs), they appear in an integrated terminal. Depending on your settings, they run automatically or wait for your approval.

**Approval Flow** — for destructive operations (file deletions, shell commands, git operations), the editor prompts you before Spark proceeds.

---

## Configuration

ACP sessions use the same config as the CLI:

| Config | Location |
|--------|----------|
| API keys / providers | `~/.spark/.env` |
| Agent config | `~/.spark/config.yaml` |
| Skills | `~/.spark/skills/` |
| Sessions | `~/.spark/state.db` |

### Changing the model

```yaml
# ~/.spark/config.yaml
model: openrouter/nous/spark-3-llama-3.1-70b
```

Or set the `SPARK_MODEL` environment variable.

### Toolsets

ACP sessions use the `spark-acp` toolset by default — designed for editor workflows, it intentionally excludes messaging delivery, cron management, and audio-first features.

---

## Troubleshooting

### Agent doesn't appear in the editor

1. Verify the `acp_adapter/registry/` directory path in your editor settings is correct and contains `agent.json`
2. Check `spark` is on your PATH: `which spark`. If not found, activate your virtualenv or add it to PATH
3. Restart the editor after changing settings

### Agent starts but errors immediately

1. Run `spark doctor` to check your configuration
2. Verify you have a valid API key: `spark status`
3. Run `spark acp` directly in a terminal to see error output

### "Module not found" errors

```bash
pip install -e ".[acp]"
```

### Slow responses

ACP streams responses — you should see incremental output. If the agent appears stuck, check your network and provider status. Some providers have rate limits; try switching models.

### Permission denied for terminal commands

Check your ACP Client extension settings for auto-approval or manual-approval preferences.

### Logs

Spark logs are written to stderr in ACP mode:

| Editor | Where to look |
|--------|---------------|
| VS Code | **Output** panel -> **ACP Client** or **Spark Agent** |
| Zed | **View** -> **Toggle Terminal** -> process output |
| JetBrains | **Event Log** or the ACP tool window |

Enable verbose logging:

```bash
SPARK_LOG_LEVEL=DEBUG spark acp
```

---

## Further Reading

- [ACP Specification](https://github.com/anysphere/acp)
- [Spark Agent Documentation](https://github.com/automatedigital/spark)
- `spark --help` for all CLI options
