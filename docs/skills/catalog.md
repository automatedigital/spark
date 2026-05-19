---
sidebar_position: 5
title: "Bundled Skills Catalog"
description: "Catalog of bundled skills that ship with Spark Agent"
---

# Bundled Skills Catalog

Every skill listed here ships with Spark and lands in `~/.spark/skills/` on install. Invoke any of them as a slash command (e.g. `/github-pr-workflow`) or just ask the agent — it picks up relevant skills automatically.

---

## apple

macOS-only. Controls iMessage, Reminders, Notes, and FindMy via native macOS tools. These skills are hidden on Linux and Windows.

| Skill | What you can do | Path |
|-------|----------------|------|
| `apple-notes` | Create, view, search, and edit Apple Notes via the memo CLI. | `apple/apple-notes` |
| `apple-reminders` | List, add, complete, and delete Apple Reminders via remindctl. | `apple/apple-reminders` |
| `findmy` | Track Apple devices and AirTags via FindMy.app using AppleScript and screen capture. | `apple/findmy` |
| `imessage` | Send and receive iMessages and SMS via the imsg CLI. | `apple/imessage` |

---

## autonomous-ai-agents

Spawn sub-agents and delegate coding work to specialized AI CLIs. Useful for long-running tasks, parallel workstreams, and multi-model comparisons.

| Skill | What you can do | Path |
|-------|----------------|------|
| `claude-code` | Delegate features, refactors, and PR reviews to Claude Code. Requires the `claude` CLI. | `autonomous-ai-agents/claude-code` |
| `codex` | Delegate coding tasks to the OpenAI Codex CLI. Requires the `codex` CLI and a git repo. | `autonomous-ai-agents/codex` |
| `spark-agent-spawning` | Spawn a full separate Spark instance as an autonomous subprocess — one-shot (`-q`) or interactive PTY mode. | `autonomous-ai-agents/spark-agent` |
| `opencode` | Delegate to OpenCode CLI for autonomous coding sessions. Requires the `opencode` CLI installed and authenticated. | `autonomous-ai-agents/opencode` |

---

## data-science

Run stateful, iterative Python in a live Jupyter kernel.

| Skill | What you can do | Path |
|-------|----------------|------|
| `jupyter-live-kernel` | Execute Python interactively via hamelnb — great for exploration and inspecting intermediate results. | `data-science/jupyter-live-kernel` |

---

## creative

Generate ASCII art, diagrams, frontend interfaces, design systems, and generative visual content.

| Skill | What you can do | Path |
|-------|----------------|------|
| `ascii-art` | Create ASCII art with pyfiglet (571 fonts), cowsay, boxes, toilet, image-to-ascii, remote APIs, and LLM fallback. No API keys needed. | `creative/ascii-art` |
| `ascii-video` | Convert video, audio, images, or generative input into colored ASCII video output (MP4, GIF, image sequence). | `creative/ascii-video` |
| `design-md` | Create, apply, audit, and validate Google `DESIGN.md` design-system files, including tokens, rationale sections, linting, diffs, and exports. | `creative/design-md` |
| `excalidraw` | Generate `.excalidraw` files for architecture diagrams, flowcharts, sequence diagrams, and concept maps — open at excalidraw.com or share via link. | `creative/excalidraw` |
| `frontend-design` | Create distinctive, production-grade frontend interfaces with high-quality typography, color, layout, motion, and visual polish. | `creative/frontend-design` |
| `p5js` | Build interactive and generative art with p5.js, render to images or video via headless browser, and serve live previews. | `creative/p5js` |

---

## design

Front-end design and review workflows — visual hierarchy, typography, color/contrast, motion, anti-pattern detection.

| Skill | What you can do | Path |
|-------|----------------|------|
| `impeccable` | Design, audit, polish, animate, and refine frontend UIs with 23 sub-commands (`craft`, `audit`, `polish`, `animate`, `clarify`, `distill`, `harden`, …) backed by seven reference docs (typography, color, spatial, motion, interaction, responsive, ux-writing) plus deterministic anti-pattern detection. Built on Anthropic's `frontend-design` skill. Upstream: [pbakaus/impeccable](https://github.com/pbakaus/impeccable). | `design/impeccable` |

---

## devops

Automate infrastructure and event-driven workflows.

