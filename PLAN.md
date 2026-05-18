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

### CRITICAL

- [x] **1. Shell injection in gateway quick-command execution**
  `src/gateway/run.py` ~2999. `asyncio.create_subprocess_shell()` passes the user-supplied `exec_cmd` string directly to the shell without any validation or escaping. Any gateway user can execute arbitrary shell commands on the host. Fix by switching to `create_subprocess_exec()` with a pre-split argument list (`shlex.split(exec_cmd)`) and optionally whitelisting allowed commands before execution.

- [x] **2. `fetchone()[0]` crashes when query returns no rows (3 sites)**
  `src/core/spark_state.py` ~1150, 1161, 1210. `cursor.fetchone()[0]` raises `TypeError` when the COUNT query returns no rows — affects `session_count()`, `message_count()`, and at least one additional call site. Fix each site with: `row = cursor.fetchone(); return row[0] if row else 0`.

---

### HIGH

- [x] **3. `BaseException` caught in skill_usage cleanup — swallows Ctrl-C**
  `src/tools/skill_usage.py` ~138-140. `except BaseException:` catches `KeyboardInterrupt` and `SystemExit`, preventing clean process termination during tool cleanup. This directly violates the documented rule in CLAUDE.md. Change to `except Exception:`.

- [x] **4. `KeyboardInterrupt` silently dropped in Anthropic adapter setup**
  `src/agent/anthropic_adapter.py` ~591-593. User cancellation (Ctrl-C) during interactive setup flow is caught and silently converted to a `None` return value instead of propagating. The caller has no way to distinguish a cancelled setup from a completed one. Re-raise `KeyboardInterrupt` after logging.

- [x] **5. Return type violation in `registry._post_process()`**
  `src/tools/registry.py` ~440. Function is annotated `-> str` but returns non-string values when `not isinstance(raw, str)`. Downstream tool dispatch code that assumes a string return will silently mishandle the result. Ensure all branches coerce to `str` (e.g. `json.dumps(raw)`) or fix the annotation to `-> Any`.

- [x] **6. File descriptor leak in `memory_tool.py` lock acquisition**
  `src/tools/memory_tool.py` ~142. `fd = open(lock_path, "w")` opens a file descriptor that is not guaranteed to close if an exception occurs between `open()` and `fcntl.flock()`. On repeated failures this exhausts available fds. Refactor to `with open(lock_path, "w") as fd: fcntl.flock(fd, ...)`.

- [x] **7. `devnull` file descriptor leak in `code_execution_tool.py`**
  `src/tools/code_execution_tool.py` ~390-399. `devnull = open(os.devnull, "w")` is assigned before `Popen`. If `Popen` raises (bad executable, permission error), the finally block that closes `devnull` may not execute because the variable isn't yet in scope for the handler. Wrap in `with open(os.devnull, "w") as devnull:` and restructure the `Popen` call inside that block.

- [x] **8. `run_job()` is 320+ lines — untestable monolith**
  `src/cron/scheduler.py` ~577. The function mixes env-var loading, config file parsing, credential pool selection, model routing, agent initialization, execution with inactivity timeout, output formatting, and error reporting. Each concern is impossible to unit-test in isolation. Extract into: `_setup_job_environment(job)`, `_initialize_job_agent(job, env)`, `_execute_job_with_timeout(agent, job)`, `_format_job_output(result, job)`. `run_job()` becomes an orchestrator that calls each in sequence.

- [x] **9. `_deliver_result()` is 166 lines**
  `src/cron/scheduler.py` ~200. Combines delivery-target resolution, adapter selection, text extraction from rich output, media file detection, and both live-adapter and HTTP fallback delivery paths. Extract into: `_build_delivery_content(result)` → returns `(text, media_files)`, `_send_via_live_adapter(adapter, text, media_files)`, `_send_via_standalone_path(platform, channel, text)`.

---

### MEDIUM

