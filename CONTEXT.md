# Spark — Domain Glossary

Canonical language for the Spark Agent project. This file is a glossary, not a
spec — it defines terms, not implementations. When code or conversation drifts
from these definitions, that drift is a bug in one or the other.

Development rules live in [AGENTS.md](AGENTS.md); implementation ownership is in
[STRUCTURE.md](STRUCTURE.md). [PLAN.md](PLAN.md) describes proposed upgrades.
Terms marked **planned** below establish vocabulary without claiming those
contracts or controls are already implemented.

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
The always-on local memory store under the active Spark home (`memories/`),
full-text searchable.
Distinct from optional memory **provider plugins** (Mem0, Honcho, Hindsight, …),
which supply an optional external backend through the same abstraction. The
memory manager retains the built-in provider and permits at most one external
provider; configuring a plugin does not remove the built-in provider.

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

Durable board tasks are owned by Kanban (`kanban.db`), including dependencies,
claims, review and task-run history. A task can span multiple execution attempts;
it is not the same as one conversation turn or an agent's temporary todo item.

### Run
A single user-visible execution turn within a Thread. The upgrade plan maps this
to the existing web `turn_id`; a unified cross-surface contract is **planned**.
Only authoritative root execution completion finishes a Run. Completion of one
tool or child agent does not finish the parent Run.

### Attempt
One execution try within a Run, distinct from a retryable HTTP request or a
Kanban task-run record. Explicit retries retain the earlier outcome. The unified
Run/Attempt relationship is **planned**; do not infer it from existing field names.

### Execution node *(planned)*
An app-owned unit of root work, tool execution, child agent or pending decision,
with explicit parent/root relationships. Provider-native IDs are correlation
references rather than Spark identity. This vocabulary guides the upgrade and
does not imply an execution-graph service already exists.

### Pending decision
A request for approval or user input with its own identity and respondability.
Waiting for a decision differs from disconnected or failed execution. Persisted
requests must be reconciled with a live responder after restart before an answer
can be accepted.

### Subagent
A delegated child agent spawned from a parent thread. A subagent has its own
child thread/transcript, but should remain visually attached to the parent thread:
show subagents in the same right-side project/task sidebar pattern, and let users
open a subagent thread in that sidebar while the main parent chat stays visible in
the center.

Spark currently supports synchronous single/batch delegation with persisted
lifecycle records. Durable asynchronous handles, cancellation and completion
delivery are **planned** extensions. A child transcript is not an independent
top-level task request. Preserve restricted child tools and permission scope.

### Worktree isolation *(planned for delegated work)*
A separate Git checkout/branch rooted at a recorded commit for a coding child.
It does not include the parent's uncommitted changes. It is distinct from isolated
conversation context or a container/remote terminal backend. Requested isolation
must report unsupported configurations rather than silently sharing files.

### Inbox and attention
The existing navigation surface for conversations that need attention or have
background outcomes. Attention is derived from structured execution/decision
state, distinct from unread text. A completion cannot conceal an unresolved
decision.

### Settled thread *(planned durable metadata)*
A thread parked outside active work without deleting its transcript or stopping
execution. Distinct from a completed Run, resolved decision, archived skill or
finished Task. Server-owned settlement/order and Undo are planned sidebar work;
snooze and automatic settlement are follow-on scope.

### Provider capability *(planned shared contract)*
An explicit, versioned statement of supported runtime behavior, including an
unsupported reason. It drives controls such as interruption and resume. Model
availability, authentication and actual lifecycle support are separate facts.

### Context handoff *(planned)*
An explicit, source-linked context artifact for a fork or provider transition at
a stable execution boundary. It preserves lineage and coverage. It never means
silently rewriting a conversation's cached system prompt or historical messages.

### Projection and replay cursor
A projection is a derived view of confirmed state. Spark has durable per-session
events/checkpoints in `state.db` and a separate bounded web delivery journal.
The journal uses a process epoch and sequence; its cursor is not interchangeable
with a session event sequence. Expired cursors or a server restart require a new
authoritative snapshot, not automatic re-execution of a prompt.

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
