/** Read-only Vite transforms for the P09 attribution probe, never app imports. */
import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { realpath, writeFile } from 'node:fs/promises';

export function instrumentSource(code, id) {
  const mark = (phase, extra = '{}') => `globalThis.__sparkAttribution?.mark(${JSON.stringify(phase)}, ${extra});`;
  const replace = (from, to) => {
    assert.equal(code.split(from).length, 2, `Expected one probe seam in ${id}: ${from.slice(0, 90)}`);
    code = code.replace(from, to);
  };
  if (id.endsWith('/hooks/useChatStreamController.ts')) {
    replace('    clearScheduledFlush();\n    return dispatch(flushAction(reason));', `    ${mark('flush', '{ reason, sid: stateRef.current.activeSessionId, buffer: stateRef.current.tokenBuffer }')}\n    clearScheduledFlush();\n    return dispatch(flushAction(reason));`);
    replace('    flushTimerRef.current = window.setTimeout(() => {', `    ${mark('flush:scheduled', '{ delay, sid: stateRef.current.activeSessionId }')}\n    flushTimerRef.current = window.setTimeout(() => {\n      ${mark('flush:timer', '{ sid: stateRef.current.activeSessionId }')}`);
    replace('        flushRafRef.current = null;\n        flush("manual");', `        ${mark('flush:raf', '{ sid: stateRef.current.activeSessionId }')}\n        flushRafRef.current = null;\n        flush("manual");`);
    replace('    const transition = reduceChatStreamController(stateRef.current, eventAction(event));', `    ${mark('token:enqueue', '{ topic: event.topic, data: event.data, sid: stateRef.current.activeSessionId }')}\n    const transition = reduceChatStreamController(stateRef.current, eventAction(event));`);
    replace('    stateRef.current = transition.state;\n    setState(transition.state);', `    ${mark('state:commit', '{ sid: transition.state.activeSessionId }')}\n    stateRef.current = transition.state;\n    setState(transition.state);`);
  }
  if (id.endsWith('/components/ChatPanel.tsx')) {
    replace('    recordWebEfficiency("reactCommits");', `    ${mark('react:effect', '{ sid: sessionId }')}\n    recordWebEfficiency("reactCommits");`);
    // Layout effects execute after DOM commit and before paint; the existing
    // efficiency counter is passive and cannot stand in for this timestamp.
    replace('  useSelectedDetailSubscription(sessionId);', `  useLayoutEffect(() => { ${mark('react:layout', '{ sid: sessionId }')} });\n  useSelectedDetailSubscription(sessionId);`);
  }
  return code;
}

// The child Vite entrypoint reads the target's own config/dependencies. Both
// production and dev paths use the same checked source transform.
if (process.argv[2] === '--serve') {
  const [webArgument, port, mode, output] = process.argv.slice(3);
  // macOS /tmp is an alias for /private/tmp. Vite/Rollup must use the same
  // canonical root as its resolved config when naming index.html assets.
  const web = await realpath(webArgument);
  const vite = await import(pathToFileURL(path.join(web, 'node_modules/vite/dist/node/index.js')));
  const transformed = new Set();
  const config = {
    root: web, configFile: path.join(web, 'vite.config.ts'),
    plugins: [{ name: 'spark-p09-phase-probe', enforce: 'pre', transform(code, id) {
      if (!/\/(hooks\/useChatStreamController\.ts|components\/ChatPanel\.tsx)$/.test(id)) return;
      transformed.add(id);
      return { code: instrumentSource(code, id), map: null };
    } }],
    server: { host: '127.0.0.1', port: Number(port), strictPort: true },
    preview: { host: '127.0.0.1', port: Number(port), strictPort: true, proxy: { '/api': process.env.SPARK_API_TARGET } },
    build: { outDir: path.join(output, 'production-assets'), emptyOutDir: true },
  };
  if (mode === 'production') {
    await vite.build(config);
    assert.equal(transformed.size, 2, 'Both production source seams transformed');
    const server = await vite.preview(config);
    await writeFile(path.join(output, 'served.json'), JSON.stringify({ mode, transformed: [...transformed], urls: server.resolvedUrls }));
  } else {
    const server = await vite.createServer(config);
    await server.listen();
  }
}
