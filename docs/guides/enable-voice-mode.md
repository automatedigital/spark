---
sidebar_position: 8
title: "Use Voice Mode with Spark"
description: "A practical guide to setting up and using Spark voice mode across CLI, Telegram, Discord, and Discord voice channels"
---

# Talk to Spark: Voice Mode Setup

Tired of typing? Voice mode lets you speak to Spark and hear it talk back — in the terminal, via Telegram, or live in a Discord voice channel. This guide gets you running, in that order.

For a full feature overview, see the [Voice Mode reference](../voice/voice-mode.md).

---

## Pick your starting point

Three distinct voice experiences exist in Spark. They share some infrastructure but each builds on the last.

| Mode | What it does | Where |
|---|---|---|
| CLI microphone loop | Hands-free coding and research at your desk | Terminal |
| Voice replies in chat | Spoken responses when messaging the bot | Telegram, Discord |
| Live voice channel | Spark joins a VC and converses in real time | Discord voice channels |

Start at the top and work down. Do not jump to Discord VC mode without proving the simpler modes work first.

---

## Before anything: verify text mode works

Voice mode sits on top of normal Spark. If text is broken, voice will not help.

```bash
spark
```

Ask something simple:

```text
What tools do you have available?
```

Move on only when that works reliably.

---

## Install what you need

### CLI microphone + playback

```bash
pip install "spark-agent[voice]"
```

### Messaging platform support

```bash
pip install "spark-agent[messaging]"
```

### Premium ElevenLabs TTS

```bash
pip install "spark-agent[tts-premium]"
```

### Local NeuTTS (optional, free, on-device)

```bash
python -m pip install -U neutts[all]
```

### Everything at once

```bash
pip install "spark-agent[all]"
```

---

## Install system packages

### macOS

```bash
brew install portaudio ffmpeg opus
brew install espeak-ng
```

### Ubuntu / Debian

```bash
sudo apt install portaudio19-dev ffmpeg libopus0
sudo apt install espeak-ng
```

| Package | Why you need it |
|---|---|
| `portaudio` | Microphone input and audio playback in CLI mode |
| `ffmpeg` | Audio conversion for TTS delivery |
| `opus` | Discord voice channel codec |
| `espeak-ng` | Phonemizer backend for NeuTTS |

---

## Choose your STT and TTS providers

The cheapest and easiest starting point: local STT with Edge TTS. Zero API keys, good enough quality.

### Add keys to `~/.spark/.env` as needed

```bash
# Cloud STT (local needs no key)
GROQ_API_KEY=***
VOICE_TOOLS_OPENAI_KEY=***

# Premium TTS (optional)
ELEVENLABS_API_KEY=***
```

### STT options

| Provider | Tradeoffs |
|---|---|
| `local` | Best default — free, private, runs on your machine |
| `groq` | Very fast cloud transcription |
| `openai` | Paid, reliable fallback |

### TTS options

| Provider | Tradeoffs |
|---|---|
| `edge` | Free, good enough for most people |
| `neutts` | Free, on-device, no key needed |
| `elevenlabs` | Best quality, paid |
| `openai` | Good middle ground, paid |
| `mistral` | Multilingual, outputs native Opus |

### Using `spark setup`?

Choose NeuTTS in the wizard and it handles everything: checks whether `neutts` is installed, offers to install `espeak-ng` with your system package manager, and runs `python -m pip install -U neutts[all]`. If that fails, the wizard falls back to Edge TTS automatically.

---

## Recommended config to start

Drop this into your `~/.spark/config.yaml`:

```yaml
voice:
  record_key: "ctrl+b"
  max_recording_seconds: 120
  auto_tts: false
  silence_threshold: 200
  silence_duration: 3.0

stt:
  provider: "local"
  local:
    model: "base"

tts:
  provider: "edge"
  edge:
    voice: "en-US-AriaNeural"
```

Prefer on-device TTS? Swap the `tts` block for:

```yaml
tts:
  provider: "neutts"
  neutts:
    ref_audio: ''
    ref_text: ''
    model: neuphonic/neutts-air-q4-gguf
    device: cpu
```

---

## CLI voice mode

### Turn it on

```bash
spark
```

Then inside the session:

```text
/voice on
```

### How recording works

