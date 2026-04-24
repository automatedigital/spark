---
sidebar_position: 5
title: "Using Spark as a Python Library"
description: "Embed AIAgent in your own Python scripts, web apps, or automation pipelines - no CLI required"
---

# Using Spark as a Python Library

You don't need the CLI to use Spark. Import `AIAgent` directly and embed it in your own scripts, web apps, or automation pipelines. Full tool access, conversation history, custom system prompts — all available programmatically.

---

## Installation

From the repository:

```bash
pip install git+https://github.com/automatedigital/spark.git
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install git+https://github.com/automatedigital/spark.git
```

Pin it in `requirements.txt`:

```text
spark-agent @ git+https://github.com/automatedigital/spark.git
```

:::tip
The same environment variables the CLI uses are required here. At minimum, set `OPENROUTER_API_KEY` (or `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` for direct provider access).
:::

---

## Basic Usage

The `chat()` method is the simplest entry point — pass a message, get a string back:

```python
from run_agent import AIAgent

agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    quiet_mode=True,
)
response = agent.chat("What is the capital of France?")
print(response)
```

`chat()` handles the full conversation loop internally — tool calls, retries, everything — and returns just the final text.

:::warning
Always set `quiet_mode=True` when embedding Spark in your own code. Without it, the agent prints CLI spinners, progress indicators, and other terminal output that will clutter your application.
:::

---

## Full Conversation Control

Use `run_conversation()` when you need access to the full response object — message history, metadata, and the final reply:

```python
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    quiet_mode=True,
)

result = agent.run_conversation(
    user_message="Search for recent Python 3.13 features",
    task_id="my-task-1",
)

print(result["final_response"])
print(f"Messages exchanged: {len(result['messages'])}")
```

The returned dictionary contains:

| Key | What it holds |
|-----|--------------|
| `final_response` | The agent's final text reply |
| `messages` | Complete message history (system, user, assistant, tool calls) |
| `task_id` | The task identifier used for VM isolation |

Override the system prompt for a single call:

```python
result = agent.run_conversation(
    user_message="Explain quicksort",
    system_message="You are a computer science tutor. Use simple analogies.",
)
```

---

## Configure Tool Access

Control which toolsets the agent can use:

```python
# Only enable web tools (search and browsing)
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    enabled_toolsets=["web"],
    quiet_mode=True,
)

# Enable everything except terminal access
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    disabled_toolsets=["terminal"],
    quiet_mode=True,
)
```

:::tip
Use `enabled_toolsets` when you want a minimal, locked-down agent. Use `disabled_toolsets` when you want most capabilities but need to block specific ones.
:::

---

## Multi-Turn Conversations

Pass message history back in to maintain context across turns:

```python
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    quiet_mode=True,
)

# First turn
result1 = agent.run_conversation("My name is Alice")
history = result1["messages"]

# Second turn — agent remembers the context
result2 = agent.run_conversation(
    "What's my name?",
    conversation_history=history,
)
print(result2["final_response"])  # "Your name is Alice."
```

The `conversation_history` parameter accepts the `messages` list from a previous result. The agent copies it internally — your original list is never mutated.

---

## Save Trajectories for Training Data

Capture conversations in ShareGPT format for training data or debugging:

```python
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    save_trajectories=True,
    quiet_mode=True,
)

agent.chat("Write a Python function to sort a list")
# Appends to trajectory_samples.jsonl in ShareGPT format
```

Each conversation is a single JSONL line, making it easy to collect datasets from automated runs.

---

## Custom System Prompts

Use `ephemeral_system_prompt` to guide behavior without polluting your training data. Ephemeral prompts are not saved to trajectory files:

```python
agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    ephemeral_system_prompt="You are a SQL expert. Only answer database questions.",
    quiet_mode=True,
)

response = agent.chat("How do I write a JOIN query?")
print(response)
```

This is how you build specialized agents — a code reviewer, a documentation writer, a SQL assistant — all using the same underlying tooling.

---

## Batch Processing

For many prompts in parallel, use `batch_runner.py`:

```bash
python batch_runner.py --input prompts.jsonl --output results.jsonl
```