- [x] **10. Three sources of truth for the platform list**
  `src/cron/scheduler.py` ~44-49 (`_KNOWN_DELIVERY_PLATFORMS` frozenset) and ~241-259 (hardcoded name→enum mapping) both duplicate what the `Platform` enum in `src/gateway/config.py` already defines. A new platform added to the enum is silently ignored by the scheduler. Remove the frozenset and derive the mapping programmatically from `Platform` members.

- [x] **11. `except Exception: pass` silently swallowing errors at multiple sites**
  `src/gateway/channel_directory.py` ~140, `src/gateway/status.py` ~272, `src/cron/scheduler.py` ~286/380/389, `src/core/model_tools.py` plugin hooks ~537-595. Silent pass blocks make it impossible to diagnose misconfigured plugins, failed Slack imports, and PID file cleanup errors. At minimum add `logger.debug("...", exc_info=True)` in each block; use specific exception types where the failure mode is known.

- [x] **12. Lock acquired inside per-match loop causes unnecessary contention**
  `src/core/spark_state.py` ~1093-1109. A comment says context fetches are "done outside the lock" but the lock is actually re-acquired on every iteration of the `for match in matches` loop. This serializes all context reads. Batch the context query into a single `WHERE id IN (...)` call before the loop.

- [x] **13. Silent JSON fallback masks data corruption in session history**
  `src/core/spark_state.py` ~900-907, 934-935. `json.JSONDecodeError` is caught and falls back to `[]` for `tool_calls` and `content` fields without any logging. Corrupted session rows are silently discarded. Add `logger.warning("Corrupt JSON in session %s message %s, falling back to []", session_id, msg_id)`.

- [x] **14. Unbounded subprocess output collection can exhaust memory**
  `src/gateway/run.py` ~3000-3002. `proc.communicate()` with no size limit buffers all stdout/stderr in memory. A runaway command printing gigabytes of output will OOM the gateway process. Add a `MAX_OUTPUT_BYTES = 10 * 1024 * 1024` cap via streaming read with a byte counter, truncating with a notice if exceeded.

- [x] **15. Circular dependency risk: cron imports shared logic from `tools`**
  `src/cron/scheduler.py` ~114, 124. `_parse_target_ref()` is imported from `src/tools/send_message_tool.py` and `resolve_channel_name()` is imported lazily inside an except handler. If `tools` ever imports `cron` (e.g. a scheduling tool), Python will hit a circular import. Move the shared parsing helpers to `src/core/channel_utils.py` and import from there.

- [x] **16. 13+ raw `os.getenv()` calls scattered through `run_job()`**
  `src/cron/scheduler.py` ~626, 645, 707 (and more). Makes testing require patching individual env vars and makes it easy to miss a variable when renaming. Create a `@dataclass class JobRunEnv` at the top of `run_job()` that reads all relevant env vars once, then pass it to sub-functions.

- [x] **17. PIL `Image.open()` handle not guaranteed to close on exception**
  `src/tools/vision_tools.py` ~342. If any processing step raises after `Image.open(path)`, the file handle leaks. Change to `with Image.open(path) as img:` and restructure downstream operations to work within the context.

- [x] **18. asyncio event loop created but not set in main-thread helper**
  `src/core/model_tools.py` ~55. `_get_tool_loop()` creates a new event loop for the main thread but never calls `asyncio.set_event_loop(loop)`, unlike the analogous `_get_worker_loop()` at ~76. Code that calls `asyncio.get_event_loop()` from the main thread will get a different loop, causing subtle async context failures. Add `asyncio.set_event_loop(loop)` immediately after creation.

---

### LOW

- [x] **19. Magic numbers in cron — should be named constants**
  `src/cron/scheduler.py` + `src/cron/jobs.py`. Values `120` (default script timeout), `7200` (max grace seconds), `5.0` (poll interval) appear inline with no explanation. Define `DEFAULT_SCRIPT_TIMEOUT_SECS = 120`, `MAX_GRACE_SECS = 7200`, `SCHEDULER_POLL_INTERVAL_SECS = 5.0` at module level.

