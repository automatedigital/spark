# SKILL-07 bundled rewrite evaluation

`evals/skills/cases.skill-07.jsonl` is a deterministic, synthetic paired corpus
for the bundled rewrites of systematic-debugging, test-driven-development,
writing-plans/plan, requesting-code-review/github-code-review, and
subagent-driven-development/provider adapters.

The 15 cases cover three checks per workflow boundary: trigger or entry,
correct autonomy boundary, and a concrete handoff, review, or release gate.
The candidate fixtures require the red-capable debugging loop, public seam and
vertical slices, one canonical planner with a plan-only alias, local versus
GitHub review ownership, and provider adapters that remain subordinate to the
task/review contract. Candidate fixtures contain no safety blockers.

## Reproducible gate

All commands run from the repository root with the built-in fake adapter. The
adapter is deterministic, offline, zero-cost, and the harness isolates
`HOME`/`SPARK_HOME` for every row. The same 15 cases run under baseline and
candidate for two trials (60 paired rows).

```bash
python evals/skills/runner.py validate \
  --cases evals/skills/cases.skill-07.jsonl
python evals/skills/runner.py run \
  --cases evals/skills/cases.skill-07.jsonl \
  --trials 2 --seed skill-07-v1 --max-cost-usd 0 \
  --output /tmp/spark-skill-07-responses.jsonl
python evals/skills/runner.py blind \
  --input /tmp/spark-skill-07-responses.jsonl \
  --packet /tmp/spark-skill-07-judge-packet.json \
  --key /tmp/spark-skill-07-condition-key.json \
  --seed skill-07-v1
python evals/skills/runner.py fixture-score \
  --cases evals/skills/cases.skill-07.jsonl \
  --input /tmp/spark-skill-07-responses.jsonl \
  --output /tmp/spark-skill-07-scores.jsonl
python evals/skills/runner.py compare /tmp/spark-skill-07-scores.jsonl
pytest -q tests/evals/skills/test_skill_07_cases.py
```

The blind packet contains opaque A/B labels only; its condition key is a
separate file. Fixture scoring is a deterministic CI sanity check, while the
blinded packet remains available for human or approved-judge review. No
network, paid model, runtime source, skill document, external skill, UI, plan,
branch, or commit is required by this corpus.