Each prompt gets its own `task_id` and isolated environment. For custom batch logic, build directly on `AIAgent`:

```python
import concurrent.futures
from run_agent import AIAgent

prompts = [
    "Explain recursion",
    "What is a hash table?",
    "How does garbage collection work?",
]

def process_prompt(prompt):
    # Create a fresh agent per task for thread safety
    agent = AIAgent(
        model="anthropic/claude-sonnet-4",
        quiet_mode=True,
        skip_memory=True,
    )
    return agent.chat(prompt)

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(process_prompt, prompts))

for prompt, result in zip(prompts, results):
    print(f"Q: {prompt}\nA: {result}\n")
```

:::warning
Always create a **new `AIAgent` instance per thread or task**. The agent maintains internal state (conversation history, tool sessions, iteration counters) that is not thread-safe to share across concurrent calls.
:::

---

## Integration Examples

### FastAPI Endpoint

```python
from fastapi import FastAPI
from pydantic import BaseModel
from run_agent import AIAgent

app = FastAPI()

class ChatRequest(BaseModel):
    message: str
    model: str = "anthropic/claude-sonnet-4"

@app.post("/chat")
async def chat(request: ChatRequest):
    agent = AIAgent(
        model=request.model,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    response = agent.chat(request.message)
    return {"response": response}
```

### Discord Bot

```python
import discord
from run_agent import AIAgent

client = discord.Client(intents=discord.Intents.default())

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if message.content.startswith("!spark "):
        query = message.content[8:]
        agent = AIAgent(
            model="anthropic/claude-sonnet-4",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
            platform="discord",
        )
        response = agent.chat(query)
        await message.channel.send(response[:2000])

client.run("YOUR_DISCORD_TOKEN")
```

### CI/CD Pipeline Step

```python
#!/usr/bin/env python3
"""CI step: auto-review a PR diff."""
import subprocess
from run_agent import AIAgent

diff = subprocess.check_output(["git", "diff", "main...HEAD"]).decode()

agent = AIAgent(
    model="anthropic/claude-sonnet-4",
    quiet_mode=True,
    skip_context_files=True,
    skip_memory=True,
    disabled_toolsets=["terminal", "browser"],
)

review = agent.chat(
    f"Review this PR diff for bugs, security issues, and style problems:\n\n{diff}"
)
print(review)
```

---

## Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | `"anthropic/claude-opus-4.6"` | Model in OpenRouter format |
| `quiet_mode` | `bool` | `False` | Suppress CLI output |
| `enabled_toolsets` | `List[str]` | `None` | Allowlist specific toolsets |
| `disabled_toolsets` | `List[str]` | `None` | Blocklist specific toolsets |
| `save_trajectories` | `bool` | `False` | Save conversations to JSONL |
| `ephemeral_system_prompt` | `str` | `None` | Custom system prompt (not saved to trajectories) |
| `max_iterations` | `int` | `90` | Max tool-calling iterations per conversation |
| `skip_context_files` | `bool` | `False` | Skip loading AGENTS.md files |
| `skip_memory` | `bool` | `False` | Disable persistent memory read/write |
| `api_key` | `str` | `None` | API key (falls back to env vars) |
| `base_url` | `str` | `None` | Custom API endpoint URL |
| `platform` | `str` | `None` | Platform hint (`"discord"`, `"telegram"`, etc.) |

---

## Key Notes

**`skip_context_files=True`** — prevents `AGENTS.md` files from the working directory from loading into the system prompt. Recommended for API endpoints.

**`skip_memory=True`** — prevents the agent from reading or writing persistent memory. Recommended for stateless applications.

**`platform`** — injecting a platform hint (e.g., `"discord"`, `"telegram"`) tells the agent to adapt its output formatting for that platform.

**Thread safety** — create one `AIAgent` per thread or task. Never share an instance across concurrent calls.

**Resource cleanup** — the agent automatically cleans up terminal sessions and browser instances when a conversation ends. In long-lived processes, make sure each conversation completes normally.

**Iteration limits** — the default `max_iterations=90` is generous. For simple Q&A, lower it (e.g., `max_iterations=10`) to prevent runaway tool-calling loops and control costs.
