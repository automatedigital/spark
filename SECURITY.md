# Security policy

## Report a vulnerability

Do not open a public issue for a security problem.

Report it privately through
[GitHub Security Advisories](https://github.com/automatedigital/spark/security/advisories/new).
Include:

- The affected component (agent loop, tool, gateway, dashboard, desktop app).
- The Spark version or commit.
- Steps to reproduce, and the effect you saw.

## Supported versions

Please reproduce against the latest release or `main` when possible, and
include whether older releases are affected.

## Scope notes

Spark runs tools with the permissions of the user who starts it. Items that
are in scope:

- Escape from a configured sandbox or approval gate.
- Prompt-injection paths that run tools without the configured approval.
- Credential or `SPARK_HOME` data leaks through the dashboard, gateway or logs.
- Authentication bypass on the dashboard or gateway.

Explain the relevant approval and sandbox settings when reporting unexpected
tool behavior.
