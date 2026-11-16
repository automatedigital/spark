# Contributing to Spark

Thank you for your help. Read [AGENTS.md](AGENTS.md) first. It is the
canonical development guide. [CONTEXT.md](CONTEXT.md) defines the domain
vocabulary, and [STRUCTURE.md](STRUCTURE.md) maps the source.

## Set up

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,web]"
pip install pre-commit  # optional local checks
pre-commit install
```

Use Node.js 22 for the web frontend:

```bash
node --version
node -p process.execPath
(cd src/spark_cli/web && npm ci)
```

## Check your change

```bash
python -m pytest tests/ -m "not slow and not integration and not network" -q -n 0
ruff check src/
mypy src/agent/ src/spark_cli/
python scripts/generate_tool_manifest.py --check
(cd src/spark_cli/web && npm run lint && npm test && npm run build)
```

Use an isolated `SPARK_HOME` for manual tests. Do not test against real user
state.

## Pull requests

1. Make a branch with a `feat/`, `fix/` or `docs/` prefix.
2. Keep each pull request to one change.
3. Fill in the pull request template, with the commands you ran.
4. Do not edit generated files (`tools/generated_manifest.py`, `web_dist/`)
   by hand.

## Security

Report vulnerabilities privately. See [SECURITY.md](SECURITY.md).