- [x] **20. `_SCRIPT_TIMEOUT` monkeypatching is brittle for testing**
  `src/cron/scheduler.py` ~369-370. Tests override a module-level mutable variable to inject a timeout value. Replace with a `timeout: int | None = None` parameter on the relevant function; callers that omit it get the default constant.

- [x] **21. Mixed `Optional[T]` vs `T | None` type hint styles**
  Codebase-wide. `Optional[dict]` and `dict | None` are used interchangeably; `typing.List` and `list[str]` coexist. Since the project targets Python 3.11, standardize on built-in generics (`list[str]`, `dict[str, Any]`, `T | None`) and remove unused `from typing import Optional, List, Dict`.

- [x] **22. `webbrowser.open()` return value ignored**
  `src/tools/mcp_oauth.py` ~301. `webbrowser.open()` returns `False` if no browser is available (headless server, no DISPLAY). The tool currently proceeds silently and the user gets no feedback. Check the return value and if `False`, log a warning and include the URL in the response so the user can open it manually.

- [x] **23. Unreachable dead code in `spark_state.py`**
  `src/core/spark_state.py` ~269. The branch `else row[0]` after `isinstance(row, sqlite3.Row)` is never reached because `row_factory = sqlite3.Row` is unconditionally set at connection creation time. Remove the dead branch.

- [x] **24. Unused cursor variable** *(already fixed)*
  `src/core/spark_state.py` ~254. `cursor = self._conn.cursor()` is assigned but the very next lines call `self._conn.execute()` directly, bypassing the cursor. Remove the unused assignment.

- [x] **25. No tests for the cron subsystem**
  `tests/`. `src/cron/scheduler.py` and `src/cron/jobs.py` run unattended and have zero dedicated test coverage. Add `tests/test_cron_jobs.py` (schedule parsing, DST transitions, grace period calculation, job normalization) and `tests/test_cron_scheduler.py` (delivery routing, timeout logic, error state propagation).

- [x] **26. Error messages expose full internal filesystem paths**
  `src/cron/scheduler.py` ~437-443. Script path validation error messages include the fully-resolved filesystem path, leaking the host directory structure to users. Replace with the path relative to `SPARK_HOME/scripts/`.

- [x] **27. Browser tool FD pair not cleaned up if `Popen` raises**
  `src/tools/browser_tool.py` ~1090-1102. File descriptors from `os.open()` are assigned inside the try block, so if `Popen` raises before both assignments complete, the finally clause can't close the unassigned fds. Move fd assignments before the try block and use a single `try/finally` that unconditionally closes them.

- [x] **28. TODO/FIXME comment debt** *(triaged: 2 remaining are legitimate pending-work notes, not stale noise)*
  Grep the entire repo for `TODO|FIXME|HACK|XXX` and triage: close resolved ones, file issues for real ones, and delete stale noise comments.

---

## FEATURE LIST

- [x] **F1. Drag-and-drop file upload in chat and workspace thread UIs**
  Currently `PromptBar.tsx` (lines 99-120) only supports file upload via a hidden `<input type="file">` triggered by the Plus button. Add `dragenter`, `dragover`, `dragleave`, and `drop` event listeners to `ChatPanel.tsx` that activate a full-panel dropzone overlay (translucent backdrop + centered "Drop files to attach" label with a file icon) when the user drags files over the chat area. On drop, call the same `onUploadFiles` path already used by the Plus button. Apply the same pattern to the `WorkspacePage.tsx` new-thread input area. No backend changes needed — the existing `api.uploadFile()` path handles the upload.

- [x] **F2. Skeleton UI and page-level loading states**
  Replace all spinner-only loading states with animated skeleton placeholders that match the shape of the real content. Add a base `Skeleton.tsx` component (`animate-pulse` gray rectangles, composable). Apply to: `ChatPanel.tsx` history loading (lines 727) → message-row skeletons; `CronPage.tsx` job list loading (line 119) → card-shaped skeletons; `ConversationsPage.tsx` → session list row skeletons; `WorkspacePage.tsx` thread list and file tree loading → row skeletons. No backend changes needed; pure frontend.

