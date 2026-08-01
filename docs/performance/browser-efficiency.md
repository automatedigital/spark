# Web-state browser efficiency acceptance

Verified on 2026-08-01 at `27a94d5f` with Playwright 1.62 and Chromium 151
against isolated source-mode sidecar and Vite processes. The run used scripted,
provider-free streams through Spark's production chat event pipeline.

## Flows exercised

- Loaded a long saved conversation containing a roughly 140,000-character tool
  result, selected it, and verified its bounded visible transcript.
- Rendered and captured the same selected detail at 390, 820, and 1440 px.
- Started two simultaneous chats, switched A to B to A while both generated,
  hard-refreshed during generation, and recovered the selected chat.
- Backgrounded and foregrounded the page after both turns settled.
- Stopped and restarted the backend, waited for the server instance ID to
  change, created another chat, and verified authoritative snapshot recovery.
- Confirmed the cold-document path hydrates a bounded snapshot even when
  `sessionStorage` retains a resume cursor. Compatibility fallback to the
  bounded legacy sessions endpoint was separately covered by Vitest and live
  browser fault injection.

## Results

| Viewport | Document scroll width | React commits through initial render and selection | Body characters |
| --- | ---: | ---: | ---: |
| 390 px | 390 px | 30 | 186 |
| 820 px | 820 px | 25 | 411 |
| 1440 px | 1440 px | 28 | 411 |

The 12-second settled healthy-stream window made no status, sessions, event,
snapshot, delta, turn-status, or stream-snapshot request. Its only API request
was the independent workspace preview server detector. There were no
application console errors, page errors, or non-2xx responses before the forced
outage. No selected or background session remained in the `Working` state.

The backend restart changed the server instance from
`0cdb744b177344e29944a8df408ee481` to
`16b268a36bba47a0acb7dea3980f5eb5`. The page recovered the new chat and showed
no stuck `Working` state. One preview-detector HTTP 500 and its Chromium resource
error occurred while the backend was intentionally offline; both were confined
to that outage and the next request recovered.

## Screenshots

- [390 px](browser-efficiency/web-state-390.png)
- [820 px](browser-efficiency/web-state-820.png)
- [1440 px](browser-efficiency/web-state-1440.png)
- [Backend restart recovery](browser-efficiency/web-state-reconnect.png)

## Automated checks

- Web-state and event backend suite: 108 passed.
- Full frontend suite from the compatibility/cold-start fix: 248 passed.
- ESLint and production Vite build passed; gzip bundle total was 197.15 KiB,
  below the 600 KiB budget.
