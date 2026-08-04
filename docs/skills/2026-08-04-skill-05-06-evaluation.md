# SKILL-05/06 content evaluation corpus

`evals/skills/cases.skill-05-06.jsonl` is a deterministic, synthetic fixture
corpus for evaluating the installed planning/orchestration and codebase/domain
design skills named by PLAN SKILL-05 and SKILL-06:

- `wayfinder`, `grill-me`, and `grill-with-docs`
- `research` and `prototype`
- `codebase-design` and `domain-modeling`

The cases exercise trigger precision, autonomy boundaries, artifact quality,
GitHub issue/triage operations, ordinary prompt cost, and Spark's
`CONTEXT.md`/`docs/adr/` architecture contract. Every skill has three cases:
trigger or invocation, boundary behavior, and an artifact or contract check.

## Fixture interpretation

This is content-evaluation infrastructure, not a model-quality result. The
existing SKILL-08 harness runs identical public synthetic prompts under two
conditions:

- `baseline` represents an unsafe or incomplete generic behavior.
- `candidate` represents the expected skill-aware behavior and records the
  expected actions and provenance in fixture metadata.

The fake adapter is deterministic, offline, zero-cost, and uses the harness's
isolated `HOME`/`SPARK_HOME`. No external skill is copied or modified, and no
paid or network model is required. Human or approved blinded judging remains
necessary before using these cases as a release decision.

## Validation

From the repository root:

```bash
python evals/skills/runner.py validate \
  --cases evals/skills/cases.skill-05-06.jsonl
python evals/skills/runner.py run \
  --cases evals/skills/cases.skill-05-06.jsonl \
  --trials 2 --seed skill-05-06-v1 \
  --output /tmp/spark-skill-05-06-responses.jsonl
python evals/skills/runner.py fixture-score \
  --cases evals/skills/cases.skill-05-06.jsonl \
  --input /tmp/spark-skill-05-06-responses.jsonl \
  --output /tmp/spark-skill-05-06-scores.jsonl
python evals/skills/runner.py compare /tmp/spark-skill-05-06-scores.jsonl
pytest -q tests/evals/skills/test_skill_05_06_cases.py
```

The focused test expects 21 cases and 84 paired rows at two trials. It also
checks that the three explicit user-only wrappers are represented as excluded
from the ordinary prompt index, while `research`, `prototype`,
`codebase-design`, and `domain-modeling` are represented as request-triggered
workflows. The GitHub case encodes Spark's `gh issue` operations,
`wayfinder:map`, canonical triage labels, and named linked tickets. The
architecture cases encode the glossary-only role of `CONTEXT.md` and the
sparse, conditional role of `docs/adr/`.
