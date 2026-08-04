# SKILL-08 evaluation harness

This harness compares baseline and candidate skill behavior on the same public,
synthetic cases. It pins provider, model, and reasoning effort; gives every
trial a disposable `HOME`/`SPARK_HOME` and config; resumes only complete rows;
and stops before persisting a result that would exceed the token or USD cap.
The machine-readable contract is in `schema.json`; the Python dataclasses and
validators are in `schema.py`.

The default fake adapter is deterministic, offline, and zero-cost:

```bash
python evals/skills/runner.py validate
python evals/skills/runner.py run --trials 2 --output /tmp/skill-responses.jsonl
python evals/skills/runner.py blind --input /tmp/skill-responses.jsonl \
  --packet /tmp/judge-packet.json --key /tmp/condition-key.json
python evals/skills/runner.py fixture-score --input /tmp/skill-responses.jsonl \
  --output /tmp/fixture-scores.jsonl
python evals/skills/runner.py compare /tmp/fixture-scores.jsonl
```

The judge packet contains only opaque A/B labels. Keep the condition key
separate from judges and open it only during comparison. Fixture scoring is a
CI sanity check; release decisions should use blinded human or approved judge
scores with the same schema.

For a real adapter, supply a command with `--adapter subprocess --command`.
The command receives one JSON request on stdin and must return one normalized
JSON result. It inherits the isolated environment and the pinned runtime, but
the harness does not provide credentials or enable network access.
