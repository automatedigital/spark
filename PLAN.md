# Spark — Bug Fixes & Feature List

---

## Agent Brief

Spark is a production-grade, multi-provider AI agent CLI (~137K LOC Python + React/TypeScript web dashboard). It runs as an interactive TUI (`spark`), a gateway server (Telegram, Discord, Slack, WhatsApp, Signal, Matrix), and a cron scheduler for unattended jobs. The web dashboard lives in `src/spark_cli/web/`.

Work through bugs **CRITICAL → HIGH → MEDIUM → LOW**, then features. Complete one item fully (fix + test + commit) before moving to the next. For frontend features, verify `npm run build` passes in `src/spark_cli/web/`.

**Tests:**
```bash
python -m pytest tests/ -q          # ~89 pre-existing failures are expected — don't count as regressions
ruff check src/ && mypy src/agent/ src/spark_cli/
```

**Key files:**

| File | Purpose |
|------|---------|
| `src/core/spark_state.py` | `SessionDB` SQLite session store |
| `src/cron/scheduler.py` | Cron scheduler — `run_job()`, `_deliver_result()` |
| `src/gateway/run.py` | Gateway HTTP/WebSocket server — all API endpoints |
| `src/tools/registry.py` | Tool registration and dispatch — `_post_process()` |
| `src/spark_cli/web/src/` | React/TypeScript web dashboard |

---

## BUG FIXES

### MEDIUM

- [ ] **B1. `_fileBaselines` map in `WorkspacePage.tsx` grows unbounded**
  `src/spark_cli/web/src/pages/WorkspacePage.tsx`. The module-level `_fileBaselines = new Map<string, string>()` accumulates baseline snapshots for every file opened across all sessions and is never cleared. Over a long-running browser session with many files this is a quiet memory leak. Add a `useEffect` that calls `_fileBaselines.clear()` when the active `sessionId` changes, and also `return () => _fileBaselines.clear()` in the cleanup for the workspace component mount.

- [ ] **B2. `NotificationBell.tsx` `EventSource` may not close on fast navigation**
  `src/spark_cli/web/src/components/NotificationBell.tsx`. The `useEffect` sets up an `EventSource` and returns a cleanup. If the component unmounts before the `EventSource` fires its `onopen`, some environments will not invoke the cleanup, leaving an open connection. Verify the cleanup calls `es.close()` unconditionally (not inside an `if (es.readyState !== EventSource.CLOSED)` guard), and add an `es.onerror` handler that calls `es.close()` when `e.target.readyState === EventSource.CLOSED` to handle server-side disconnects without dangling listeners.

- [ ] **B3. Flaky `TestSilentDelivery` tests — shared module-level `_live_adapters` dict**
  `src/cron/scheduler.py` + `tests/cron/test_scheduler.py`. The `_live_adapters` dict is module-level shared state. Tests that register a mock adapter affect subsequent tests that run in the same process, causing order-dependent failures (`test_normal_response_delivers`, `test_failed_job_always_delivers` fail when the full suite runs but pass in isolation). Add a `setUp`/`tearDown` (or `@patch` decorator) in `TestSilentDelivery` that saves and restores `scheduler._live_adapters` around each test, or refactor the dict to be per-instance state passed via dependency injection.

- [ ] **B4. `ConversationsPage.tsx` fork tree view never implemented**
  F12 added the `↩ Forked from` badge in `ChatPanel.tsx` and the `GET /api/sessions/{id}/forks` endpoint, but `ConversationsPage.tsx` still renders all sessions in a flat list with no visual grouping. Forked sessions should be indented under their parent. Add a `buildSessionTree(sessions)` utility that groups sessions by `parent_session_id` and render the tree with a left-border accent and reduced opacity for child sessions. Fetch each parent's fork count via the existing endpoint when the page loads.

---

### LOW

- [ ] **B5. PDF files fall through to raw `<pre>` in `ToolCallBubble.tsx`**
  `src/spark_cli/web/src/components/chat/ToolCallBubble.tsx`. The `detectOutputType` utility (`src/spark_cli/web/src/lib/detectOutputType.ts`) identifies `.pdf` paths, but the `ResultPreview` component has no renderer for them — it falls through to the existing `<pre>` block, showing a raw path string. Add a `kind === "pdf"` branch that renders `<iframe src={url} className="w-full h-64 rounded border" />` with a "Open in new tab" link below it as a fallback for browsers that block embedded PDFs.

