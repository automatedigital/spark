/** Bounded matching-source A/B probe. No source, gate or canonical bundle writes.
 * Activate the root venv; PYTHON=/absolute/venv/bin/python.
 * node e2e/performance-ab.mjs --source /source/snapshot --probe thread|sidebar|search10k --output-dir /new/directory
 * Run sequentially, alternate sources, and keep builds/tests idle. The source must
 * have its own npm ci (same lockfile). Output is deliberately never overwritten.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { createHash } from 'node:crypto';

const pythonStartup = `import time, sys, json
t=time.perf_counter()
from spark_cli.web_server import start_server
print("AB_STARTUP " + json.dumps({"phase":"web_server_import", "ms":(time.perf_counter()-t)*1000}), file=sys.stderr, flush=True)
import uvicorn
real_run=uvicorn.run
def marked_run(*args, **kwargs):
    print("AB_STARTUP " + json.dumps({"phase":"before_uvicorn_run", "ms":(time.perf_counter()-t)*1000}), file=sys.stderr, flush=True)
    return real_run(*args, **kwargs)
uvicorn.run=marked_run
start_server('127.0.0.1', int(sys.argv[1]), False)
`;

const { values } = parseArgs({ options: {
  source: { type: 'string' }, probe: { type: 'string' },
  'output-dir': { type: 'string' }, 'source-sha': { type: 'string' },
  'prepare-only': { type: 'boolean', default: false },
  diagnostic: { type: 'boolean', default: false },
} });
assert.ok(values.source && values['output-dir']);
assert.ok(['thread', 'sidebar', 'search10k'].includes(values.probe));
assert.ok(process.env.VIRTUAL_ENV && process.env.PYTHON, 'Activate root venv and set PYTHON');
assert.equal(process.versions.node.split('.')[0], '22');
const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(values.source);
const web = path.join(source, 'src/spark_cli/web');
const output = path.resolve(values['output-dir']);
await mkdir(output); // Fail on reused evidence directories.
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
const lock = await readFile(path.join(web, 'package-lock.json'));
assert.equal(sha256(lock), sha256(await readFile(path.join(here, '../package-lock.json'))));
let code;
let driverHash;
if (values.probe === 'thread') {
  code = await readFile(path.join(here, 'baseline-capture.mjs'), 'utf8');
  driverHash = sha256(code);
  const replace = (from, to) => {
    assert.ok(code.includes(from), `Unsupported baseline driver: missing ${from.slice(0, 80)}`);
    code = code.replace(from, to);
  };
  replace('const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");', `const webRoot = ${JSON.stringify(web)};`);
  replace('import { chromium } from "playwright";', `import { chromium } from ${JSON.stringify(path.join(web, 'node_modules/playwright/index.mjs'))};`);
  // The original driver builds before measuring a dev page. Do not inject build
  // load into these timings; this probe does not claim production acceptance.
  replace('    buildTemporaryWeb(stagedBuildRoot);', '    // A/B probe intentionally does not build canonical or temporary assets.');
  replace('  const page = await context.newPage();\n  const historyRequests', `  const page = await context.newPage();
  const profiler = await attachProfiler(page);
  const historyRequests`);
  replace('    const firstRenderMs = performance.now() - startedAt;', `    const firstRenderMs = performance.now() - startedAt;
    const firstUsefulProfile = await profiler.sample('firstUseful');`);
  replace('    const browserPerformance = await performanceMetrics(page);', `    const browserPerformance = await performanceMetrics(page);
    const fullHistoryProfile = await profiler.sample('fullHistory');`);
  if (values.diagnostic) {
    replace("const fullHistoryProfile = await profiler.sample('fullHistory');", "const fullHistoryProfile = await profiler.sample('fullHistory');\n    fullHistoryProfile.retainedHeapAfterGC = await profiler.collectHeap();");
    replace('  const profiler = await attachProfiler(page);', '  const profiler = await attachProfiler(page);\n  page.__abProfiler = profiler;');
    replace('  await createStreamProbe(apiBase, sessionId, title, marker);', '  await page.__abProfiler.startCPU();\n  await createStreamProbe(apiBase, sessionId, title, marker);');
    replace('  await page.waitForTimeout(150);\n  return page.evaluate(() => {', '  await page.waitForTimeout(150);\n  await writeFile(path.join(options["output-dir"], "stream-cpu.json"), JSON.stringify(await page.__abProfiler.stopCPU()));\n  return page.evaluate(() => {');
  }
  replace('      navigationTiming,\n      history:', '      navigationTiming,\n      firstUsefulProfile, fullHistoryProfile,\n      history:');
  replace('      stream,\n      screenshot:', `      stream,
      streamProfile: await profiler.sample('afterStream'),
      networkProfile: profiler.network,
      screenshot:`);
  replace('    window.__sparkBaselineInstrumentation = {', `    installBrowserProbe();
    window.__sparkBaselineInstrumentation = {`);
  // addInitScript serializes this function, so installBrowserProbe must be inline.
  replace('    installBrowserProbe();', `    (${browserProbe.toString()})();`);
  replace('await new Promise((resolve) => setTimeout(resolve, 200));', 'await new Promise((resolve) => setTimeout(resolve, 25));');
  replace('"from spark_cli.web_server import start_server; import sys; start_server(\'127.0.0.1\', int(sys.argv[1]), False)"', JSON.stringify(pythonStartup));
  replace('    if (browser) await browser.close();', '    await writeFile(path.join(stagedOutputRoot, "backend.log"), backend.logs.join(""));\n    await writeFile(path.join(stagedOutputRoot, "vite.log"), vite.logs.join(""));\n    if (browser) await browser.close();');
  code += `\n${attachProfiler.toString()}\n`;
} else {
  code = await readFile(path.join(here, 'performance-sidebar-probe.mjs'), 'utf8');
  driverHash = sha256(code);
  code = code.replace('import { chromium } from "playwright";', `import { chromium } from ${JSON.stringify(path.join(web, 'node_modules/playwright/index.mjs'))};`);
  code = code.replace('BROWSER_PROBE_PLACEHOLDER();', `(${browserProbe.toString()})();`);
  code += `\n${attachProfiler.toString()}\n${browserProbe.toString()}\n`;
}
const driver = path.join(output, 'instrumented-driver.mjs');
await writeFile(driver, code);
if (values['prepare-only']) {
  const syntax = spawnSync(process.execPath, ['--check', driver], { encoding: 'utf8' });
  assert.equal(syntax.status, 0, syntax.stderr);
  console.log(`Prepared and syntax checked ${driver}; no servers/browser started`);
  process.exit(0);
}
const environment = {
  ...process.env, PYTHONPATH: path.join(source, 'src'), SPARK_AB_SOURCE: source,
  SPARK_AB_OUTPUT: output, SPARK_AB_STARTUP: pythonStartup,
  SPARK_AB_SEARCH10K: values.probe === 'search10k' ? '1' : '',
};
const args = values.probe === 'thread'
  ? [driver, '--repeat', '1', '--case', 'dark:2000:1440', '--output-dir', output] : [driver];
const started = new Date();
const hostBefore = spawnSync('ps', ['-Ao', 'pid,pcpu,comm', '-r'], { encoding: 'utf8' }).stdout;
await writeFile(path.join(output, 'host-before.txt'), hostBefore);
const child = spawn(process.execPath, args, { cwd: web, env: environment, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
let stdout = '', stderr = '', timedOut = false;
child.stdout.on('data', (data) => { stdout += data; process.stdout.write(data); });
child.stderr.on('data', (data) => { stderr += data; process.stderr.write(data); });
const kill = (signal) => { try { process.kill(-child.pid, signal); } catch { /* exited */ } };
let escalation;
const timeout = setTimeout(() => { timedOut = true; kill('SIGTERM'); escalation = setTimeout(() => kill('SIGKILL'), 3000); }, 240_000);
const result = await new Promise((resolve) => {
  child.once('error', (error) => resolve({ exit: null, error: String(error) }));
  child.once('exit', (exit, signal) => resolve({ exit, signal }));
});
clearTimeout(timeout); clearTimeout(escalation); kill('SIGKILL');
await writeFile(path.join(output, 'stdout.log'), stdout);
await writeFile(path.join(output, 'stderr.log'), stderr);
await writeFile(path.join(output, 'host-after.txt'), spawnSync('ps', ['-Ao', 'pid,pcpu,comm', '-r'], { encoding: 'utf8' }).stdout);
await writeFile(path.join(output, 'attempt.json'), JSON.stringify({
  schema: 'spark.performance-ab.attempt.v1', source, sourceSha: values['source-sha'], probe: values.probe,
  startedAt: started.toISOString(), endedAt: new Date().toISOString(), ...result, timedOut,
  timeoutMs: 240000, node: process.version, platform: os.platform(), cpu: os.cpus()[0].model,
  diagnostic: values.diagnostic,
  loadAverage: os.loadavg(), python: process.env.PYTHON, lockSha256: sha256(lock),
  originalDriverSha256: driverHash, generatedDriverSha256: sha256(code),
  changes: 'Matching driver across sources; read-only source override; 25ms readiness poll; startup markers; CDP/resource/DOM instrumentation; no build during probe.',
}, null, 2));
process.exitCode = result.exit === 0 && !timedOut ? 0 : 1;

