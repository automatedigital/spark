/** P09 diagnostic-only Vite transform. Never imported by product source. */
import assert from 'node:assert/strict';
import path from 'node:path';
import { realpath, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export function instrumentSearchScroll(code, id, behavior = 'original') {
  assert.ok(['original', 'instant'].includes(behavior));
  if (!id.endsWith('/components/ChatPanel.tsx')) return code;
  const original = code;
  const replace = (from, to) => {
    assert.equal(code.split(from).length, 2, `Expected one diagnostic seam: ${from.slice(0, 100)}`);
    code = code.replace(from, to);
  };
  // Label every source scroll writer by original line, retaining conditional
  // statement boundaries (including single-line if/else) and exact arguments.
  const writers = [];
  code = code.replace(/\b(?:element|el|scrollEl|currentTarget|target)\.scrollTop\s*(?:\+=|=)[\s\S]*?;|virtualizer\.scrollToIndex\([^;]+\);/g, (statement, offset) => {
    const line = original.slice(0, offset).split('\n').length;
    const label = `ChatPanel:${line}`;
    writers.push({ label, statement });
    return `__p09Write(${JSON.stringify(label)}, () => { ${statement} });`;
  });
  assert.equal(writers.length, 18, 'Review all source scroll writers if count changes');
  replace('    const idx = turnIndexForMessageIndex(searchMatches[searchMatchIdx % searchMatches.length]);', `    const idx = turnIndexForMessageIndex(searchMatches[searchMatchIdx % searchMatches.length]);
    __p09("search:intent", { messageIndex: searchMatches[searchMatchIdx % searchMatches.length], mappedIndex: idx, actualTurnId: timelineTurns[idx]?.id, requestedBehavior: safeMode ? "instant" : "smooth" });`);
  if (behavior === 'instant') {
    replace('virtualizer.scrollToIndex(idx, { align: "center", behavior: safeMode ? "instant" : "smooth" });', 'virtualizer.scrollToIndex(idx, { align: "center", behavior: "instant" });');
  }
  replace('  const measuredSessionRef = useRef<string | null>(null);', `${snapshotSource}\n  const measuredSessionRef = useRef<string | null>(null);`);
  replace('    prependRestoreGenerationRef.current += 1;\n    const transition = streamController.setSession({', `    prependRestoreGenerationRef.current += 1;
    __p09("session:reset", { resetSessionId, recoverySequence });
    const transition = streamController.setSession({`);
  replace('    followStreamRef.current = !savedScroll;', '    followStreamRef.current = !savedScroll;\n    __p09("session:scroll-state", { savedScroll });');
  replace('    const restoreGeneration = prependRestoreGenerationRef.current;', '    const restoreGeneration = prependRestoreGenerationRef.current;\n    __p09("bookmark:restore-start", { saved, restoreGeneration });');
  replace('      frame = requestAnimationFrame(() => {\n        if (restoreGeneration !== prependRestoreGenerationRef.current) return;', '      frame = requestAnimationFrame(() => {\n        __p09("bookmark:frame", { restoreGeneration, remaining });\n        if (restoreGeneration !== prependRestoreGenerationRef.current) return;');
  replace('    const measureRenderedRows = (entries?: ResizeObserverEntry[]) => {', '    const measureRenderedRows = (entries?: ResizeObserverEntry[]) => {\n      __p09("measurement:observer", { entries: entries?.length ?? null });');
  replace('        rowResizeRafRef.current = null;\n        const scrollEl', '        rowResizeRafRef.current = null;\n        __p09("measurement:frame", { pendingCount: pendingRows.size });\n        const scrollEl');
  replace('            virtualizer.resizeItem(index, row.getBoundingClientRect().height);', `            __p09("measurement:resize-before", { index, rowId: row.dataset.rowId, height: row.getBoundingClientRect().height });
            virtualizer.resizeItem(index, row.getBoundingClientRect().height);
            __p09("measurement:resize-after", { index, rowId: row.dataset.rowId });`);
  replace('      if (loadingHistory || restoringThreadScroll.current || activeSessionRef.current !== activeSessionId || scrollStateRef.current.mode === "jumping-to-bottom") return;', '      __p09("follow:scroll-event");\n      if (loadingHistory || restoringThreadScroll.current || activeSessionRef.current !== activeSessionId || scrollStateRef.current.mode === "jumping-to-bottom") return;');
  replace('    if (shouldFollow) {', '    __p09("autofollow:decision", { shouldFollow, countChanged, streaming });\n    if (shouldFollow) {');
  replace('    let firstFrame = true;', '    let firstFrame = true;\n    __p09("bottom-clamp:start");');
  replace('        if (!el || scrollStateRef.current.mode !== "jumping-to-bottom") return;', '        __p09("bottom-clamp:frame", { remaining, firstFrame });\n        if (!el || scrollStateRef.current.mode !== "jumping-to-bottom") return;');
  return { code, writers };
}

// JSON-only snapshots: never retain DOM nodes, callbacks, virtualizer, or turns
// in probe state. Read measurements only; do not force virtualizer.measure().
const snapshotSource = `
  function __p09(phase: string, extra: Record<string, unknown> = {}) {
    const probe = (globalThis as any).__sparkSearchProbe;
    if (!probe?.enabled) return;
    const element = scrollContainerRef.current;
    const viewport = element?.getBoundingClientRect();
    const targetId = "turn:user:db:2501";
    const targetIndex = timelineTurns.findIndex((turn) => turn.id === targetId);
    const targetMessageIndex = chatMessages.findIndex((message) => message.id === "db:2502");
    const items = virtualizer.getVirtualItems();
    const measurements = (virtualizer as any).measurementsCache ?? [];
    const targetMeasurement = targetIndex >= 0 ? measurements[targetIndex] : null;
    const rows = element ? Array.from(element.querySelectorAll<HTMLElement>("[data-row-id]")).map((row) => {
      const rect = row.getBoundingClientRect();
      return { id: row.dataset.rowId, index: Number(row.dataset.index), top: rect.top, bottom: rect.bottom, height: rect.height, visible: Boolean(viewport && rect.bottom > viewport.top && rect.top < viewport.bottom) };
    }) : [];
    probe.mark(phase, {
      sid: activeSessionId, activeSid: activeSessionRef.current, loadingHistory,
      mode: scrollStateRef.current.mode, anchorId: scrollStateRef.current.anchorId,
      follow: followStreamRef.current, restoreGeneration: prependRestoreGenerationRef.current,
      sessionGeneration: sessionRecoverySeqRef.current, restoringBookmark: restoringThreadScroll.current,
      pendingBookmark: pendingThreadScroll.current ? { ...pendingThreadScroll.current } : null,
      scrollTop: element?.scrollTop, viewportHeight: element?.clientHeight,
      scrollHeight: element?.scrollHeight, totalHeight: virtualizer.getTotalSize(),
      viewport: viewport ? { top: viewport.top, bottom: viewport.bottom } : null,
      messageCount: chatMessages.length, firstMessageId: chatMessages[0]?.id,
      lastMessageId: chatMessages.at(-1)?.id, turnCount: timelineTurns.length,
      searchQuery, searchMatches: [...searchMatches], searchMatchIdx, safeMode,
      target: { id: targetId, targetIndex, targetMessageIndex,
        lookupIndex: targetMessageIndex < 0 ? null : turnIndexForMessageIndex(targetMessageIndex),
        estimatedSize: targetIndex < 0 ? null : estimateRowSize(targetIndex),
        measurement: targetMeasurement ? { index: targetMeasurement.index, key: targetMeasurement.key, start: targetMeasurement.start, end: targetMeasurement.end, size: targetMeasurement.size } : null,
        centerOffset: targetIndex < 0 ? null : virtualizer.getOffsetForIndex(targetIndex, "center"),
        measuredSize: (virtualizer as any).itemSizeCache?.get(targetId) ?? null },
      virtualScroll: { offset: virtualizer.scrollOffset, rect: virtualizer.scrollRect, adjustments: (virtualizer as any).scrollAdjustments, intent: (virtualizer as any).scrollState ? { ...(virtualizer as any).scrollState } : null },
      range: items.map((item) => ({ index: item.index, key: item.key, start: item.start, end: item.end, size: item.size })), rows,
      ...extra,
    });
  }
  function __p09Write(label: string, write: () => void) {
    __p09("writer:before", { writer: label });
    const probe = (globalThis as any).__sparkSearchProbe;
    const previous = probe?.owner;
    if (probe) probe.owner = label;
    try { write(); } finally {
      __p09("writer:after", { writer: label });
      if (probe) probe.owner = previous;
    }
  }
  useLayoutEffect(() => { __p09("react:layout"); });
`;

if (process.argv[2] === '--serve') {
  const [webArgument, port, output, behavior] = process.argv.slice(3);
  const web = await realpath(webArgument);
  const vite = await import(pathToFileURL(path.join(web, 'node_modules/vite/dist/node/index.js')));
  const transformed = [];
  const config = {
    root: web, configFile: path.join(web, 'vite.config.ts'),
    plugins: [{ name: 'spark-search-scroll-diagnostic', enforce: 'pre', transform(code, id) {
      if (!id.endsWith('/components/ChatPanel.tsx')) return;
      const result = instrumentSearchScroll(code, id, behavior);
      transformed.push({ id, writers: result.writers });
      return { code: result.code, map: null };
    } }],
    build: { outDir: path.join(output, 'production-assets'), emptyOutDir: true },
    preview: { host: '127.0.0.1', port: Number(port), strictPort: true, proxy: { '/api': process.env.SPARK_API_TARGET } },
  };
  await vite.build(config);
  assert.equal(transformed.length, 1);
  const server = await vite.preview(config);
  await writeFile(path.join(output, 'served.json'), JSON.stringify({ mode: 'production', behavior, transformed, urls: server.resolvedUrls }, null, 2));
}
