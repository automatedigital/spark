# Tasks

## Mid-Prompt @ Mentions & /Slash Commands

### Task 1 — Detect `/` mid-prompt to trigger slash menu
File: `src/spark_cli/web/src/components/chat/PromptBar.tsx`

Add two new state variables alongside the existing `showMenu`/`showAtMenu`:
```ts
const [slashTokenStart, setSlashTokenStart] = useState<number>(-1);
const [slashQuery, setSlashQuery] = useState("");
```

In `handleChange()`, replace:
```ts
setShowMenu(val.startsWith("/"));
```
with:
```ts
const slashMatch = /(^|\s)(\/\S*)$/.exec(beforeCursor);
if (slashMatch) {
  const token = slashMatch[2]; // the "/word" part
  setSlashQuery(token.slice(1)); // strip leading /
  setSlashTokenStart(cursor - token.length);
  setShowMenu(true);
} else {
  setShowMenu(false);
  setSlashTokenStart(-1);
  setSlashQuery("");
}
```

Pass `slashQuery` (not `input.slice(1)`) to `<SlashCommandMenu query={slashQuery} />`.

- [x] Done

---

### Task 2 — Fix slash select to replace token in-place
File: `src/spark_cli/web/src/components/chat/PromptBar.tsx`

Replace the body of `handleSlashSelect()`:
```ts
const handleSlashSelect = (command: string) => {
  const textarea = textareaRef.current;
  const insertToken = `/${command} `;
  if (slashTokenStart >= 0) {
    // find end of the /token at cursor — use current input length from slashTokenStart
    const tokenEnd = slashTokenStart + 1 + slashQuery.length;
    const newInput = input.slice(0, slashTokenStart) + insertToken + input.slice(tokenEnd);
    setInput(newInput);
    setTimeout(() => {
      const pos = slashTokenStart + insertToken.length;
      if (textarea) { textarea.selectionStart = textarea.selectionEnd = pos; textarea.focus(); }
    }, 0);
  } else {
    setInput(insertToken);
    setTimeout(() => textarea?.focus(), 0);
  }
  setShowMenu(false);
  setMenuHasItems(false);
  setSlashTokenStart(-1);
  setSlashQuery("");
};
```

- [x] Done

---

### Task 3 — AtFileMenu: Enter key selects (same as Tab)
File: `src/spark_cli/web/src/components/chat/AtFileMenu.tsx`

In the keyboard handler `useEffect`, change:
```ts
} else if (e.key === "Tab") {
  e.preventDefault();
  const entry = filtered[activeIdx];
  if (entry) onSelect(entry.path, entry.type === "dir");
}
```
to:
```ts
} else if (e.key === "Tab" || e.key === "Enter") {
  e.preventDefault();
  const entry = filtered[activeIdx];
  if (entry) onSelect(entry.path, entry.type === "dir");
}
```

- [x] Done

---

### Task 4 — Fix mirror highlighting: bold accent for both `@mentions` and `/commands` mid-prompt
File: `src/spark_cli/web/src/components/chat/PromptBar.tsx`

Replace the `TOKEN_RE` and `renderMirror` function.

Current regex only matches `/command` at start of line (`^\/\S+`). Replace with one that matches after start-of-string or whitespace using a two-group approach (to avoid consuming the leading space):

```ts
// matches @token or /token at start or after a space
const AT_RE = /(@\S+)/g;
const SLASH_RE = /((?:^|(?<=[ \t]))\/\S+)/gm;

function renderMirror(text: string): React.ReactNode[] {
  // Build a sorted list of all token ranges to highlight
  type Range = { start: number; end: number; text: string };
  const ranges: Range[] = [];

  let m: RegExpExecArray | null;
  AT_RE.lastIndex = 0;
  while ((m = AT_RE.exec(text)) !== null) {
    ranges.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  SLASH_RE.lastIndex = 0;
  while ((m = SLASH_RE.exec(text)) !== null) {
    ranges.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  ranges.sort((a, b) => a.start - b.start);

  const nodes: React.ReactNode[] = [];
  let last = 0;
  for (const r of ranges) {
    if (r.start > last) nodes.push(text.slice(last, r.start));
    nodes.push(
      <mark key={r.start} className="bg-transparent text-primary font-bold not-italic">
        {r.text}
      </mark>
    );
    last = r.end;
  }
  if (last < text.length) nodes.push(text.slice(last));
  nodes.push(" ");
  return nodes;
}
```

Note: `(?<=[ \t])` lookbehind is supported in Chrome/Safari/Firefox modern versions. If TypeScript complains about the regex, cast it: `new RegExp('((?:^|(?<=[ \\t]))\\/\\S+)', 'gm')`.

- [x] Done

---

### Task 5 — Verify Enter-while-popup-open blocks send
File: `src/spark_cli/web/src/components/chat/PromptBar.tsx`

Check `handleKeyDown`. The existing guard is:
```ts
if (showMenu || showAtMenu) {
  if (["ArrowUp", "ArrowDown", "Escape"].includes(e.key)) return;
  if (e.key === "Tab") return;
  if (e.key === "Enter" && !e.shiftKey && menuHasItems) return;
}
```

This correctly blocks Enter from sending when a menu is open with items. No change needed — just verify this logic is intact after edits to Tasks 1–4.

- [x] Verified (no change needed)

---

### Task 6 — Build the webui
```bash
cd src/spark_cli/web && npm run build
```
Build must complete with no errors. TypeScript type errors must be fixed before proceeding.

- [x] Done

---

### Task 7 — Test with Chrome MCP

Start the Spark web server if not running (`spark` or check `nova:9119`). Use Chrome MCP to open `http://nova:9119` and run the following tests. Mark each sub-item done as it passes.

**Test A — slash command mid-prompt**
- [x] Click into the prompt bar
- [x] Type `hello /com` — slash command popup appears showing commands matching "com" (e.g. `/compress`, `/comfy`)
- [x] Press `ArrowDown` to move to second item, then `Tab` — item is inserted mid-prompt, e.g. `hello /compress `, popup closes, prompt is NOT sent
- [x] Clear input, type `hello /com`, press `Enter` — item is inserted, popup closes, prompt is NOT sent
- [x] Press `Enter` again — prompt is sent

**Test B — @ file mention mid-prompt**
- [x] Type `summarise @` — file popup appears
- [x] Press `ArrowDown`, then `Tab` — file inserted mid-prompt, popup closes, not sent
- [x] Clear, type `summarise @`, press `Enter` — file inserted, popup closes, not sent
- [x] Press `Enter` again — prompt is sent

**Test C — accent highlighting**
- [x] Type `@somefile /compress more text` — both `@somefile` and `/compress` are rendered **bold primary-colour** in the prompt bar mirror; plain text is unaffected

**Test D — slash at start of prompt still works**
- [x] Clear input, type `/dream` — slash popup opens as before
- [x] `Enter` or `Tab` selects, second `Enter` sends

**Test E — Escape closes popup without sending**
- [x] Type `/co` — popup opens
- [x] Press `Escape` — popup closes, text remains, nothing sent