| Skill | What you can do | Path |
|-------|----------------|------|
| `webhook-subscriptions` | Create and manage webhook subscriptions so external services (GitHub, Stripe, CI/CD, IoT) can trigger agent runs. Requires the webhook platform to be enabled. | `devops/webhook-subscriptions` |

---

## email

Manage email from the terminal via IMAP/SMTP.

| Skill | What you can do | Path |
|-------|----------------|------|
| `himalaya` | List, read, compose, reply, forward, search, and organize emails across multiple accounts using the himalaya CLI. Supports MML (MIME Meta Language) for composition. | `email/himalaya` |

---

## github

Full GitHub workflow management via the `gh` CLI and git.

| Skill | What you can do | Path |
|-------|----------------|------|
| `codebase-inspection` | Count lines of code, break down languages, and measure code-vs-comment ratios with pygount. | `github/codebase-inspection` |
| `github-auth` | Set up HTTPS tokens, SSH keys, credential helpers, or `gh auth` — with auto-detection to pick the right method. | `github/github-auth` |
| `github-code-review` | Analyze git diffs, leave inline PR comments, and run pre-push code review. Falls back to git + GitHub REST API via curl. | `github/github-code-review` |
| `github-issues` | Create, triage, label, assign, and close GitHub issues. Falls back to git + GitHub REST API via curl. | `github/github-issues` |
| `github-pr-workflow` | Full PR lifecycle: branch, commit, open PR, watch CI, auto-fix failures, and merge. Falls back to git + GitHub REST API via curl. | `github/github-pr-workflow` |
| `github-repo-management` | Clone, fork, configure, and manage repos — including remotes, secrets, releases, and workflows. Falls back to git + GitHub REST API via curl. | `github/github-repo-management` |

---

## inference-sh

Run AI apps from the cloud in one command.

| Skill | What you can do | Path |
|-------|----------------|------|
| `inference-sh-cli` | Access 150+ AI apps via the `infsh` CLI — image generation, video creation, LLMs, search, 3D, and social automation. | `inference-sh/cli` |

---

## leisure

Find places near you without any API keys.

| Skill | What you can do | Path |
|-------|----------------|------|
| `find-nearby` | Discover restaurants, cafes, bars, pharmacies, and more via OpenStreetMap. Accepts coordinates, addresses, city names, zip codes, or Telegram location pins. | `leisure/find-nearby` |

---

## mcp

Connect to and interact with MCP (Model Context Protocol) servers.

| Skill | What you can do | Path |
|-------|----------------|------|
| `mcporter` | Use the mcporter CLI to list, configure, auth, and call MCP servers and tools directly via HTTP or stdio. | `mcp/mcporter` |
| `native-mcp` | Built-in MCP client that connects to external MCP servers, discovers their tools, and registers them as native Spark tools. Supports stdio and HTTP with automatic reconnection and zero-config tool injection. | `mcp/native-mcp` |

---

## media

Work with YouTube content and GIFs.

| Skill | What you can do | Path |
|-------|----------------|------|
| `gif-search` | Search and download GIFs from Tenor using curl and jq. No extra dependencies. | `media/gif-search` |
| `youtube-content` | Fetch YouTube transcripts and turn them into chapters, summaries, threads, or blog posts. | `media/youtube-content` |

---

## mlops

General ML operations: model hub management, datasets, and workflow orchestration.

| Skill | What you can do | Path |
|-------|----------------|------|
| `huggingface-hub` | Search, download, and upload models and datasets; manage repos; deploy inference endpoints via the `hf` CLI. | `mlops/huggingface-hub` |

---

## mlops/cloud

GPU cloud and serverless compute for ML workloads.

| Skill | What you can do | Path |
|-------|----------------|------|
| `lambda-labs-gpu-cloud` | Provision reserved or on-demand GPU instances with SSH access, persistent filesystems, and multi-node cluster support. | `mlops/cloud/lambda-labs` |
| `modal-serverless-gpu` | Run ML workloads on-demand without managing infrastructure — deploy models as APIs or run batch jobs with auto-scaling. | `mlops/cloud/modal` |

---

## mlops/evaluation

Benchmarks, experiment tracking, data curation, tokenizers, and interpretability.

