# Response efficiency evaluation

This harness compares baseline and candidate prompts with identical cases,
runner, model, reasoning effort, and trial counts. Runs use a temporary HOME
and SPARK_HOME, resume completed rows, enforce a cost cap, and preserve exact
runner/version metadata. Generate `judge-packet.json` before review so judges
see stable A/B labels rather than condition names.

```bash
python evals/response_efficiency/run.py validate
python evals/response_efficiency/run.py run --condition baseline --trials 3
python evals/response_efficiency/run.py run --condition candidate --trials 3
python evals/response_efficiency/run.py blind
python evals/response_efficiency/run.py score evals/response_efficiency/results/scores.jsonl
```

The bundled fixture runner is deterministic and cost-free for CI. Published
product claims must use a real isolated runner with the same pinned model and
reasoning configuration for both conditions.
