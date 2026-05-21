---
sidebar_position: 10
title: "Voice Mode"
description: "Real-time voice conversations with Spark Agent - CLI, Telegram, Discord (DMs, text channels, and voice channels)"
---

# Voice Mode

Talk to Spark using your microphone and hear spoken replies. Works in the CLI, Telegram, Discord DMs, Discord text channels, and live Discord voice channels.

For a practical setup walkthrough with recommended configurations, see [Enable Voice Mode](../guides/enable-voice-mode.md).

## What's Available

| Feature | Where | What it does |
|---------|-------|-------------|
| Push-to-talk | CLI | Press Ctrl+B, speak, get a spoken reply |
| Auto voice reply | Telegram, Discord | Agent speaks its reply when you send a voice message |
| Voice channel | Discord | Bot joins VC, listens, and speaks replies live |

---

## Before You Start

1. Spark installed — `pip install spark-agent`
2. An LLM provider configured — run `spark model` or add keys to `~/.spark/.env`
3. Confirm text chat works first — run `spark` and send a message

> The `~/.spark/` directory and default `config.yaml` are created on first run. You only need to create `~/.spark/.env` manually for API keys.

---

## Install Voice Packages

```bash
pip install "spark-agent[voice]"      # CLI voice mode
pip install "spark-agent[messaging]"  # Telegram + Discord bots
pip install "spark-agent[tts-premium]"  # ElevenLabs TTS
pip install "spark-agent[all]"        # Everything
```

| Extra | Installs | Needed for |
|-------|----------|------------|
| `voice` | `sounddevice`, `numpy` | CLI push-to-talk |
| `messaging` | `discord.py[voice]`, telegram bot, aiohttp | Messaging bots |
| `tts-premium` | `elevenlabs` | ElevenLabs TTS |

For NeuTTS (local, no API key), install separately:

```bash
python -m pip install -U neutts[all]
```

### System dependencies

```bash
# macOS
brew install portaudio ffmpeg opus
brew install espeak-ng   # for NeuTTS

# Ubuntu/Debian
sudo apt install portaudio19-dev ffmpeg libopus0
sudo apt install espeak-ng   # for NeuTTS
```

| Package | Purpose |
|---------|---------|
| PortAudio | Microphone input and audio playback (CLI) |
| ffmpeg | Audio format conversion |
| Opus | Discord voice codec |
| espeak-ng | Phonemizer for NeuTTS |

### API keys

Add to `~/.spark/.env`:

```bash
# STT — local Whisper needs no key
# pip install faster-whisper           # free, runs on your machine
GROQ_API_KEY=your-key                  # Groq Whisper (fast, free tier)
VOICE_TOOLS_OPENAI_KEY=your-key        # OpenAI Whisper (paid)

# TTS — Edge TTS and NeuTTS need no key
ELEVENLABS_API_KEY=your-key            # premium quality
```

---

## CLI Voice Mode

### Enable it

```bash
spark     # start the CLI
```

Then inside Spark:

```
/voice on       Enable voice mode
/voice off      Disable voice mode
/voice tts      Toggle spoken replies
/voice status   Show current state
```

### How recording works

1. Press **Ctrl+B** — a beep plays, recording starts
2. Speak — a live level bar shows your audio
3. Stop speaking — after 3 seconds of silence, recording stops automatically
4. Two beeps confirm the recording ended
5. Audio is transcribed and sent to the agent
6. If TTS is on, the reply is spoken aloud
7. Recording restarts automatically — speak again without pressing anything

This loop continues until you press **Ctrl+B** during recording (exits continuous mode) or 3 consecutive recordings detect no speech.

The record key is configurable via `voice.record_key` in `config.yaml` (default: `ctrl+b`).

### Silence detection

Spark uses a two-stage algorithm:

1. **Speech confirmation** — waits for audio above RMS threshold (200) for at least 0.3s, tolerating brief gaps between syllables
2. **End detection** — after speech is confirmed, triggers after 3.0 seconds of continuous silence

If no speech is detected for 15 seconds, recording stops. Both `silence_threshold` and `silence_duration` are configurable.

### Streaming TTS

Replies play sentence-by-sentence as they're generated — you don't wait for the full response. Spark buffers text deltas into complete sentences, strips markdown and `<think>` blocks, then generates and plays audio per sentence in real time.

### Hallucination filter

Whisper sometimes generates phantom text from silence or background noise ("Thank you for watching", "Subscribe", etc.). Spark filters these out using 26 known hallucination phrases across multiple languages plus a regex for repetitive variations.

---

## Gateway Voice Reply (Telegram & Discord)

First-time setup? See [Telegram Setup](../chat-platforms/telegram.md) or [Discord Setup](../chat-platforms/discord.md).

```bash
spark gateway        # start the gateway
spark gateway setup  # first-time setup wizard
```

### Commands (both platforms)

```
/voice          Toggle voice mode on/off
/voice on       Speak reply only when you send a voice message
/voice tts      Speak reply to every message
/voice off      Disable voice replies
/voice status   Show current setting
```

| Mode | Command | Behavior |
|------|---------|----------|
| Off (default) | `/voice off` | Text replies only |
| Voice-triggered | `/voice on` | Speaks only when you send a voice message |
| Always-on | `/voice tts` | Speaks every reply |

Voice mode setting persists across gateway restarts.

### Discord: channels vs DMs

| Mode | How to talk | Mention needed? |
|------|------------|:---:|
| DM | Open the bot's profile → "Message" | No |
| Server channel | Type in a text channel with the bot | Yes (`@botname`) |

DMs are the simplest for personal use — no @mention, everything just works.