| Skill | What you can do | Path |
|-------|----------------|------|
| `evaluating-llms-harness` | Benchmark LLMs across 60+ academic tasks (MMLU, HumanEval, GSM8K, TruthfulQA, HellaSwag). Industry standard used by EleutherAI and HuggingFace. | `mlops/evaluation/lm-evaluation-harness` |
| `huggingface-tokenizers` | Train custom vocabularies, track alignments, and handle padding/truncation with Rust-based tokenizers. Tokenizes 1 GB in under 20 seconds. | `mlops/evaluation/huggingface-tokenizers` |
| `nemo-curator` | Curate LLM training data with GPU acceleration — fuzzy dedup (16x faster), 30+ quality heuristics, PII redaction, and NSFW detection. | `mlops/evaluation/nemo-curator` |
| `sparse-autoencoder-training` | Train and analyze Sparse Autoencoders (SAEs) with SAELens to find interpretable features in language model activations. | `mlops/evaluation/saelens` |
| `weights-and-biases` | Log experiments automatically, visualize training in real-time, run hyperparameter sweeps, and manage model registry with W&B. | `mlops/evaluation/weights-and-biases` |

---

## mlops/inference

Serve, quantize, and optimize LLMs for production.

| Skill | What you can do | Path |
|-------|----------------|------|
| `gguf-quantization` | Quantize models to GGUF format (2–8 bit) for efficient CPU and Apple Silicon inference with llama.cpp. | `mlops/inference/gguf` |
| `guidance` | Guarantee valid JSON, XML, or code output by constraining generation with regex and grammars via Microsoft Research's Guidance framework. | `mlops/inference/guidance` |
| `instructor` | Extract structured data from LLM responses with Pydantic validation, automatic retry on failures, and streaming partial results. | `mlops/inference/instructor` |
| `llama-cpp` | Run LLM inference on CPU, Apple Silicon, and consumer GPUs without CUDA. Supports GGUF quantization and delivers 4–10x speedup over PyTorch on CPU. | `mlops/inference/llama-cpp` |
| `outlines` | Guarantee valid JSON/XML/code structure during generation, use Pydantic models for type-safe outputs, and maximize inference speed with local models. | `mlops/inference/outlines` |
| `serving-llms-vllm` | Serve LLMs with high throughput via PagedAttention and continuous batching. Supports OpenAI-compatible endpoints, GPTQ/AWQ/FP8 quantization, and limited GPU memory. | `mlops/inference/vllm` |
| `tensorrt-llm` | Maximize NVIDIA GPU throughput with TensorRT-LLM — 10–100x faster inference than PyTorch on A100/H100, with FP8/INT4 quantization and in-flight batching. | `mlops/inference/tensorrt-llm` |

---

## mlops/models

Specific architectures for vision, speech, audio generation, and multimodal tasks.

| Skill | What you can do | Path |
|-------|----------------|------|
| `audiocraft-audio-generation` | Generate music from text (MusicGen) and sound effects (AudioGen), or condition on a melody. | `mlops/models/audiocraft` |
| `clip` | Zero-shot classify images, match image-text pairs, and build cross-modal retrieval — no fine-tuning required. | `mlops/models/clip` |
| `llava` | Run multi-turn image chats, visual question answering, and instruction following by combining a CLIP encoder with a LLaMA-based language model. | `mlops/models/llava` |
| `segment-anything-model` | Segment any object in images using points, boxes, or masks as prompts — or automatically generate all object masks. | `mlops/models/segment-anything` |
| `stable-diffusion-image-generation` | Generate images from text, run img-to-img, inpaint, or build custom diffusion pipelines via HuggingFace Diffusers. | `mlops/models/stable-diffusion` |
| `whisper` | Transcribe or translate audio in 99 languages. Six model sizes from tiny (39M params) to large (1550M params). | `mlops/models/whisper` |

---

## mlops/research

Build and optimize AI systems with declarative programming frameworks.

| Skill | What you can do | Path |
|-------|----------------|------|
| `dspy` | Declare complex AI pipelines as modules, optimize prompts automatically, and build modular RAG systems with DSPy (Stanford NLP). | `mlops/research/dspy` |

---

## mlops/training

Fine-tuning, RLHF/DPO/GRPO, distributed training, and optimization.

