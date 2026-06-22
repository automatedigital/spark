# Spark — Domain Glossary

Canonical language for the Spark Agent project. This file is a glossary, not a
spec — it defines terms, not implementations. When code or conversation drifts
from these definitions, that drift is a bug in one or the other.

## Terms

### Dream
The **heavy, on-demand** reflective synthesis pass. Reads recent session
transcripts plus the holographic memory store, runs a single LLM synthesis, and
writes consolidated facts back into memory (category `dream`) plus a human-readable
wiki review entry. Stale facts are *queued for confirmation*, never auto-deleted.
Dream is also the **compaction** pass for MEMORY.md — it dedups and consolidates the
cruft that Auto-memory appends over time (the heavy cleanup to Auto-memory's cheap
append). **Dream runs only when explicitly invoked** — the `/dream` command or a
user-set cron/schedule. It must **never** fire implicitly at session end or on any
per-turn event. Dream is distinct from Auto-memory (below).

### Auto-memory
The **lightweight, always-on** memory maintenance that runs without the user asking.
Two surfaces, both updated automatically:
- **Holographic memory** — facts auto-extracted from a conversation at session end
  (the `auto_extract` path in the holographic provider).
- **MEMORY.md** — the agent's curated long-term notes file, auto-distilled/updated
  from the session rather than only when the model happens to call the memory tool
  mid-conversation.
Auto-memory is cheap, runs on every session, and is the default "gets smarter over
time" behavior. It does **not** invoke Dream.

### Holographic memory
The always-on local memory store (`~/.spark/memories/`), full-text searchable.
Distinct from optional memory **provider plugins** (Mem0, Honcho, Hindsight, …),
which swap the backend but keep the same abstraction.

### SOUL.md
The persistent agent identity/preferences file loaded into every normal
conversation. User edits outrank the default base voice. Not auto-mutated by Dream
or Auto-memory (those write to holographic memory + MEMORY.md, never SOUL.md).

### Workspace *(deprecated term)*
Historically a separate IDE-like dashboard surface. **No longer exists as a
distinct concept** — its file-tree + terminal + multi-thread chat capabilities
were folded into **Chat** (`ChatPage`). The lingering `WorkspacePage.tsx` is
stale duplicate code, not a live surface. Prefer "Chat" for the dashboard's
primary surface.

### Chat (dashboard surface)
The canonical primary surface of the web dashboard (`ChatPage`): multi-thread
conversation plus an embedded file tree (`FileTreePane`) and terminal
(`WorkspaceTerminalPanel`). Supersedes the former Workspace surface.

### Thread
A durable Spark conversation. A thread is either a **Chat thread** or a
**Project thread**.

### Chat thread
A thread with no project binding. Use for general conversation, one-off tasks,
and work that should not be grouped under a project.

### Project thread
A thread bound to a Project. Use when the conversation should live with the
project's related files, previews, tasks, and changes.

### Project
A named work container for related files, previews, tasks, changes, and project
threads. Prefer Project over Workspace when describing user-facing work groups.

### Quick Ask
A lightweight macOS entry surface for starting or sending a brief prompt without
opening the full Chat workbench. Quick Ask can expand into Chat when the task
needs project context, files, panels, or longer interaction.

### Artifact
A durable work product produced, opened, or managed from a thread. Artifacts
include canvases and tasks; they should stay connected to the conversation that
created or uses them.

### Canvas
A visual artifact that can open as a full-screen work surface when it needs
focused editing or inspection.

### Task
A trackable work artifact that belongs near the active thread or project. Tasks
should appear contextually, especially in the Chat project panel, and expand only
when the user needs more detail.

### Subagent
A delegated child agent spawned from a parent thread. A subagent has its own
child thread/transcript, but should remain visually attached to the parent thread:
show subagents in the same right-side project/task sidebar pattern, and let users
open a subagent thread in that sidebar while the main parent chat stays visible in
the center.

### Toolset
A named bundle of tools (`_SPARK_CORE_TOOLS` and others in `toolsets.py`) that
can be enabled/disabled per platform. Changing the active toolset mid-conversation
breaks prompt caching and is disallowed outside compression.

### Gateway
The long-running process bridging Spark to messaging platforms (Telegram,
Discord, Slack, …). Also hosts the 60-second tick that drives scheduled work
(cron, Dream scheduler).

### Profile
A named, isolated Spark instance under `~/.spark/profiles/<name>/`. All code must
resolve paths via `get_spark_home()` so profiles stay isolated — never hardcode
`~/.spark`.