To remove the mention requirement in channels, add to `~/.spark/.env`:

```bash
DISCORD_REQUIRE_MENTION=false
# or allow specific channels without mention:
DISCORD_FREE_RESPONSE_CHANNELS=123456789,987654321
```

### Audio delivery

| Platform | Format | Notes |
|----------|--------|-------|
| Telegram | Voice bubble (Opus/OGG) | Plays inline, ffmpeg converts MP3 if needed |
| Discord | Native voice bubble (Opus/OGG) | Falls back to file attachment if voice bubble API fails |

---

## Discord Voice Channels

The bot can join a voice channel, listen to everyone speaking, and talk back in real time.

### Setup

#### 1. Add voice permissions to your bot

In the [Discord Developer Portal](https://discord.com/developers/applications) → your app → **Installation** → **Default Install Settings** → **Guild Install**, add:

| Permission | Purpose |
|-----------|---------|
| Connect | Join voice channels |
| Speak | Play TTS audio |
| Use Voice Activity | Detect when users are speaking |

Updated permissions integer for text + voice: **`274881432640`**

Re-invite the bot to apply updated permissions:

```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=274881432640
```

Re-inviting a bot that's already in a server just updates permissions — no data is lost.

#### 2. Enable privileged gateway intents

In the Developer Portal → your app → **Bot** → **Privileged Gateway Intents**, enable all three:

| Intent | Why |
|--------|-----|
| Presence Intent | Detect user status |
| Server Members Intent | Map voice streams to user IDs |
| Message Content Intent | Read text messages |

**Server Members Intent is required** — without it, the bot can't identify who's speaking.

#### 3. Install the Opus codec

```bash
brew install opus              # macOS
sudo apt install libopus0      # Ubuntu/Debian
```

The bot loads it automatically from standard paths.

#### 4. Environment variables

```bash
# ~/.spark/.env
DISCORD_BOT_TOKEN=your-bot-token
DISCORD_ALLOWED_USERS=your-user-id
# STT: pip install faster-whisper (no key) or set GROQ_API_KEY
```

### Start

```bash
spark gateway
```

### Voice channel commands

Use in the text channel where the bot is present:

```
/voice join      Bot joins your current voice channel
/voice channel   Alias for /voice join
/voice leave     Bot disconnects
/voice status    Show voice mode and current channel
```

You must be in a voice channel before running `/voice join`. The bot joins whichever VC you're in.

### How it works

1. Listens to each user's audio stream separately
2. After 1.5s of silence (following at least 0.5s of speech), processes the recording
3. Transcribes via Whisper STT
4. Runs through the full agent pipeline (session, tools, memory)
5. Speaks the reply back in the voice channel

Transcripts and replies also appear in the text channel where `/voice join` was used. The bot automatically pauses its listener while speaking to prevent it from hearing itself.

Only users in `DISCORD_ALLOWED_USERS` can interact via voice.

---

## Configuration Reference

```yaml
# ~/.spark/config.yaml

voice:
  record_key: "ctrl+b"
  max_recording_seconds: 120
  auto_tts: false
  silence_threshold: 200    # RMS level below which = silence
  silence_duration: 3.0     # seconds of silence before auto-stop

stt:
  provider: "local"         # "local" | "groq" | "openai" | "mistral"
  local:
    model: "base"           # tiny, base, small, medium, large-v3

tts:
  provider: "edge"          # "edge" | "elevenlabs" | "openai" | "neutts" | "minimax"
  edge:
    voice: "en-US-AriaNeural"
  elevenlabs:
    voice_id: "pNInz6obpgDQGcFmaJgB"
    model_id: "eleven_multilingual_v2"
  openai:
    model: "gpt-4o-mini-tts"
    voice: "alloy"
```

### STT quick comparison

| Provider | Speed | Cost | Key needed? |
|----------|-------|------|:-----------:|
| Local `base` | Fast | Free | No |
| Local `large-v3` | Slow | Free | No |
| Groq `whisper-large-v3-turbo` | Very fast (~0.5s) | Free tier | Yes |
| OpenAI `whisper-1` | Fast (~1s) | Paid | Yes |
| OpenAI `gpt-4o-transcribe` | Medium (~2s) | Paid | Yes |

Fallback order: **local → groq → openai**

### TTS quick comparison

| Provider | Quality | Cost | Key needed? |
|----------|---------|------|:-----------:|
| Edge TTS | Good | Free | No |
| NeuTTS | Good | Free | No |
| OpenAI TTS | Good | Paid | Yes |
| ElevenLabs | Excellent | Paid | Yes |
| MiniMax | Excellent | Paid | Yes |

---

## Troubleshooting

**"No audio device found"**  
PortAudio isn't installed. `brew install portaudio` (macOS) or `sudo apt install portaudio19-dev` (Linux).

**Bot doesn't respond in server channels**  
It requires an @mention. Pick the bot user from the mention popup (not a role with the same name), or set `DISCORD_REQUIRE_MENTION=false`.

**Bot joins VC but doesn't hear me**  
- Check your user ID is in `DISCORD_ALLOWED_USERS`
- Make sure you're not muted in Discord
- Start speaking within a few seconds of the bot joining

**Bot hears me but doesn't respond**  
- Install `faster-whisper` or set a cloud STT key
- Verify the LLM model is configured
- Check `~/.spark/logs/gateway.log`

**Bot responds in text but not in voice**  
TTS provider may be failing. Edge TTS (free, no key) is the default fallback. Check logs for TTS errors.

**Whisper transcribes garbage**  
The hallucination filter catches most cases automatically. If it's still happening: use a quieter environment, raise `silence_threshold` in config, or try a larger STT model.
