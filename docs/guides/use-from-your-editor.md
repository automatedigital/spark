---
sidebar_position: 23
title: "Use From Your Editor"
description: "Spark via ACP in VS Code, Zed, and JetBrains."
---

# Use Spark from Your Editor

With [ACP](../integrations/acp.md), Spark runs inside your IDE. Chat, tool calls, diffs, and terminal output — all in-panel, without switching windows.

Supported editors: VS Code, Zed, JetBrains.

## Setup

1. Install the **ACP extension** for your editor (check your editor's extension marketplace or vendor docs).
2. Make sure Spark is on your `PATH` and configured. See the [Installation guide](../getting-started/installation.md).
3. Start the **ACP adapter** from Spark:
   ```bash
   spark acp
   ```
   Full setup details are in the [ACP setup guide](../editor-integration.md).

## What to Expect

- You get the same toolsets and models as the CLI.
- Session storage follows your active profile.
- Add project [context files](../tools/context-files.md) (`AGENTS.md`, `.spark.md`) so the agent automatically picks up your repo's conventions.

## See Also

- [ACP feature doc](../integrations/acp.md)
- [Developer: ACP internals](../building/editor-extension-internals.md)
