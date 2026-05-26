# PromptBar & UI Refinement Plan

Inspired by Claude Code and Cursor's prompt bar designs: a unified input card with an inner toolbar row showing model name, reasoning level, and quick-access controls.

---

## 1. Visual Redesign — Unified Input Card

**Goal:** Replace the flat border-only input with a self-contained card (like Cursor's design): large border-radius, inner padding, with the textarea at top and a toolbar row at the bottom inside the same card.

- [ ] Wrap textarea + bottom toolbar in a single `rounded-xl border bg-card` container
- [ ] Remove the current outer flex layout (Plus button left, textarea middle, Send button right)
- [ ] Add a dedicated bottom toolbar row inside the card (left: controls, right: send button)
- [ ] Move the `+` (attach) button into the bottom toolbar row
- [ ] Move the `Send` / `Stop` button to the bottom-right of the inner toolbar
- [ ] Update placeholder text to: `"Ask anything · / for commands · @ for context"`
- [ ] Add subtle `focus-within` ring on the outer card (not on the textarea itself)
- [ ] Increase vertical padding on the textarea for a roomier feel

---

## 2. Model + Reasoning Display in Toolbar

**Goal:** Show `{model} · {reasoning}` in the bottom toolbar (like Claude Code's `Sonnet 4.6 · Medium`). Both are clickable to change inline.

### 2a. Model display (read-only first)
- [ ] Call `api.getModelInfo()` on mount (already exists: `GET /api/model/info`)
- [ ] Display short model name in toolbar: strip provider prefix, e.g. `claude-sonnet-4-6` → `Sonnet 4.6`
- [ ] Show a dim provider label or icon alongside (optional, can skip initially)

### 2b. Reasoning level display + toggle
- [ ] Read `agent.reasoning_effort` from `GET /api/config` on mount
- [ ] Display as `· Low` / `· Medium` / `· High` next to the model name (omit if `none`/`minimal`)
- [ ] Clicking the reasoning label cycles through `none → low → medium → high → none`
- [ ] On change: `PUT /api/config` with updated `agent.reasoning_effort`, show brief confirmation
- [ ] Valid values: `none`, `minimal`, `low`, `medium`, `high`, `xhigh` (from `VALID_REASONING_EFFORTS`)
- [ ] Only show reasoning toggle when `capabilities.supports_reasoning === true` from model info

### 2c. Model switcher (follow-up)
- [ ] Clicking the model name opens a popover to switch models (reuses `conversationModels` or `PUT /api/config`)

---

## 3. Keyboard Shortcut Hint

**Goal:** Small hint text near the send button showing `⏎` to send, `⇧⏎` for newline — disappears once the user has sent a message.

- [ ] Add `⏎ Send` hint in the bottom-right of the toolbar (small, muted)
- [ ] Store a `hasEverSent` flag in `localStorage` and hide the hint permanently after first send
- [ ] On mobile / touch devices, omit the hint

---

## 4. Context / Attachment Chips

**Goal:** When files are attached or a workspace is active, show compact chips above the textarea inside the card.

- [ ] When `workspaceSlug` is set, show a `@{slug}` context chip inside the card (top of card, above textarea)
- [ ] When files are uploading/uploaded, show filename chips with remove buttons
- [ ] Chips sit in a flex-wrap row; card height adjusts naturally

---

## 5. Send Button Polish

- [ ] Replace `size="icon"` with a pill-shaped send button (`rounded-full px-3 py-1.5 h-8`) matching Cursor style
- [ ] Show `↑` arrow icon instead of the `Send` icon (more modern)
- [ ] Disabled state: button is semi-transparent, no hover effect
- [ ] Stop button: keep destructive red, same pill shape

---

## 6. Backend: Expose Reasoning Effort via Dedicated Endpoint

**Goal:** Avoid fetching the full config just to read/write reasoning effort.

- [ ] Add `GET /api/model/reasoning` → returns `{ effort: string, supported: bool }`
- [ ] Add `PUT /api/model/reasoning` → accepts `{ effort: string }`, saves to config, returns updated value
- [ ] Wire frontend to these endpoints instead of the heavyweight `GET/PUT /api/config`

---

## 7. General UI Polish

- [ ] **Sidebar thread rows**: tighten line-height, add hover background that matches the card design language
- [ ] **Thread header**: add the current model badge to the chat thread header (top bar) so it's visible without looking at the prompt bar
- [ ] **New chat empty state**: update the empty-state illustration/copy to be more actionable
- [ ] **Mobile**: ensure the new bottom toolbar stacks gracefully at narrow widths (model label truncates, hint hidden)

---

## Implementation Order

1. Task 1 (visual redesign) — pure frontend, no backend needed, highest visual impact
2. Task 2a + 2b (model + reasoning display) — uses existing APIs
3. Task 3 (keyboard hint) — tiny, quick win
4. Task 5 (send button polish) — goes hand-in-hand with Task 1
5. Task 4 (context chips) — moderate effort, depends on Task 1 layout
6. Task 6 (backend endpoints) — clean up after 2a/2b are working
7. Task 7 (general polish) — last pass