- [x] **F3. Friendly cron scheduler — replace raw expression input with guided pickers**
  `CronPage.tsx` currently shows a raw cron expression text input (line 162-167, placeholder `"0 9 * * *"`). Replace with two fields: **Frequency** (a `<Select>` with options: Every Hour, Every Day, Every Week, Every Month, Every Year, Custom) and **Trigger Time** (a time picker `<input type="time">` for daily/weekly/monthly, a day-of-week selector for weekly, a day-of-month + month selector for annual). When "Custom" is chosen, show the raw cron input as a fallback. Add a client-side `cronToFriendly(expr)` / `friendlyToCron(freq, time, day)` utility. The gateway API and `src/cron/jobs.py` already store cron expressions — the conversion is frontend-only.

- [ ] **F4. Voice mode — animated call UI with local-first TTS/STT and hardware detection**

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
  - Call the appropriate `_generate_<provider>_tts()` function from `tts_tool.py`, write to a NamedTemporaryFile, then stream the file as `audio/mpeg` (MP3) or `audio/wav` using `FileResponse` or a `StreamingResponse` that reads and deletes the temp file after streaming.
  - ElevenLabs streaming path (already returns a generator in `tts_tool.py` around line 244) should be streamed directly without buffering to disk if possible.
  - Supertonic produces WAV output from `soundfile.write()`; serve as `audio/wav`. All other providers produce MP3/OGG — detect by inspecting the output file extension.
  - Return a proper `Content-Type` header so the browser `<audio>` element can auto-play without codec detection.

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

  #### 5. No hardware-detection backend needed

  The original plan mentioned a `src/core/voice_config.py` with GPU/CPU detection for Chatterbox-Turbo and Kokoro. Neither library is currently in `tts_tool.py` — adding them would require new optional dependencies (`pip install chatterbox-tts`, `pip install kokoro-onnx`) and significant integration work. **Skip the hardware-detection piece for now.** Supertonic-3 handles its own device auto-selection. The existing provider auto-selection in `transcription_tools.py` (faster-whisper if installed, else OpenAI) is sufficient. The Settings panel will show users what's active.

  #### 6. Browser compatibility note

  `MediaRecorder` with `audio/webm;codecs=opus` works in Chrome/Edge/Firefox. Safari requires `audio/mp4` (AAC). Check `MediaRecorder.isTypeSupported()` and fall back to `audio/mp4` on Safari. The backend should handle both via ffmpeg or soundfile for format conversion if needed (faster-whisper accepts WAV/MP3/WebM natively via ffmpeg).

  #### Suggested build order

  1. Add `_generate_supertonic_tts()` to `tts_tool.py` + config defaults (30 min).
  2. `GET /api/voice/capabilities` endpoint (5 min — calls existing `check_voice_requirements()` + adds provider fields).
  3. `POST /api/voice/transcribe` endpoint (30 min).
  4. `GET /api/voice/tts` endpoint (45 min — wires existing `_generate_*` functions, handles WAV vs MP3 content-type).
  5. `VoiceCallModal.tsx` without waveforms (transcript + basic record/playback loop) (2h).
  6. Add waveform visualizers (1h).
  7. Wire mic button into `PromptBar.tsx` + `ChatPanel.tsx` (15 min).
  8. Settings panel Voice section with Supertonic provider label (30 min).
  9. Test on Chrome + Safari, handle codec fallback.

- [x] **F5. Global command palette (Cmd+K)**
  Add a `CommandPalette.tsx` modal component triggered by `Cmd+K` (or `Ctrl+K`). It provides a fuzzy-searchable list of: page navigation (all pages in `App.tsx`), recent sessions (from the existing sessions API), slash commands (from `src/spark_cli/web/src/i18n/en.ts`), and workspace actions (new thread, upload file). Selecting an item navigates or dispatches the action. Register a global `keydown` listener in `App.tsx`. No backend changes needed — all data sources are already available to the frontend.

