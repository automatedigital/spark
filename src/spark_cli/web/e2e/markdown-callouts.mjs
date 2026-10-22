// Run with a Vite dev server: CALLOUT_BASE_URL=http://127.0.0.1:5196 node e2e/markdown-callouts.mjs
// No backend, credentials, provider calls or profile state are needed.
import assert from "node:assert/strict";
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1000, height: 1300 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(`${process.env.CALLOUT_BASE_URL || "http://127.0.0.1:5196"}/e2e/markdown-callouts.html`);
  const response = page.getByRole("region", { name: "Rendered response" });
  for (const label of ["Note", "Tip", "Important", "Warning", "Caution"]) {
    await page.getByRole("note", { name: label, exact: true }).waitFor();
  }
  assert.equal(await response.locator("blockquote").count(), 2);
  assert.match(await response.locator("pre").innerText(), /\[!WARNING\]/);
  assert.match(await response.ariaSnapshot(), /note "Warning"/);
  const firstHelp = page.getByRole("note", { name: "Note", exact: true }).getByRole("link", { name: "Help" });
  await firstHelp.focus();
  await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => document.activeElement?.closest('[role="note"]')?.getAttribute("aria-labelledby")), await page.getByRole("note", { name: "Tip", exact: true }).getAttribute("aria-labelledby"));
  const popupPromise = page.waitForEvent("popup");
  await page.keyboard.press("Enter");
  const popup = await popupPromise;
  await popup.waitForLoadState();
  assert.equal(new URL(popup.url()).hash, "#help");
  await popup.close();

  const contrasts = {};
  for (const theme of ["codex", "spark", "daylight", "signal", "aurora", "ember", "orchid", "harbor"]) {
    await page.getByLabel("Theme", { exact: true }).selectOption(theme);
    contrasts[theme] = await response.locator('[role="note"]').evaluateAll((notes) => {
      const luminance = (color) => {
        const channels = color.match(/[\d.]+/g).slice(0, 3).map(Number).map((n) => n / 255).map((n) => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4);
        return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
      };
      return notes.map((note) => {
        const style = getComputedStyle(note);
        const fg = luminance(style.color), bg = luminance(style.backgroundColor);
        return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
      });
    });
    assert.ok(contrasts[theme].every((ratio) => ratio >= 4.5), `${theme}: contrast ${contrasts[theme]}`);
  }

  await page.getByLabel("Streaming", { exact: true }).check();
  const input = page.getByRole("textbox", { name: "Markdown source" });
  await input.fill("> [!WAR");
  assert.equal(await response.getByRole("note").count(), 0);
  await input.fill("> [!WARNING]\n> First\n>\n> - second\n> > nested");
  await response.getByRole("note", { name: "Warning" }).waitFor();
  assert.equal(await response.locator("li").innerText(), "second");
  assert.equal(await response.locator("blockquote").innerText(), "nested");
  await page.getByLabel("Streaming", { exact: true }).uncheck();
  await page.getByLabel("Safe mode", { exact: true }).check();
  assert.equal(await response.getByRole("note").count(), 0);
  assert.match(await response.innerText(), /\[!WARNING\]/);
  await page.getByLabel("Safe mode", { exact: true }).uncheck();
  await response.getByRole("note", { name: "Warning" }).waitFor();
  await page.screenshot({ path: process.env.CALLOUT_SCREENSHOT || "/tmp/f06-callouts.png", fullPage: true });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ passed: true, checks: ["five named notes", "ordinary/unknown quotes", "literal fence", "accessibility tree", "Tab/Enter link", "eight theme contrasts >= 4.5", "stream split and completion", "safe mode"], contrasts, errors }, null, 2));
} finally {
  await browser.close();
}
