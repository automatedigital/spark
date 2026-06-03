# Execution backends

Every shell command the agent runs goes through a **backend** implementing the
`BaseEnvironment` ABC (`base.py`). The `terminal_tool.py` factory
`_create_environment(env_type, …)` picks one based on config (`terminal.backend`)
or the `TERMINAL_ENV` env var. All backends expose the same `execute()` /
`_run_bash()` interface, so tools are backend-agnostic.

## Available backends

| `env_type` | class | where commands run | isolation |
|------------|-------|--------------------|-----------|
| `local` *(default)* | `LocalEnvironment` | the host shell | none — full host access |
| `docker` | `DockerEnvironment` | a Docker container | strong (container) |
| `ssh` | `SSHEnvironment` | a remote host over SSH | remote machine |
| `singularity` | `SingularityEnvironment` | a Singularity/Apptainer image | strong (container) |
| `modal` / managed | `ModalEnvironment` / `ManagedModalEnvironment` | a Modal cloud sandbox | strong, serverless |
| `daytona` | `DaytonaEnvironment` | a Daytona dev sandbox | strong, serverless |

## Selecting a backend

- **Config:** `terminal.backend: docker` in `config.yaml` (default `local`).
- **Env var:** `TERMINAL_ENV=ssh` overrides at process start.
- **TUI:** `/backend` shows the current backend; `/backend <name>` sets and
  persists `terminal.backend`.

## When to sandbox

`local` gives the agent full host access — appropriate for a trusted personal
machine. For untrusted input, shared/group gateway sessions, or risky commands,
use a sandboxed backend (`docker`/`ssh`/`modal`/`daytona`) so command execution
is isolated from the host. The shared `_wait_for_process` loop (in `base.py`)
provides interrupt handling, activity heartbeats, and incremental stdout
streaming uniformly across all backends.
</content>
