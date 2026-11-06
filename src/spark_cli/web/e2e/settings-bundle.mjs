// Compare actual production App graphs built with the same toolchain.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { gzipSync } from "node:zlib";
function graph(root, source) {
  const manifest = JSON.parse(readFileSync(path.join(root, ".vite/manifest.json")));
  const start = source ? Object.keys(manifest).find((key) => key.endsWith(source) || (source.endsWith("SettingsPanel.tsx") && manifest[key].name === "SettingsPanel")) : Object.keys(manifest).find((key) => manifest[key].isEntry);
  assert(start, source);
  const keys = new Set();
  function visit(key) { if (keys.has(key)) return; keys.add(key); for (const dep of manifest[key].imports || []) visit(dep); }
  visit(start);
  const js = [...keys].filter((key) => manifest[key].file.endsWith(".js"));
  return { keys: [...keys], bytes: js.reduce((n, key) => n + gzipSync(readFileSync(path.join(root, manifest[key].file))).length, 0) };
}
const [baseline, candidate] = process.argv.slice(2);
const result = { baseline: { chat: graph(baseline), settings: graph(baseline, "src/components/SettingsPanel.tsx") }, candidate: { chat: graph(candidate), settings: graph(candidate, "src/components/SettingsPanel.tsx") } };
console.log(JSON.stringify(result, null, 2));
assert(result.candidate.chat.bytes <= result.baseline.chat.bytes, "Initial Chat gzip graph must not grow");
assert(result.candidate.settings.bytes < result.baseline.settings.bytes, "Model Settings gzip graph must shrink");
assert(!result.candidate.settings.keys.some((key) => /(?:Analytics|Logs|Admin)Page/.test(key)), "Secondary feature modules must be deferred");

