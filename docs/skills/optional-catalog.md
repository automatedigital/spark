---
sidebar_position: 9
title: "Optional Skills Catalog"
description: "Official optional skills shipped with spark-agent - install via spark skills install official/<category>/<skill>"
---

# Optional Skills Catalog

These skills ship with the spark-agent repository under `optional-skills/` but stay **inactive by default**. They cover heavier or niche use cases that most users don't need out of the box.

Install any of them with:

```bash
spark skills install official/<category>/<skill>
```

For example:

```bash
spark skills install official/blockchain/solana
spark skills install official/mlops/flash-attention
```

Once installed, the skill appears in the agent's skill list and loads automatically when relevant tasks come up.

To remove one:

```bash
spark skills uninstall <skill-name>
```

---

## Autonomous AI Agents

| Skill | What you can do |
|-------|----------------|
| **blackbox** | Delegate coding tasks to Blackbox AI CLI — a multi-model agent with a built-in judge that runs tasks through multiple LLMs and picks the best result. |
| **honcho** | Configure Honcho memory with Spark for cross-session user modeling, multi-profile peer isolation, observation config, and dialectic reasoning. |

## Blockchain

| Skill | What you can do |
|-------|----------------|
| **base** | Query Base (Ethereum L2) with USD pricing — wallet balances, token info, transaction details, gas analysis, contract inspection, whale detection, and live network stats. No API key required. |
| **solana** | Query Solana with USD pricing — wallet balances, token portfolios, transaction details, NFTs, whale detection, and live network stats. No API key required. |

## Communication

| Skill | What you can do |
|-------|----------------|
| **one-three-one-rule** | Apply a structured communication framework for proposals and decision-making. |

## Creative

| Skill | What you can do |
|-------|----------------|
| **blender-mcp** | Control Blender directly from Spark via socket connection to the blender-mcp addon — create 3D objects, materials, animations, and run arbitrary Blender Python (`bpy`) code. |

## DevOps

| Skill | What you can do |
|-------|----------------|
| **cli** | Run 150+ AI apps via inference.sh CLI (`infsh`) — image generation, video creation, LLMs, search, 3D, and social automation. |
| **docker-management** | Manage Docker containers, images, volumes, networks, and Compose stacks — lifecycle ops, debugging, cleanup, and Dockerfile optimization. |

## Email

| Skill | What you can do |
|-------|----------------|
| **agentmail** | Give the agent its own dedicated inbox via AgentMail — send, receive, and manage email autonomously with agent-owned addresses. |

## Health

| Skill | What you can do |
|-------|----------------|
| **fitness-nutrition** | Plan gym workouts and track nutrition — wger exercise search, USDA FoodData Central lookups, BMI/TDEE/macros/body-fat helpers (pure Python). |

## MCP

| Skill | What you can do |
|-------|----------------|
| **fastmcp** | Build, test, inspect, install, and deploy MCP servers with FastMCP in Python — wrap APIs or databases as MCP tools, expose resources or prompts, and deploy over HTTP. |

## Migration

| Skill | What you can do |
|-------|----------------|
| **openclaw-migration** | Migrate an OpenClaw configuration into Spark Agent — imports memories, SOUL.md, command allowlists, user skills, and selected workspace assets from `~/.openclaw`. |

## MLOps

The largest optional category. It covers the full ML pipeline from data curation to production inference.

