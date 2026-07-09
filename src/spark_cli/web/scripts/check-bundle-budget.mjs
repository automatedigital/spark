import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { resolve } from "node:path";

const distDir = resolve(process.cwd(), "../web_dist");
const manifestPath = resolve(distDir, ".vite/manifest.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const initialBudgetBytes = 600 * 1024;

const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry);
if (!entryKey) throw new Error("Bundle budget: production manifest has no entry chunk.");

const initialKeys = new Set();
function addStaticImports(key) {
  if (initialKeys.has(key)) return;
  initialKeys.add(key);
  for (const importedKey of manifest[key]?.imports ?? []) addStaticImports(importedKey);
}
addStaticImports(entryKey);

const initialAssets = [...initialKeys]
  .map((key) => manifest[key]?.file)
  .filter((file) => file?.endsWith(".js"));
const rows = initialAssets.map((file) => {
  const source = readFileSync(resolve(distDir, file));
  return { file, bytes: source.length, gzipBytes: gzipSync(source).length };
});
const initialGzipBytes = rows.reduce((total, row) => total + row.gzipBytes, 0);

const requiredDeferredSources = [
  "src/pages/CanvasPage.tsx",
  "src/pages/FilesPage.tsx",
  "src/components/files/CodeEditor.tsx",
  "src/components/workspace/WorkspaceTerminalPanel.tsx",
  "src/components/SettingsPanel.tsx",
  "src/components/OnboardingWizard.tsx",
  "src/components/CommandPalette.tsx",
];
for (const source of requiredDeferredSources) {
  const key = Object.keys(manifest).find((candidate) => candidate.endsWith(source));
  if (!key) throw new Error(`Bundle budget: expected deferred module is missing: ${source}`);
  if (initialKeys.has(key)) throw new Error(`Bundle budget: deferred module leaked into startup: ${source}`);
  if (!manifest[key].isDynamicEntry) {
    throw new Error(`Bundle budget: expected a dynamic entry for ${source}`);
  }
}

const forbiddenInitialChunkNames = new Set([
  "feature-canvas",
  "feature-editor-core",
  "feature-terminal",
]);
for (const key of initialKeys) {
  const name = manifest[key]?.name;
  if (forbiddenInitialChunkNames.has(name)) {
    throw new Error(`Bundle budget: ${name} is reachable from the startup entry.`);
  }
}

console.log("Initial JavaScript bundle report (static entry graph):");
for (const row of rows) {
  console.log(
    `  ${row.file}: ${(row.bytes / 1024).toFixed(2)} KiB minified / ${(row.gzipBytes / 1024).toFixed(2)} KiB gzip`,
  );
}
console.log(
  `  Total: ${(initialGzipBytes / 1024).toFixed(2)} KiB gzip (budget ${(initialBudgetBytes / 1024).toFixed(0)} KiB)`,
);

if (initialGzipBytes > initialBudgetBytes) {
  throw new Error(
    `Initial JavaScript exceeds budget by ${((initialGzipBytes - initialBudgetBytes) / 1024).toFixed(2)} KiB.`,
  );
}
