---
sidebar_position: 12
title: "Batch Processing"
description: "Generate agent trajectories at scale - parallel processing, checkpointing, and toolset distributions"
---

# Batch Processing

Give the batch runner a JSONL file of prompts and it runs each one through a full agent session — in parallel, with tool access, and with automatic checkpointing so an interrupted run picks up where it left off.

The primary use case is **training data generation**: producing ShareGPT-format trajectories with tool usage statistics for fine-tuning or evaluation.

## Run Your First Batch

```bash
python batch_runner.py \
    --dataset_file=data/prompts.jsonl \
    --batch_size=10 \
    --run_name=my_first_run \
    --model=anthropic/claude-sonnet-4-6 \
    --num_workers=4
```

Got interrupted? Resume with:

```bash
python batch_runner.py \
    --dataset_file=data/prompts.jsonl \
    --batch_size=10 \
    --run_name=my_first_run \
    --resume
```

See what toolset distributions are available:

```bash
python batch_runner.py --list_distributions
```

## Dataset Format

One JSON object per line. Every entry needs a `prompt` field:

```jsonl
{"prompt": "Write a Python function that finds the longest palindromic substring"}
{"prompt": "Create a REST API endpoint for user authentication using Flask"}
{"prompt": "Debug this error: TypeError: cannot unpack non-iterable NoneType object"}
```

Optional fields per entry:

- `image` or `docker_image` — container image for this prompt's sandbox (works with Docker, Modal, and Singularity)
- `cwd` — working directory override for the task's terminal session

## Configuration

### Core Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--dataset_file` | required | Path to JSONL dataset |
| `--batch_size` | required | Prompts per batch |
| `--run_name` | required | Name for this run (drives output dir + checkpointing) |
| `--model` | `claude-sonnet-4-6` | Model to use |
| `--distribution` | `"default"` | Toolset distribution to sample from |
| `--num_workers` | `4` | Parallel worker processes |
| `--max_turns` | `10` | Max tool-calling iterations per prompt |
| `--max_samples` | all | Only process first N samples |
| `--max_tokens` | model default | Max tokens per model response |
| `--resume` | `false` | Resume from checkpoint |
| `--verbose` | `false` | Enable verbose logging |

### Provider Routing (OpenRouter)

| Parameter | Description |
|-----------|-------------|
| `--providers_allowed` | Comma-separated providers to allow (e.g., `"anthropic,openai"`) |
| `--providers_ignored` | Comma-separated providers to ignore (e.g., `"together,deepinfra"`) |
| `--providers_order` | Preferred provider order |
| `--provider_sort` | Sort by `"price"`, `"throughput"`, or `"latency"` |

### Reasoning Control

| Parameter | Description |
|-----------|-------------|
| `--reasoning_effort` | `none`, `minimal`, `low`, `medium`, `high`, or `xhigh` |
| `--reasoning_disabled` | Completely disable reasoning/thinking tokens |

### Advanced Options

| Parameter | Description |
|-----------|-------------|
| `--ephemeral_system_prompt` | System prompt used during execution but NOT saved to trajectories |
| `--log_prefix_chars` | Characters to show in log previews (default: 100) |
| `--prefill_messages_file` | JSON file with prefill messages for few-shot priming |

## Toolset Distributions

Each prompt gets a randomly sampled set of toolsets drawn from a **distribution**. This ensures your training data covers diverse tool combinations rather than always hitting the same tools.

Each distribution assigns a probability to each individual toolset. The sampler flips each one independently, then guarantees at least one toolset is enabled per prompt.

Run `--list_distributions` to see all available distributions.

## Output Structure

All output goes to `data/<run_name>/`:

```text
data/my_run/
 trajectories.jsonl    # Final merged output across all batches
 batch_0.jsonl         # Individual batch results
 batch_1.jsonl
 ...
 checkpoint.json       # Resume state
 statistics.json       # Aggregate tool usage stats
```

### Trajectory Format

Each line in `trajectories.jsonl`:

```json
{
  "prompt_index": 42,
  "conversations": [
    {"from": "human", "value": "Write a function..."},
    {"from": "gpt", "value": "I'll create that function...", "tool_calls": [...]},
    {"from": "tool", "value": "..."},
    {"from": "gpt", "value": "Here's the completed function..."}
  ],
  "metadata": {
    "batch_num": 2,
    "timestamp": "2026-01-15T10:30:00",
    "model": "anthropic/claude-sonnet-4-6"
  },
  "completed": true,
  "partial": false,
  "api_calls": 3,
  "toolsets_used": ["terminal", "file"],
  "tool_stats": {
    "terminal": {"count": 2, "success": 2, "failure": 0},
    "read_file": {"count": 1, "success": 1, "failure": 0}
  },
  "tool_error_counts": {
    "terminal": 0,
    "read_file": 0
  }
}
```

The `conversations` field uses ShareGPT-like format. Tool stats include zero defaults for all possible tools, ensuring a consistent schema for HuggingFace datasets compatibility.

## How Checkpointing Works

The batch runner tracks progress by **content**, not just index. On `--resume`:

1. Scans all `batch_*.jsonl` files for completed prompts by matching their actual text
2. Filters the dataset to exclude those prompts
3. Re-batches only the remaining work
4. Processes remaining prompts
5. Merges all batch files (old and new) into the final `trajectories.jsonl`

This means a resume works correctly even if the dataset order changed. Failed prompts are not marked as done and will be retried.

## Quality Filtering

Before writing the final output, the batch runner automatically drops low-quality entries:

- **No-reasoning filter** — samples where zero assistant turns contain reasoning (no `<REASONING_SCRATCHPAD>` or native thinking tokens) are discarded
- **Corrupted entry filter** — entries with hallucinated tool names (not in the valid tool list) are removed during the final merge

## Statistics

After a run completes, you'll see a summary covering:

- Tool call counts, success and failure rates per tool
- Reasoning coverage (percentage of assistant turns with reasoning)
- How many samples were discarded for lacking reasoning
- Total processing time

Stats are also written to `statistics.json` for programmatic analysis.

## Example Use Cases

### Training Data Generation

```bash
python batch_runner.py \
    --dataset_file=data/coding_prompts.jsonl \
    --batch_size=20 \
    --run_name=coding_v1 \
    --model=anthropic/claude-sonnet-4-6 \
    --num_workers=8 \
    --distribution=default \
    --max_turns=15
```

### Model Evaluation

```bash
python batch_runner.py \
    --dataset_file=data/eval_suite.jsonl \
    --batch_size=10 \
    --run_name=eval_gpt4 \
    --model=openai/gpt-4o \
    --num_workers=4 \
    --max_turns=10
```

### Per-Prompt Container Images

For benchmarks requiring specific environments, specify images inline:

```jsonl
{"prompt": "Install numpy and compute eigenvalues of a 3x3 matrix", "image": "python:3.11-slim"}
{"prompt": "Compile this Rust program and run it", "image": "rust:1.75"}
{"prompt": "Set up a Node.js Express server", "image": "node:20-alpine", "cwd": "/app"}
```

The batch runner verifies each Docker image is accessible before running the prompt.