| Skill | What you can do | Path |
|-------|----------------|------|
| `axolotl` | Fine-tune 100+ LLMs with YAML configs — LoRA/QLoRA, DPO/KTO/ORPO/GRPO, multimodal support. | `mlops/training/axolotl` |
| `distributed-llm-pretraining-torchtitan` | Pretrain Llama 3.1, DeepSeek V3, or custom models with 4D parallelism (FSDP2, TP, PP, CP) from 8 to 512+ GPUs using torchtitan. | `mlops/training/torchtitan` |
| `fine-tuning-with-trl` | Fine-tune with SFT, DPO, PPO, or GRPO using TRL — covers instruction tuning, preference alignment, and reward model training. | `mlops/training/trl-fine-tuning` |
| `grpo-model-training` | Expert guidance for GRPO/RL fine-tuning with TRL for reasoning and task-specific model training. | `mlops/training/grpo-model-training` |
| `spark-atropos-environments` | Build, test, and debug Spark Agent RL environments for Atropos training — covers the SparkAgentBaseEnv interface, reward functions, wandb logging, and all three CLI modes. | `mlops/training/spark-atropos-environments` |
| `huggingface-accelerate` | Add distributed training to any PyTorch script in 4 lines — unified API for DeepSpeed, FSDP, Megatron, and DDP. | `mlops/training/accelerate` |
| `optimizing-attention-flash` | Cut attention memory 10–20x and speed it up 2–4x with Flash Attention. Useful for sequences longer than 512 tokens. | `mlops/training/flash-attention` |
| `peft-fine-tuning` | Fine-tune 7B–70B models training under 1% of parameters with LoRA, QLoRA, and 25+ PEFT methods. | `mlops/training/peft` |
| `pytorch-fsdp` | Shard model parameters across GPUs for large-scale training with PyTorch FSDP — mixed precision, CPU offloading, and FSDP2. | `mlops/training/pytorch-fsdp` |
| `pytorch-lightning` | Write clean PyTorch training loops with the Trainer class — automatic DDP/FSDP/DeepSpeed, callbacks, and zero boilerplate. Scales from laptop to supercomputer. | `mlops/training/pytorch-lightning` |
| `simpo-training` | Align models with Simple Preference Optimization — reference-free, no reference model needed, and +6.4 pts on AlpacaEval 2.0 over DPO. | `mlops/training/simpo` |
| `slime-model-training` | LLM post-training with RL using a Megatron+SGLang framework (slime). Covers custom data generation and GLM model workflows. | `mlops/training/slime` |
| `unsloth` | Fine-tune 2–5x faster with 50–80% less memory using Unsloth — optimized LoRA/QLoRA. | `mlops/training/unsloth` |

---

## mlops/vector-databases

Vector similarity search and embedding databases for RAG and semantic search.

| Skill | What you can do | Path |
|-------|----------------|------|
| `chroma` | Store embeddings and metadata, run vector and full-text search, and filter by metadata — simple 4-function API that scales from notebooks to clusters. | `mlops/vector-databases/chroma` |
| `faiss` | Search billions of dense vectors with GPU acceleration and multiple index types (Flat, IVF, HNSW) using Facebook's FAISS library. | `mlops/vector-databases/faiss` |
| `pinecone` | Run production semantic search and RAG with a fully managed, auto-scaling vector database — hybrid dense+sparse search, metadata filtering, under 100ms p95. | `mlops/vector-databases/pinecone` |
| `qdrant-vector-search` | Build fast nearest-neighbor search and hybrid RAG with Qdrant's Rust-powered vector engine. | `mlops/vector-databases/qdrant` |

---

## note-taking

Read and write notes in your Obsidian vault.

| Skill | What you can do | Path |
|-------|----------------|------|
| `obsidian` | Search, read, and create notes in the Obsidian vault. | `note-taking/obsidian` |

---

## productivity

Documents, spreadsheets, presentations, PDFs, and workspace integrations.