function browserProbe() {
  window.__ab = { events: [], longTasks: [], dom: [], mutations: 0, commits: [] };
  const record = () => {
    const panel = document.querySelector('[data-testid="chat-panel"]');
    const id = panel?.getAttribute('data-session-id');
    const tokens = panel?.textContent?.match(/token \d+\./g)?.length ?? 0;
    const last = window.__ab.dom.at(-1);
    if (id !== last?.id || tokens !== last?.tokens) window.__ab.dom.push({ at: performance.now(), id, tokens });
    window.__ab.mutations++;
  };
  new MutationObserver(record).observe(document, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['data-session-id', 'data-streaming'] });
  new PerformanceObserver((list) => window.__ab.longTasks.push(...list.getEntries().map((entry) => ({ startTime: entry.startTime, duration: entry.duration })))).observe({ type: 'longtask', buffered: true });
  const NativeEventSource = window.EventSource;
  window.EventSource = class extends NativeEventSource {
    constructor(url, options) {
      super(url, options);
      this.addEventListener('message', (event) => {
        try {
          const data = JSON.parse(event.data);
          window.__ab.events.push({ at: performance.now(), url: String(url), type: data.type, topic: data.topic, data: data.data });
        } catch { /* leave actual parser responsible */ }
      });
    }
  };
}