1. Press `Ctrl+B`
2. Speak
3. Silence detection stops recording automatically
4. Spark transcribes and responds
5. If TTS is enabled, it reads the answer aloud
6. The loop restarts for continuous use

### Commands

```text
/voice
/voice on
/voice off
/voice tts
/voice status
```

### What to actually use it for

**Debugging without your hands:**
```text
I keep getting a docker permission error. Help me debug it.
```
Then continue: "Read the last error again" → "Explain the root cause" → "Give me the exact fix."

**Walking around and brainstorming:** Dictate half-formed ideas and let Spark structure them in real time.

**Low-typing sessions:** If typing is inconvenient for any reason, voice mode keeps you in the full Spark loop.

---

## Tuning the CLI experience

### Silence threshold

Recording stops or starts too aggressively? Raise the threshold:

```yaml
voice:
  silence_threshold: 250
```

Higher = less sensitive to ambient noise.

### Silence duration

You pause a lot between sentences? Give yourself more time:

```yaml
voice:
  silence_duration: 4.0
```

### Record key

`Ctrl+B` clashes with tmux? Change it:

```yaml
voice:
  record_key: "ctrl+space"
```

---

## Voice replies in Telegram or Discord

This is simpler than full voice channels. The bot stays a text chat bot — it just speaks its replies.

### Start the gateway

```bash
spark gateway
```

### Enable voice replies

In Telegram or Discord chat:

```text
/voice on
```

Or for spoken-only mode all the time:

```text
/voice tts
```

### Reply modes

| Mode | What happens |
|---|---|
| `off` | Text only |
| `voice_only` | Speak only when the user sent voice |
| `all` | Speak every reply |

**When to use which:**
- `/voice on` — spoken replies only for voice-originated messages
- `/voice tts` — full spoken assistant, always

### Good use cases

- Away from your machine, sending voice notes from your phone and getting spoken replies
- Discord DMs where you want private spoken output without server channel noise

---

## Discord voice channels

The most powerful mode. Spark joins a voice channel, listens for speech, transcribes it, runs the agent, and speaks back into the channel.

### Required Discord permissions

Your bot needs these in the Developer Portal:
- Connect
- Speak
- Use Voice Activity (preferred)

Privileged intents:
- Presence Intent
- Server Members Intent
- Message Content Intent

### Join and leave

In any Discord text channel where the bot is present:

```text
/voice join
/voice leave
/voice status
```

### What happens after joining

- Users speak in the VC
- Spark detects speech boundaries
- Transcripts appear in the text channel where you typed `/voice join`
- Spark replies in both text and audio

### Best practices

- Keep `DISCORD_ALLOWED_USERS` tight — do not leave this open
- Use a dedicated test channel before going live
- Confirm STT and TTS work in regular chat mode first

---

## Provider recommendations by goal

| Goal | STT | TTS |
|---|---|---|
| Best quality | local `large-v3` or Groq `whisper-large-v3` | ElevenLabs |
| Best speed | local `base` or Groq | Edge |
| Zero cost | local | Edge |

---

## Troubleshooting

### "No audio device found"
Install `portaudio`.

### "Bot joins but hears nothing"
Check: your user ID is in `DISCORD_ALLOWED_USERS`, you are not muted, privileged intents are enabled, the bot has Connect and Speak permissions.

### "Spark transcribes but never speaks"
Check: TTS provider config, API key/quota for ElevenLabs or OpenAI, `ffmpeg` install for Edge TTS conversion.

### "Whisper outputs garbage"
Try: a quieter environment, a higher `silence_threshold`, a different provider or model, shorter and clearer utterances.

### "Works in DMs but not in server channels"
Likely a mention policy issue. By default the bot needs an `@mention` in Discord server text channels unless you configure it otherwise.

---

## The shortest path to success

1. Get text Spark working
2. Install `spark-agent[voice]`
3. Use CLI voice mode with local STT + Edge TTS
4. Enable `/voice on` in Telegram or Discord
5. Only then try Discord VC mode

Each step is a smaller debugging surface than jumping straight to the end.

---

## Read next

- [Voice Mode feature reference](../voice/voice-mode.md)
- [Messaging Gateway](../chat-platforms/index.md)
- [Discord setup](../chat-platforms/discord.md)
- [Telegram setup](../chat-platforms/telegram.md)
- [Configuration](../configuration.md)