- [ ] **B6. `GET /api/voice/tts` content-type detection relies on file extension only**
  When the voice TTS endpoint (to be added in F4) calls `_generate_supertonic_tts()`, the output path is a `NamedTemporaryFile` with suffix `.wav`. But the edge/openai/piper providers write `.mp3` and `neutts` writes `.ogg`. If a provider writes to an extension-less temp path, `FileResponse` will serve `application/octet-stream` and the browser `<audio>` element will fail to decode it. After writing the audio file, inspect the first 4 bytes (magic bytes: `ID3`/`\xff\xfb` for MP3, `OggS` for OGG, `RIFF` for WAV) to determine content-type rather than relying solely on extension.

---

## FEATURE LIST

- [ ] **F1. Voice mode — animated call UI with local-first TTS/STT**

  ### What already exists (do not reimplement)

  - **TTS** — `src/tools/tts_tool.py` (~1200 lines). Supports 7 providers: `edge` (default, free, `edge_tts` package), `elevenlabs` (API key in `ELEVENLABS_API_KEY`, streaming already implemented at lines 218–259), `openai`, `minimax`, `mistral`, `neutts` (local neural), `piper` (local, offline). Provider is read from `config.yaml` at path `tts.provider`. Helper `_get_provider(tts_config)` at line 137 returns the active provider name. Each provider has a `_generate_<name>_tts(text, output_path, tts_config) -> str` function that writes an audio file and returns its path.
  - **STT** — `src/tools/transcription_tools.py`. Three providers: `local` (faster-whisper, free, default), `openai` (whisper-1 / gpt-4o-transcribe), `groq`. Provider auto-selected by `_get_provider(stt_config)` at line 163 — checks for faster-whisper install, then API key presence. `transcribe_recording(wav_path, model)` is the top-level call. Whisper hallucination filtering at `is_whisper_hallucination(transcript)` in `voice_mode.py` line 772.
  - **Voice mode orchestration** — `src/tools/voice_mode.py` (~1017 lines). `AudioRecorder` class (line 372) handles microphone capture with silence detection. `check_voice_requirements()` (line 924) returns a dict indicating what's available. `transcribe_recording()` (line 789) dispatches to the active STT provider. `play_audio_file(path)` (line 843) plays output through sounddevice/pygame/mpv/afplay.
  - **Config** — `src/spark_cli/config.py`. `DEFAULT_CONFIG["voice"]` (line 650) already has: `record_key`, `max_recording_seconds`, `auto_tts`, `silence_threshold` (RMS int 0–32767), `silence_duration`. `DEFAULT_CONFIG["tts"]` and `DEFAULT_CONFIG["stt"]` sections hold provider sub-configs.
  - **No web endpoints exist yet** — `grep -n "/api/voice"` in `web_server.py` returns nothing. The TTS/STT tools are CLI-only today.

  ---

  ### New TTS provider: Supertonic-3

  Add **`supertonic`** as an 8th TTS provider alongside the existing seven. Model: [`Supertone/supertonic-3`](https://huggingface.co/Supertone/supertonic-3) on HuggingFace.

  #### Integration points in `src/tools/tts_tool.py`

  1. **Add to `_get_provider()` resolution** — ensure `"supertonic"` is a recognized value (no change needed if the function just passes through unknown names; add it to any validation list that exists).

  2. **Add `_generate_supertonic_tts(text, output_path, tts_config) -> str`** following the existing lazy-import pattern:
     ```python
     def _generate_supertonic_tts(text: str, output_path: str, tts_config: dict) -> str:
         try:
             from transformers import pipeline as hf_pipeline
             import soundfile as sf
             import numpy as np
         except ImportError as exc:
             raise ImportError(
                 "Supertonic-3 requires: pip install transformers soundfile torch"
             ) from exc

         model_id = tts_config.get("supertonic", {}).get("model_id", "Supertone/supertonic-3")
         device = tts_config.get("supertonic", {}).get("device", "auto")  # "auto", "cpu", "cuda", "mps"
         if device == "auto":
             import torch
             if torch.backends.mps.is_available():
                 device = "mps"
             elif torch.cuda.is_available():
                 device = "cuda"
             else:
                 device = "cpu"

         tts = hf_pipeline("text-to-speech", model=model_id, device=device)
         result = tts(text)
         # result is {"audio": np.ndarray, "sampling_rate": int}
         sf.write(output_path, result["audio"], result["sampling_rate"])
         return output_path
     ```

  3. **Wire into the dispatch block** — in whatever `match`/`if` block routes provider names to handler functions, add:
     ```python
     case "supertonic":
         return _generate_supertonic_tts(text, output_path, tts_config)
     ```

  4. **Config additions** — in `DEFAULT_CONFIG["tts"]` in `src/spark_cli/config.py`, add a `supertonic` sub-dict:
     ```python
     "supertonic": {
         "model_id": "Supertone/supertonic-3",
         "device": "auto",   # auto-selects mps > cuda > cpu
     },
     ```

  #### Hardware note
  Supertonic-3 is a neural model; GPU acceleration is strongly recommended. On Apple Silicon, `device="mps"` gives real-time speed. On CPU it will be slow for long utterances. The auto-detection above (`mps` → `cuda` → `cpu`) matches what `neutts` already does for device selection — follow the same pattern.

  #### Dependencies
  ```
  pip install transformers soundfile torch
  ```
  All are optional (lazy-imported inside the function). `soundfile` is already used by other tools so it is likely present. `torch` and `transformers` are only needed when `tts.provider = "supertonic"`.

  ---

  ### What needs to be built

  #### 1. Backend — three new endpoints in `src/spark_cli/web_server.py`

  **`POST /api/voice/transcribe`**
  - Accept `multipart/form-data` with a single `audio` field (WebM/OGG blob from browser MediaRecorder).
  - Save to a temp file, call `transcribe_recording(wav_path)` from `tools.transcription_tools`, return `{"text": "...", "provider": "..."}`.
  - If faster-whisper is not installed and no API key is configured, return `{"error": "no_stt_provider", "text": ""}` — the frontend must show a setup hint.
  - Auth: require the session token (same `_require_auth` pattern used by all other endpoints).

  **`GET /api/voice/tts`**
  - Query params: `text` (URL-encoded string), `provider` (optional, overrides config).
  - Call the appropriate `_generate_<provider>_tts()` function from `tts_tool.py`, write to a NamedTemporaryFile, then stream the file using `FileResponse` or a `StreamingResponse` that reads and deletes the temp file after streaming.
  - Detect content-type from magic bytes (see B6), not just file extension.
  - ElevenLabs streaming path (already returns a generator in `tts_tool.py` around line 244) should be streamed directly without buffering to disk if possible.
  - Supertonic produces WAV output from `soundfile.write()`; serve as `audio/wav`.

  **`GET /api/voice/capabilities`**
  - Call `check_voice_requirements()` from `tools.voice_mode` and return its dict as JSON.
  - Augment the response with `{"tts_provider": _get_provider(tts_config), "stt_provider": _get_provider(stt_config)}`.
  - Used by the frontend on modal open to decide whether to show setup instructions or proceed directly.

  #### 2. Config additions in `src/spark_cli/config.py`

  Add to `DEFAULT_CONFIG["voice"]` (existing dict at line 650):
  ```python
  "web_enabled": True,               # master switch shown in Settings > Voice
  "interrupt_threshold_rms": 0.02,   # Web Audio RMS float (0.0–1.0) above which mic input interrupts playback
  ```
  Add `supertonic` sub-dict to `DEFAULT_CONFIG["tts"]` as described in the Supertonic-3 section above.

  #### 3. Frontend — `src/spark_cli/web/src/components/VoiceCallModal.tsx` (new file, ~300 lines)

  **Trigger:** Add a `<Mic>` icon button to `PromptBar.tsx` (`src/spark_cli/web/src/components/chat/PromptBar.tsx`, currently 163 lines). Add an `onVoiceCall?: () => void` prop alongside existing props (line 6). Render the button between the upload button and the send button; disable when `streaming` is true. In `ChatPanel.tsx`, pass `onVoiceCall={() => setVoiceOpen(true)}` and add `voiceOpen` + `setVoiceOpen` state.

  **Modal structure:**
  ```
  <VoiceCallModal open onClose capabilities={...} sessionId={...} />
  ```
  - Full-screen overlay (`fixed inset-0 z-[200]`) with a dark frosted glass background.
  - Two waveform visualizer circles — user (bottom-left) and agent (bottom-right) — using `<canvas>` + `requestAnimationFrame` + Web Audio API `AnalyserNode`.
    - User canvas: connected to `MediaStream` from `getUserMedia({ audio: true })`. Bars pulse green while recording, gray while muted.
    - Agent canvas: driven by an `AudioContext` source node connected to the TTS audio blob. Bars pulse blue/indigo during playback, gray when idle.
  - Live transcript strip (scrolling `<div>` in the center) showing the last 5 turns, styled like chat messages.
  - Bottom button row: `Mute` toggle (mic icon, toggling `stream.getAudioTracks()[0].enabled`), `Hang up` (red phone-down icon, closes modal and stops all tracks).
  - A "Setting up…" state while `GET /api/voice/capabilities` is loading; if capabilities missing show a styled error with install instructions.

  **Recording loop (inside the modal, using `useRef` for MediaRecorder):**
  1. On open: call `navigator.mediaDevices.getUserMedia({ audio: true })`.
  2. Create `MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" })`.
  3. On `dataavailable`: collect chunks into a `Blob`.
  4. On `stop`: POST the blob to `POST /api/voice/transcribe`, get back `{ text }`, append user message to transcript strip, send text to the existing chat `onSend(text)` callback.
  5. Silence detection: use `AnalyserNode.getByteTimeDomainData()` each animation frame, compute RMS, if below `interrupt_threshold_rms` for >1.5s and currently recording — stop MediaRecorder.
  6. Auto-restart: after sending, wait for the agent response via the existing SSE event bus (`/api/events?topics=chat`), detect `chat.token_end` event for this session, fetch the last assistant message, send it to `GET /api/voice/tts`, play back the returned audio.

  **Interruption:** When user starts speaking (RMS > threshold) while agent audio is playing, immediately call `audioElement.pause()` and `audioElement.currentTime = 0` (or `audioContext.close()` if using Web Audio for playback), then restart MediaRecorder.

  **State machine** (can be a `useReducer` or simple `useState` string):
  `idle` → `listening` → `processing` → `speaking` → `listening` → …
  Modal shows a status label matching the current state.

  #### 4. Settings panel hook

  In `src/spark_cli/web/src/components/SettingsPanel.tsx`, add a **Voice** tab section showing:
  - `voice.web_enabled` toggle.
  - Read-only display of the active TTS provider (from `GET /api/voice/capabilities`). For `supertonic`, show "Supertonic-3 (local neural)" and a note about torch/GPU requirements.
  - Read-only display of the active STT provider.
  - A "Test TTS" button that calls `GET /api/voice/tts?text=Hello+from+Spark` and plays the result.

  #### 5. Browser compatibility note

  `MediaRecorder` with `audio/webm;codecs=opus` works in Chrome/Edge/Firefox. Safari requires `audio/mp4` (AAC). Check `MediaRecorder.isTypeSupported()` and fall back to `audio/mp4` on Safari. The backend should handle both via ffmpeg or soundfile for format conversion if needed (faster-whisper accepts WAV/MP3/WebM natively via ffmpeg).

  #### Suggested build order

  1. Add `_generate_supertonic_tts()` to `tts_tool.py` + config defaults (30 min).
  2. `GET /api/voice/capabilities` endpoint (5 min).
  3. `POST /api/voice/transcribe` endpoint (30 min).
  4. `GET /api/voice/tts` endpoint with magic-byte content-type detection (45 min).
  5. `VoiceCallModal.tsx` without waveforms (transcript + basic record/playback loop) (2h).
  6. Add waveform visualizers (1h).
  7. Wire mic button into `PromptBar.tsx` + `ChatPanel.tsx` (15 min).
  8. Settings panel Voice section (30 min).
  9. Test on Chrome + Safari, handle codec fallback.

- [ ] **F2. Global session full-text search**
  `SessionDB` in `src/core/spark_state.py` already has an FTS5 index and a `search_sessions(query)` method, but there is no web UI to use it. Add a search input at the top of `ConversationsPage.tsx` (debounced, 300ms) that calls a new `GET /api/sessions?q=<query>` endpoint in `web_server.py` (route already exists but check if `q` param is handled — if not, wire `search_sessions()` into the existing list endpoint). Highlight matched text in session titles and snippets. Searching `""` should return the normal recent-sessions list. No new backend infrastructure needed — FTS5 is already there.

- [ ] **F3. Cron job "next run" live preview on the schedule editor**
  `CronPage.tsx` has a friendly cron picker (F3, now done), but shows no indication of when the job will next fire. After the user changes the frequency/time fields (or the raw cron input in Custom mode), compute and display "Next run: Monday 09:00 local time" below the field. Use the same `cronToFriendly` / `friendlyToCron` utilities already in `CronPage.tsx` plus a lightweight client-side cron-parser (the `cronstrue` or `cron-parser` npm packages, or a minimal inline implementation) to calculate the next fire time. No backend changes needed.

- [ ] **F4. `ConversationsPage.tsx` global keyword filter + tag/label system**
  Currently `ConversationsPage.tsx` lists sessions in reverse-chronological order with no filtering beyond the FTS search added in F2. Add: (1) a **tag** system — users can label sessions with freeform tags (stored as a JSON array in a new `tags` column on the `sessions` SQLite table, exposed via `PUT /api/sessions/{id}/tags`); (2) a tag filter bar below the search input that shows all used tags as chips — clicking a chip filters the list to sessions with that tag; (3) a "star/pin" toggle per session (stored as a boolean `pinned` column) that keeps pinned sessions at the top of the list regardless of sort order. Backend: two new columns (`tags TEXT DEFAULT '[]'`, `pinned INTEGER DEFAULT 0`) in `spark_state.py` with migration logic; two new API endpoints. Frontend: tag chips in session row, `TagEditor` popover on right-click or via a `...` menu.