async function attachProfiler(page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Performance.enable');
  const network = [];
  cdp.on('Network.requestWillBeSent', (e) => network.push({ phase: 'request', id: e.requestId, at: e.timestamp, wallTime: e.wallTime, url: e.request.url, method: e.request.method, initiator: e.initiator.type }));
  cdp.on('Network.responseReceived', (e) => network.push({ phase: 'response', id: e.requestId, at: e.timestamp, url: e.response.url, status: e.response.status, protocol: e.response.protocol, timing: e.response.timing }));
  cdp.on('Network.loadingFinished', (e) => network.push({ phase: 'finished', id: e.requestId, at: e.timestamp, bytes: e.encodedDataLength }));
  cdp.on('Network.loadingFailed', (e) => network.push({ phase: 'failed', id: e.requestId, at: e.timestamp, error: e.errorText }));
  return { network,
    startCPU: async () => { await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', { interval: 1000 }); await cdp.send('Profiler.start'); },
    stopCPU: async () => (await cdp.send('Profiler.stop')).profile,
    collectHeap: async () => { await cdp.send('HeapProfiler.collectGarbage'); return Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((m) => [m.name, m.value])); },
    sample: async (phase) => ({
    phase, cdp: Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map((m) => [m.name, m.value])),
    browser: await page.evaluate(() => ({
      at: performance.now(), efficiency: window.__sparkWebEfficiency?.snapshot?.(),
      probe: window.__ab, resources: performance.getEntriesByType('resource').map((r) => r.toJSON()),
      navigation: performance.getEntriesByType('navigation').map((r) => r.toJSON()),
    })),
  }) };
}