| Skill | What you can do |
|-------|----------------|
| **accelerate** | Add distributed training to any PyTorch script in 4 lines — unified API for DeepSpeed, FSDP, Megatron, and DDP. |
| **chroma** | Store embeddings and metadata, run vector and full-text search with a simple 4-function API. Scales from notebooks to production clusters. |
| **faiss** | Search billions of dense vectors with GPU acceleration and multiple index types (Flat, IVF, HNSW) using Facebook's FAISS. |
| **flash-attention** | Speed up transformer attention 2–4x and cut memory 10–20x. Supports PyTorch SDPA, the flash-attn library, H100 FP8, and sliding window attention. |
| **spark-atropos-environments** | Build, test, and debug Spark Agent RL environments for Atropos training — SparkAgentBaseEnv interface, reward functions, agent loop integration, and evaluation. |
| **huggingface-tokenizers** | Tokenize 1 GB in under 20 seconds with Rust-based BPE, WordPiece, and Unigram tokenizers — supports custom vocabulary training and alignment tracking. |
| **instructor** | Extract structured data from LLM responses with Pydantic validation, automatic retry on failures, and streaming partial results. |
| **lambda-labs** | Provision reserved or on-demand GPU instances with SSH access, persistent filesystems, and multi-node cluster support. |
| **llava** | Run multi-turn image chats and visual question answering by combining a CLIP vision encoder with a LLaMA language model. |
| **nemo-curator** | Curate LLM training data on GPU — fuzzy dedup (16x faster than CPU), 30+ quality heuristics, semantic dedup, PII redaction, and NSFW detection. Scales with RAPIDS. |
| **pinecone** | Run production semantic search and RAG with a fully managed, auto-scaling vector database — hybrid dense+sparse search, metadata filtering, under 100ms p95. |
| **pytorch-lightning** | Write clean PyTorch training loops with the Trainer class — automatic DDP/FSDP/DeepSpeed, callbacks, and minimal boilerplate. Scales from laptop to supercomputer. |
| **qdrant** | Fast nearest-neighbor search and hybrid RAG with Qdrant's Rust-powered vector engine. |
| **saelens** | Train and analyze Sparse Autoencoders (SAEs) with SAELens to find interpretable features in language model activations. |
| **simpo** | Align models without a reference model using Simple Preference Optimization — +6.4 pts on AlpacaEval 2.0 over DPO, and faster to train. |
| **slime** | LLM post-training with RL using Megatron+SGLang (slime) — custom data generation workflows and tight Megatron-LM integration for RL scaling. |
| **tensorrt-llm** | Push NVIDIA GPU inference to its limit — 10–100x faster than PyTorch on A100/H100 with FP8/INT4 quantization and in-flight batching. |
| **torchtitan** | Pretrain large models with 4D parallelism (FSDP2, TP, PP, CP) across 8 to 512+ GPUs using PyTorch-native torchtitan with Float8 and torch.compile. |

## Productivity

| Skill | What you can do |
|-------|----------------|
| **canvas** | Fetch enrolled courses and assignments from Canvas LMS using API token authentication. |
| **memento-flashcards** | Build and review spaced repetition flashcard decks for learning and knowledge retention. |
| **siyuan** | Search, read, create, and manage blocks and documents in a self-hosted SiYuan knowledge base via its API. |
| **telephony** | Give Spark phone capabilities — provision a Twilio number, send/receive SMS/MMS, make calls, and place AI-driven outbound calls through Bland.ai or Vapi. |

## Research

| Skill | What you can do |
|-------|----------------|
| **bioinformatics** | Access 400+ bioinformatics skills from bioSkills and ClawBio — genomics, transcriptomics, single-cell, variant calling, pharmacogenomics, metagenomics, and structural biology. |
| **domain-intel** | Passive domain recon using Python stdlib — subdomain discovery, SSL inspection, WHOIS, DNS records, and bulk multi-domain analysis. No API keys. |
| **duckduckgo-search** | Free web search via DuckDuckGo — text, news, images, and videos. No API key needed. |
| **gitnexus-explorer** | Index a codebase with GitNexus and serve an interactive knowledge graph via web UI and Cloudflare tunnel. |
| **parallel-cli** | Agent-native web search, extraction, deep research, enrichment, and monitoring via the Parallel CLI. |
| **qmd** | Search personal knowledge bases, notes, docs, and meeting transcripts locally with qmd — hybrid BM25, vector search, and LLM reranking. Supports CLI and MCP. |
| **scrapling** | Scrape the web with Scrapling — HTTP fetching, stealth browser automation, Cloudflare bypass, and spider crawling via CLI and Python. |

## Security

| Skill | What you can do |
|-------|----------------|
| **1password** | Set up the 1Password CLI (`op`), enable desktop app integration, sign in, and inject secrets into commands. |
| **oss-forensics** | Investigate open-source packages for supply chain risks — analyze dependencies, recover deleted commits, detect force-pushes, and extract IOCs. |
| **sherlock** | OSINT username search across 400+ social networks — hunt down accounts by username. |