| Skill | What you can do | Path |
|-------|----------------|------|
| `google-workspace` | Access Gmail, Calendar, Drive, Contacts, Sheets, and Docs via OAuth2 — runs entirely in the Spark venv, no external binaries. | `productivity/google-workspace` |
| `linear` | Create, update, search, and organize Linear issues, projects, and teams via the GraphQL API. | `productivity/linear` |
| `nano-pdf` | Edit PDFs with natural-language instructions via the nano-pdf CLI — fix typos, update titles, change content on specific pages. | `productivity/nano-pdf` |
| `notion` | Search, create, update, and query Notion workspaces via the Notion API and curl. | `productivity/notion` |
| `ocr-and-documents` | Extract text from PDFs, scanned documents, and DOCX files using web_extract, pymupdf, or marker-pdf. | `productivity/ocr-and-documents` |
| `powerpoint` | Create slide decks and pitch decks, or read and extract content from `.pptx` files. | `productivity/powerpoint` |

---

## research

Academic research, paper discovery, domain recon, market data, and content monitoring.

| Skill | What you can do | Path |
|-------|----------------|------|
| `arxiv` | Search arXiv by keyword, author, category, or paper ID — no API key needed. Combine with web_extract or the ocr-and-documents skill to read full papers. | `research/arxiv` |
| `blogwatcher` | Monitor blogs and RSS/Atom feeds with blogwatcher CLI — add blogs, scan for new articles, and track what you've read. | `research/blogwatcher` |
| `llm-wiki` | Build and maintain an interlinked markdown knowledge base with Karpathy's LLM Wiki — ingest sources, query compiled knowledge, and lint for consistency. Works as an Obsidian vault. Configurable via `skills.config.wiki.path`. | `research/llm-wiki` |
| `domain-intel` | Run passive domain recon using Python stdlib — subdomain discovery, SSL inspection, WHOIS, DNS records, and bulk multi-domain analysis. No API keys. | `research/domain-intel` |
| `duckduckgo-search` | Search the web for free via DuckDuckGo — text, news, images, videos. No API key needed. Prefers the `ddgs` CLI when installed. | `research/duckduckgo-search` |
| `ml-paper-writing` | Draft publication-ready ML/AI papers for NeurIPS, ICML, ICLR, ACL, AAAI, or COLM with LaTeX templates, reviewer guidelines, and citation verification. | `research/ml-paper-writing` |
| `polymarket` | Query Polymarket prediction markets — search markets, get prices, orderbooks, and price history via public REST APIs. No API key needed. | `research/polymarket` |

---

## smart-home

Control Philips Hue lights from the terminal.

| Skill | What you can do | Path |
|-------|----------------|------|
| `openhue` | Turn Hue lights on/off, adjust brightness, color, color temperature, and activate scenes via the OpenHue CLI. | `smart-home/openhue` |

---

## social-media

Interact with social platforms from the terminal.

| Skill | What you can do | Path |
|-------|----------------|------|
| `twitter-x-cli` | Post, read, and manage X/Twitter via the x-cli terminal client using official X API credentials. | `social-media/twitter-x-cli` |

---

## software-development

Code review, debugging, planning, and development workflows.

| Skill | What you can do | Path |
|-------|----------------|------|
| `code-review` | Apply security and quality-focused guidelines to perform thorough code reviews. | `software-development/code-review` |
| `exploratory-web-qa` | Run systematic exploratory QA on web apps — find bugs, capture evidence, and generate structured reports using the browser toolset. | `software-development/exploratory-web-qa` |
| `plan` | Inspect context, write a markdown implementation plan into `.spark/plans/`, and stop — do not execute the work yet. | `software-development/plan` |
| `requesting-code-review` | Validate completed work against requirements with a systematic review process. Use before merging. | `software-development/requesting-code-review` |
| `subagent-driven-development` | Execute implementation plans by dispatching a fresh `delegate_task` per task with two-stage review (spec compliance then code quality). | `software-development/subagent-driven-development` |
| `systematic-debugging` | Investigate any bug, test failure, or unexpected behavior with a 4-phase root cause analysis — no fixes before understanding the problem. | `software-development/systematic-debugging` |
| `test-driven-development` | Enforce RED-GREEN-REFACTOR before writing implementation code. | `software-development/test-driven-development` |
| `writing-plans` | Turn a spec or requirements doc into a comprehensive implementation plan with bite-sized tasks, exact file paths, and complete code examples. | `software-development/writing-plans` |

---

# Optional Skills

Optional skills live in `optional-skills/` in the repository but are **not active by default**. They cover heavier or niche use cases. Install any of them with:

