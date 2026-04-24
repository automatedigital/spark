---
sidebar_position: 9
title: "Voice & TTS"
description: "Text-to-speech and voice message transcription across all platforms"
---

# Voice & TTS

Spark can speak its replies aloud and transcribe voice messages you send through Telegram, Discord, WhatsApp, Slack, or Signal. Here's everything you need to get it working.

## Text-to-Speech (TTS)

Six providers to choose from:

| Provider | Quality | Cost | API Key |
|----------|---------|------|---------|
| **Edge TTS** (default) | Good | Free | None |
| **ElevenLabs** | Excellent | Paid | `ELEVENLABS_API_KEY` |
| **OpenAI TTS** | Good | Paid | `VOICE_TOOLS_OPENAI_KEY` |
| **MiniMax TTS** | Excellent | Paid | `MINIMAX_API_KEY` |
| **Mistral (Voxtral TTS)** | Excellent | Paid | `MISTRAL_API_KEY` |
| **NeuTTS** | Good | Free | None |

### Where Audio Gets Delivered

| Platform | Format | Notes |
|----------|--------|-------|
| Telegram | Voice bubble (Opus `.ogg`) | Plays inline |
| Discord | Voice bubble (Opus/OGG) | Falls back to file attachment |
| WhatsApp | Audio file (MP3) | |
| CLI | Saved to `~/.spark/audio_cache/` | MP3 |

### Config

```yaml
# ~/.spark/config.yaml
tts:
  provider: "edge"              # "edge" | "elevenlabs" | "openai" | "minimax" | "mistral" | "neutts"
  speed: 1.0                    # Global speed — provider-specific settings override this
  edge:
    voice: "en-US-AriaNeural"   # 322 voices, 74 languages
    speed: 1.0
  elevenlabs:
    voice_id: "pNInz6obpgDQGcFmaJgB"   # Adam
    model_id: "eleven_multilingual_v2"
  openai:
    model: "gpt-4o-mini-tts"
    voice: "alloy"              # alloy, echo, fable, onyx, nova, shimmer
    base_url: "https://api.openai.com/v1"
    speed: 1.0                  # 0.25 - 4.0
  minimax:
    model: "speech-2.8-hd"     # or speech-2.8-turbo
    voice_id: "English_Graceful_Lady"
    speed: 1                    # 0.5 - 2.0
    vol: 1                      # 0 - 10
    pitch: 0                    # -12 - 12
  mistral:
    model: "voxtral-mini-tts-2603"
    voice_id: "c69964a6-ab8b-4f8a-9465-ec0925096ec8"   # Paul - Neutral
  neutts:
    ref_audio: ''
    ref_text: ''
    model: neuphonic/neutts-air-q4-gguf
    device: cpu
```

**Speed hierarchy:** provider-specific `speed` → global `tts.speed` → `1.0` default.

### Telegram Voice Bubbles & ffmpeg

Telegram voice bubbles need Opus/OGG audio. Some providers produce it natively; others need ffmpeg to convert:

| Provider | Needs ffmpeg? |
|----------|:---:|
| OpenAI TTS | No — Opus native |
| ElevenLabs | No — Opus native |
| Mistral | No — Opus native |
| Edge TTS | Yes — outputs MP3 |
| MiniMax TTS | Yes — outputs MP3 |
| NeuTTS | Yes — outputs WAV |

```bash
sudo apt install ffmpeg   # Ubuntu/Debian
brew install ffmpeg       # macOS
sudo dnf install ffmpeg   # Fedora
```

Without ffmpeg, Edge/MiniMax/NeuTTS audio still works — it just appears as a rectangular audio player rather than a voice bubble.

> **Tip:** Want voice bubbles without installing ffmpeg? Switch to OpenAI, ElevenLabs, or Mistral TTS.

---

## Voice Message Transcription (STT)

Send a voice message on Telegram, Discord, WhatsApp, Slack, or Signal and Spark automatically transcribes it. The transcript enters the conversation as normal text.

| Provider | Quality | Cost | API Key |
|----------|---------|------|---------|
| **Local Whisper** (default) | Good | Free | None |
| **Groq Whisper API** | Good–Best | Free tier | `GROQ_API_KEY` |
| **OpenAI Whisper API** | Good–Best | Paid | `VOICE_TOOLS_OPENAI_KEY` or `OPENAI_API_KEY` |
| **Mistral Voxtral** | Excellent | Paid | `MISTRAL_API_KEY` |

Local transcription works out of the box with `faster-whisper`. If it's not installed, Spark also checks for a local `whisper` CLI or a custom command via `SPARK_LOCAL_STT_COMMAND`.

### Config

```yaml
# ~/.spark/config.yaml
stt:
  provider: "local"           # "local" | "groq" | "openai" | "mistral"
  local:
    model: "base"             # tiny, base, small, medium, large-v3
  openai:
    model: "whisper-1"        # whisper-1 | gpt-4o-mini-transcribe | gpt-4o-transcribe
  mistral:
    model: "voxtral-mini-latest"
```

### Local model sizes

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | ~75 MB | Fastest | Basic |
| `base` | ~150 MB | Fast | Good (default) |
| `small` | ~500 MB | Medium | Better |
| `medium` | ~1.5 GB | Slower | Great |
| `large-v3` | ~3 GB | Slowest | Best |

### Provider notes

**Groq** — Requires `GROQ_API_KEY`. Fast cloud option with a generous free tier.

**OpenAI** — Uses `VOICE_TOOLS_OPENAI_KEY` first, falls back to `OPENAI_API_KEY`. Supports `whisper-1`, `gpt-4o-mini-transcribe`, and `gpt-4o-transcribe`.

**Mistral (Voxtral Transcribe)** — Requires `MISTRAL_API_KEY` and `pip install spark-agent[mistral]`. Supports 13 languages, speaker diarization, and word-level timestamps.

**Custom CLI** — Set `SPARK_LOCAL_STT_COMMAND` with a template that uses `{input_path}`, `{output_dir}`, `{language}`, and `{model}` placeholders.

### Automatic Fallback

If your chosen provider isn't available, Spark falls through automatically:

- Local faster-whisper unavailable → tries local `whisper` CLI or `SPARK_LOCAL_STT_COMMAND`, then cloud
- Groq key not set → local, then OpenAI
- OpenAI key not set → local, then Groq
- Mistral key/SDK missing → skipped in auto-detect
- Nothing available → voice message passes through with a note to the user
