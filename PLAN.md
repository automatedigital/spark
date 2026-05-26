# PromptBar & UI Refinement Plan

Inspired by Claude Code and Cursor's prompt bar designs: a unified input card with an inner toolbar row showing model name, reasoning level, and quick-access controls.

---

## 1. Visual Redesign — Unified Input Card ✅

- [x] Wrap textarea + bottom toolbar in a single `rounded-xl border bg-card` container
- [x] Remove the current outer flex layout (Plus button left, textarea middle, Send button right)
- [x] Add a dedicated bottom toolbar row inside the card (left: controls, right: send button)
- [x] Move the `+` (attach) button into the bottom toolbar row
- [x] Move the `Send` / `Stop` button to the bottom-right of the inner toolbar
- [x] Update placeholder text to: `"Ask anything · / for commands · @ for context"`
- [x] Add subtle `focus-within` ring on the outer card (not on the textarea itself)
- [x] Increase vertical padding on the textarea for a roomier feel

---

## 2. Model + Reasoning Display in Toolbar ✅

### 2a. Model display
- [x] Call `api.getModelInfo()` on mount
- [x] Display short model name in toolbar: `claude-sonnet-4-6` → `Sonnet 4.6`

### 2b. Reasoning level display + toggle
- [x] Read reasoning effort from `GET /api/model/reasoning`
- [x] Display as `· Low` / `· Medium` / `· High` next to model name (omit if `none`)
- [x] Clicking cycles through `none → low → medium → high → none`
- [x] On change: `PUT /api/model/reasoning` saves to config
- [x] Only show when `supports_reasoning === true`

### 2c. Model switcher ✅
- [x] Clicking the model name opens a quick-settings popover
- [x] Smart model dropdown (provider-aware suggestions from `GET /api/model/suggestions`)
- [x] Fast model dropdown shown when multi-model routing is enabled
- [x] Changes save immediately via `PUT /api/model/smart` and `PUT /api/model/fast`
- [x] Multi-model status read from `GET /api/model/status` (single call for all state)

---

## 3. Keyboard Shortcut Hint ✅

- [x] `⏎ to send` hint in bottom-right toolbar (small, muted)
- [x] Hidden permanently after first send via `localStorage`
- [x] Hidden on mobile (`hidden sm:flex`)

---

## 4. Context / Attachment Chips (future)

- [ ] When `workspaceSlug` is set, show a `@{slug}` context chip inside the card
- [ ] When files are uploading/uploaded, show filename chips with remove buttons

---

## 5. Send Button Polish ✅

- [x] Rounded-full send button matching Cursor style
- [x] `↑` arrow icon instead of `Send` icon
- [x] Disabled state: `opacity-30`, no pointer events
- [x] Stop button: destructive red, same rounded-full shape

---

## 6. Backend: Reasoning Effort Endpoints ✅

- [x] `GET /api/model/reasoning` → `{ effort, supported }`
- [x] `PUT /api/model/reasoning` → save to config, return updated value
- [x] `ReasoningEffortResponse` type added to API client

---

## 7. General UI Polish ✅

- [x] **Thread header**: `ModelBadge` component shows current model + reasoning level
- [x] **New chat empty state**: smaller icon, tighter copy, actionable "+ New chat" button
- [x] **Mobile**: hint hidden on small screens, model label uses `hidden md:flex`