```bash
spark skills install official/<category>/<skill>
```

## autonomous-ai-agents

| Skill | Description | Path |
|-------|-------------|------|
| `blackbox` | Delegate coding tasks to Blackbox AI CLI agent. Multi-model agent with built-in judge that runs tasks through multiple LLMs and picks the best result. Requires the blackbox CLI and a Blackbox AI API key. | `autonomous-ai-agents/blackbox` |

## blockchain

| Skill | Description | Path |
|-------|-------------|------|
| `base` | Query Base (Ethereum L2) blockchain data with USD pricing - wallet balances, token info, transaction details, gas analysis, contract inspection, whale detection, and live network stats. Uses Base RPC + CoinGecko. No API key required. | `blockchain/base` |
| `solana` | Query Solana blockchain data with USD pricing - wallet balances, token portfolios with values, transaction details, NFTs, whale detection, and live network stats. Uses Solana RPC + CoinGecko. No API key required. | `blockchain/solana` |

## creative

| Skill | Description | Path |
|-------|-------------|------|
| `blender-mcp` | Control Blender directly from Spark via socket connection to the blender-mcp addon. Create 3D objects, materials, animations, and run arbitrary Blender Python (bpy) code. | `creative/blender-mcp` |

## devops

| Skill | Description | Path |
|-------|-------------|------|
| `docker-management` | Manage Docker containers, images, volumes, networks, and Compose stacks - lifecycle ops, debugging, cleanup, and Dockerfile optimization. | `devops/docker-management` |

## email

| Skill | Description | Path |
|-------|-------------|------|
| `agentmail` | Give the agent its own dedicated email inbox via AgentMail. Send, receive, and manage email autonomously using agent-owned email addresses (e.g. spark-agent@agentmail.to). | `email/agentmail` |

## health

| Skill | Description | Path |
|-------|-------------|------|
| `fitness-nutrition` | Gym workout planning and nutrition tracking — wger exercise search, USDA FoodData Central lookups, BMI/TDEE/macros/body-fat helpers (pure Python). | `health/fitness-nutrition` |

## mcp

| Skill | Description | Path |
|-------|-------------|------|
| `fastmcp` | Build, test, inspect, install, and deploy MCP servers with FastMCP in Python. Use when creating a new MCP server, wrapping an API or database as MCP tools, exposing resources or prompts, or preparing a FastMCP server for HTTP deployment. | `mcp/fastmcp` |

## migration

| Skill | Description | Path |
|-------|-------------|------|
| `openclaw-migration` | Migrate a user's OpenClaw customization footprint into Spark Agent. Imports Spark-compatible memories, SOUL.md, command allowlists, user skills, and selected workspace assets from ~/.openclaw, then reports what could not be migrated and why. | `migration/openclaw-migration` |

## productivity

| Skill | Description | Path |
|-------|-------------|------|
| `telephony` | Give Spark phone capabilities - provision and persist a Twilio number, send and receive SMS/MMS, make direct calls, and place AI-driven outbound calls through Bland.ai or Vapi. | `productivity/telephony` |

## research

| Skill | Description | Path |
|-------|-------------|------|
| `bioinformatics` | Gateway to 400+ bioinformatics skills from bioSkills and ClawBio. Covers genomics, transcriptomics, single-cell, variant calling, pharmacogenomics, metagenomics, structural biology, and more. | `research/bioinformatics` |
| `qmd` | Search personal knowledge bases, notes, docs, and meeting transcripts locally using qmd - a hybrid retrieval engine with BM25, vector search, and LLM reranking. Supports CLI and MCP integration. | `research/qmd` |

## security

| Skill | Description | Path |
|-------|-------------|------|
| `1password` | Set up and use 1Password CLI (op). Use when installing the CLI, enabling desktop app integration, signing in, and reading/injecting secrets for commands. | `security/1password` |
| `oss-forensics` | Supply chain investigation, evidence recovery, and forensic analysis for GitHub repositories. Covers deleted commit recovery, force-push detection, IOC extraction, multi-source evidence collection, and structured forensic reporting. | `security/oss-forensics` |
| `sherlock` | OSINT username search across 400+ social networks. Hunt down social media accounts by username. | `security/sherlock` |