- [x] **F6. Session export (Markdown, JSON, PDF)**
  Add an export button to the conversation detail view (`ConversationsPage.tsx` / `ChatPanel.tsx`). Options: **Markdown** (renders messages as `## User` / `## Assistant` blocks with tool call details), **JSON** (raw session data), **PDF** (browser `window.print()` with a print-specific CSS stylesheet). Markdown and JSON are generated client-side from the already-loaded message array. PDF uses the browser print dialog with `@media print` styles that hide sidebar and controls. No backend changes needed for Markdown/JSON/PDF. Optionally add a `GET /api/sessions/{id}/export?format=md` gateway endpoint for server-side rendering if the session is too large for in-browser export.

- [x] **F7. Inline image and file preview in chat messages**
  When tool calls in `ToolCallBubble.tsx` or assistant messages return a file path or URL (image, audio, video, PDF, code file), detect the file type and render it inline rather than showing just a raw path string. Images: `<img>` with max-height cap and click-to-fullscreen. Audio: HTML5 `<audio controls>`. Code files: syntax-highlighted code block using the existing `highlight.js` integration already in `WorkspacePage.tsx`. PDF: `<iframe>` embed or download link. Add a `detectOutputType(value: string)` utility and update `ToolCallBubble.tsx` and the assistant message renderer to use it.

- [x] **F8. In-session message search**
  Add a search bar to `ChatPanel.tsx` that appears on `Cmd+F` (or a search icon button in the chat header). As the user types, highlight all matching text spans in the rendered message list and show a `3 / 12` match counter with up/down arrows to jump between matches. Implement with a `searchQuery` state in `ChatPanel.tsx`, a `useMemo` that builds a list of match positions from the flattened message content, and a `useEffect` that scrolls the active match into view. No backend changes needed — searches the already-loaded message array.

- [x] **F9. Notification system for async job completions**
  When a cron job or long-running task finishes, surface the result via: (1) an in-app notification bell icon in the top nav bar that opens a dropdown of recent events (job name, status, timestamp, truncated output) — powered by a new SSE stream `GET /api/notifications/stream` in `src/gateway/run.py` that the scheduler pushes to after each `run_job()` completes; (2) a browser `Notification` (Web Notifications API) if the user has granted permission. The notification store is a small in-memory queue in the gateway process; events are not persisted between restarts. Add a `NotificationBell.tsx` component to the `App.tsx` header.

- [x] **F10. Workspace file diff viewer**
  In `WorkspacePage.tsx`, when the agent modifies a file (detected via the existing file-change events), show a **Diff** tab alongside the current file view. Use a lightweight JS diff library (e.g. `diff` npm package, already common) to compute a unified diff between the pre-change snapshot (stored in a `Map<path, string>` at the time the session opens) and the current content. Render with syntax-colored `+`/`-` line prefixes. Add a "Diff" tab button to the file viewer toolbar (lines 262-334 in `WorkspacePage.tsx`). No backend changes needed — the frontend already fetches file content via `api.getWorkspaceFile()`.

- [x] **F11. Keyboard shortcuts reference overlay**
  Add a `KeyboardShortcutsModal.tsx` that opens when the user presses `?` (outside an input field). Lists all keyboard shortcuts organized by context (Global, Chat, Workspace, Editor). Shortcuts are defined in a static `SHORTCUTS` constant in the component. Add a "Keyboard shortcuts" entry to the settings panel or help menu so it's also discoverable without knowing the key. No backend changes needed.

- [x] **F12. Session branching / fork-from-message UI**
  `ChatPanel.tsx` already has a "Fork" action on user messages (line ~141-156) that calls the backend fork API. Currently the forked session opens as a new conversation with no visual link back to the parent. Improve this by: (1) showing a `↩ Forked from [Session Name]` badge at the top of the new session's chat header; (2) adding a "Branches" indicator on the original session's message row showing how many forks exist (via a `GET /api/sessions/{id}/forks` count endpoint added to `src/gateway/run.py`); (3) in `ConversationsPage.tsx`, group forked sessions visually under their parent with an indented tree layout. Backend: add a `parent_session_id` query to `src/core/spark_state.py` `get_session_forks(session_id)`.
