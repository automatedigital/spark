/** Bounded P09 search diagnostic. --prepare-only never builds/installs/launches.
 * source-ref pins a committed source snapshot under a fresh output directory.
 * After explicit root window clear: npm ci in snapshot/src/spark_cli/web, then
 * node THIS --run-prepared OUTPUT --window-clear EXACT-ROOT-MESSAGE.
 * --behavior instant is a controlled diagnostic only; original is the default.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { createHash } from 'node:crypto';
import { instrumentSearchScroll } from './search-scroll-source.mjs';

const { values } = parseArgs({ options: {
  source: { type: 'string' }, 'source-ref': { type: 'string', default: 'e8d6713' },
  'output-dir': { type: 'string' }, 'prepare-only': { type: 'boolean', default: false },
  behavior: { type: 'string', default: 'original' },
  'observe-after-guard': { type: 'boolean', default: false },
  'run-prepared': { type: 'string' }, 'window-clear': { type: 'string' },
} });
assert.equal(process.version, 'v22.22.1', 'Use verified actual Node 22.22.1');
assert.ok(process.env.VIRTUAL_ENV && process.env.PYTHON, 'Activate root venv; set PYTHON');
const here = path.dirname(fileURLToPath(import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
if (values['run-prepared']) {
  assert.ok(values['window-clear'], 'Explicit root measurement window clearance required');
  const output = path.resolve(values['run-prepared']);
  const prep = JSON.parse(await readFile(path.join(output, 'preparation.json'), 'utf8'));
  for (const [file, expected] of Object.entries(prep.sourceHashes)) {
    assert.equal(hash(await readFile(path.join(prep.source, file))), expected, `Source drift: ${file}`);
  }
  assert.equal(hash(await readFile(prep.driver)), prep.driverHash);
  assert.equal(hash(await readFile(prep.transform)), prep.transformHash);
  await writeFile(path.join(output, 'execution-start.json'), JSON.stringify({ startedAt: new Date().toISOString(), clearance: values['window-clear'] }, null, 2), { flag: 'wx' });
  const child = spawn(process.execPath, [prep.driver, '--repeat', '1', '--case', 'dark:2000:1440', '--output-dir', output], {
    cwd: path.join(prep.source, 'src/spark_cli/web'), detached: true,
    env: { ...process.env, PYTHONPATH: path.join(prep.source, 'src') }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '', stderr = '', timedOut = false;
  child.stdout.on('data', data => { stdout += data; process.stdout.write(data); });
  child.stderr.on('data', data => { stderr += data; process.stderr.write(data); });
  const kill = signal => { try { process.kill(-child.pid, signal); } catch { /* exited */ } };
  const timer = setTimeout(() => { timedOut = true; kill('SIGKILL'); }, 240000);
  const result = await new Promise(resolve => {
    child.once('error', error => resolve({ exit: null, error: String(error) }));
    child.once('exit', (exit, signal) => resolve({ exit, signal }));
  });
  clearTimeout(timer); kill('SIGKILL');
  await writeFile(path.join(output, 'stdout.log'), stdout, { flag: 'wx' });
  await writeFile(path.join(output, 'stderr.log'), stderr, { flag: 'wx' });
  await writeFile(path.join(output, 'attempt.json'), JSON.stringify({ ...result, timedOut, endedAt: new Date().toISOString(), node: process.version, executable: process.execPath }, null, 2), { flag: 'wx' });
  process.exitCode = result.exit === 0 && !timedOut ? 0 : 1;
} else {
  assert.ok(values['prepare-only'], 'Prepare first, then explicitly --run-prepared after root clearance');
  assert.ok(values.source && values['output-dir']);
  const output = path.resolve(values['output-dir']);
  await mkdir(output); // Fail rather than overwrite evidence.
  const source = path.join(output, 'source');
  await mkdir(source);
  const git = args => {
    const result = spawnSync('git', ['-C', path.resolve(values.source), ...args], { encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr); return result.stdout.trim();
  };
  const commit = git(['rev-parse', `${values['source-ref']}^{commit}`]);
  const archive = spawnSync('git', ['-C', path.resolve(values.source), 'archive', '--format=tar', commit, 'src', 'scripts', 'pyproject.toml'], { maxBuffer: 100 * 1024 * 1024 });
  assert.equal(archive.status, 0, String(archive.stderr));
  const unpack = spawnSync('tar', ['-xf', '-', '-C', source], { input: archive.stdout });
  assert.equal(unpack.status, 0, String(unpack.stderr));
  const web = path.join(source, 'src/spark_cli/web');
  const panelFile = path.join(web, 'src/components/ChatPanel.tsx');
  const original = await readFile(panelFile, 'utf8');
  const transformed = instrumentSearchScroll(original, '/components/ChatPanel.tsx', values.behavior);
  await writeFile(path.join(output, 'ChatPanel.instrumented.tsx'), transformed.code);
  const transform = path.join(output, 'search-scroll-source.mjs');
  await writeFile(transform, await readFile(path.join(here, 'search-scroll-source.mjs')));
  let code = await readFile(path.join(web, 'e2e/baseline-capture.mjs'), 'utf8');
  const originalDriverHash = hash(code);
  const replace = (from, to) => {
    assert.equal(code.split(from).length, 2, `Expected one driver seam: ${from.slice(0, 100)}`);
    code = code.replace(from, to);
  };
  replace('const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");', `const webRoot = ${JSON.stringify(web)};`);
  replace('import { chromium } from "playwright";', `import { chromium } from ${JSON.stringify(path.join(web, 'node_modules/playwright/index.mjs'))};`);
  replace('const viteBin = path.join(webRoot, "node_modules", ".bin", "vite");', 'const viteBin = process.execPath;');
  replace('[webRoot, "--host", "127.0.0.1", "--port", String(webPort)]', `[${JSON.stringify(transform)}, '--serve', webRoot, String(webPort), ${JSON.stringify(output)}, ${JSON.stringify(values.behavior)}]`);
  replace('    buildTemporaryWeb(stagedBuildRoot);', '    // Diagnostic Vite child builds temporary transformed production assets.');
  replace('    window.__sparkBaselineInstrumentation = {', `    (${browserProbe.toString()})();\n    window.__sparkBaselineInstrumentation = {`);
  replace('  const page = await context.newPage();', `  const page = await context.newPage();
  page.__diagnosticErrors = [];
  page.on('pageerror', error => page.__diagnosticErrors.push({ kind: 'pageerror', error: String(error) }));
  page.on('console', message => { if(message.type() === 'error') page.__diagnosticErrors.push({kind: 'console', error: message.text()}); });
  page.__navigation = [];
  page.on('framenavigated', frame => { if(frame === page.mainFrame()) page.__navigation.push({at:performance.now(),url:frame.url()}); });`);
  replace('    const stream = await measureStream(page, apiBase, `${size}-${theme.name}-${viewport}`);', `    const searchDiagnostic = await diagnoseSearch(page, ${JSON.stringify(output)}, ${values['observe-after-guard']});
    const stream = { updateCount: 0, diagnosticOnly: true };`);
  replace('      stream,\n      screenshot:', '      stream, searchDiagnostic,\n      screenshot:');
  replace('          await validateCaseResult(result, stagedScreenshotRoot);', '          // This bounded diagnostic runs the unchanged search guard only; no full baseline acceptance claim.');
  replace('      schema: "spark.web.baseline.v1",', '      schema: "spark.web.search-scroll-diagnostic.v1",');
  replace('      mode: "dev",', '      mode: "production",');
  replace('    if (browser) await browser.close();', `    await writeFile(path.join(stagedOutputRoot, 'backend.log'), backend.logs.join(''));
    await writeFile(path.join(stagedOutputRoot, 'vite.log'), vite.logs.join(''));
    if (browser) await browser.close();`);
  code += `\n${diagnoseSearch.toString()}\n`;
  const driver = path.join(output, 'diagnostic-driver.mjs');
  await writeFile(driver, code);
  for (const filename of [driver, transform]) {
    const check = spawnSync(process.execPath, ['--check', filename], { encoding: 'utf8' });
    assert.equal(check.status, 0, check.stderr);
  }
  const sourceHashes = {};
  for (const file of ['src/spark_cli/web/src/components/ChatPanel.tsx', 'src/spark_cli/web/src/pages/ChatPage.tsx', 'src/spark_cli/web/src/hooks/useChatSessionController.ts', 'src/spark_cli/web/package-lock.json']) sourceHashes[file] = hash(await readFile(path.join(source, file)));
  await writeFile(path.join(output, 'preparation.json'), JSON.stringify({ schema: 'spark.search-scroll.preparation.v1', preparedAt: new Date().toISOString(), commit, source, output, behavior: values.behavior, observeAfterGuard: values['observe-after-guard'], sourceHashes, writers: transformed.writers, transform, transformHash: hash(await readFile(transform)), originalDriverHash, driver, driverHash: hash(code), transformedSourceHash: hash(transformed.code), node: process.version, executable: process.execPath, limits: ['No build, browser, installation or capture in prepare-only', 'Thirteen fixed forced-GC checkpoints, no heap snapshots or parsing', 'Source logging perturbs timing; single diagnostic cannot establish population incidence'] }, null, 2));
  console.log(`READY: prepared ${driver}; no dependencies installed/build/browser started`);
}

async function diagnoseSearch(page, output, observeAfterGuard = false) {
  const checkpoints = [];
  const cdp = await page.context().newCDPSession(page);
  try {
    for (let cycle = 0; cycle <= 12; cycle++) {
      if (cycle === 12) await page.evaluate(() => window.__sparkSearchProbe.clear());
      if (cycle) {
        await waitForChatSession(page, 'baseline_thread_50', 'Baseline thread 50 rows');
        await page.waitForTimeout(100);
        await waitForChatSession(page, 'baseline_thread_2000', 'Baseline thread 2000 rows');
      }
      await page.waitForTimeout(250);
      await page.evaluate(() => {
        window.__sparkWebEfficiency?.snapshot?.(true);
        performance.clearResourceTimings();
      });
      await cdp.send('HeapProfiler.collectGarbage');
      checkpoints.push({ cycle, at: new Date().toISOString(), dom: await page.evaluate(() => window.__sparkSearchProbe.dom()) });
    }
  } finally { await cdp.detach(); }
  await writeFile(path.join(output, 'cycles.json'), JSON.stringify(checkpoints, null, 2));
  await page.evaluate(() => { window.__sparkSearchProbe.mark('guard:before-click', window.__sparkSearchProbe.dom()); });
  let outcome = 'failed', failure = null;
  try {
    // Identical original added guard, preserving literal, selector and 30s wait.
    const query = 'Response 1952:';
    await page.getByTitle('Search messages (⌘F)', {exact:true}).click();
    const search = page.getByPlaceholder('Search messages…', {exact:true});
    await search.fill(query);
    await page.locator('[data-testid="chat-panel"] [data-row-id]').filter({hasText:query}).first().waitFor({state:'visible', timeout:30000});
    await search.press('Escape');
    outcome = 'passed';
  } catch (error) { failure = String(error.stack ?? error); }
  const originalGuard = { outcome, failure, state: await page.evaluate(() => window.__sparkSearchProbe.dom()), at: await page.evaluate(() => performance.now()) };
  await writeFile(path.join(output, 'original-guard.json'), JSON.stringify(originalGuard, null, 2));
  const observation = { requested: observeAfterGuard, outcome: 'not-requested', failure: null };
  if (observeAfterGuard && !failure) {
    observation.outcome = 'failed';
    try {
      await page.waitForFunction(() => window.__sparkSearchProbe.events.some(event => event.phase === 'search:intent' && event.searchQuery === 'Response 1952:'), null, { timeout: 5000 });
      observation.intent = await page.evaluate(() => window.__sparkSearchProbe.events.find(event => event.phase === 'search:intent' && event.searchQuery === 'Response 1952:'));
      await page.evaluate(() => window.__sparkSearchProbe.mark('observation:intent-seen', window.__sparkSearchProbe.dom()));
      await page.waitForFunction(() => window.__sparkSearchProbe.dom().rows.some(row => row.id === 'turn:user:db:2501' && row.visible), null, { timeout: 10000 });
      observation.firstIntersection = await page.evaluate(() => ({ at: performance.now(), ...window.__sparkSearchProbe.dom() }));
      // Observe rather than close on the first transient intersection.
      await page.waitForTimeout(1500);
      observation.settled = await page.evaluate(() => ({ at: performance.now(), ...window.__sparkSearchProbe.dom() }));
      if (!observation.settled.rows.some(row => row.id === 'turn:user:db:2501' && row.visible)) throw new Error('Target no longer intersects viewport after 1500ms observation');
      observation.outcome = 'passed';
    } catch (error) { observation.failure = String(error.stack ?? error); }
    await page.evaluate(() => window.__sparkSearchProbe.mark('observation:outcome', window.__sparkSearchProbe.dom()));
  }
  const trace = await page.evaluate(() => {
    const probe = window.__sparkSearchProbe;
    probe.mark('guard:outcome', probe.dom());
    probe.enabled = false;
    return { events: probe.events, dropped: probe.dropped, document: { timeOrigin: performance.timeOrigin, url: location.href }, final: probe.dom() };
  });
  const report = { outcome, failure, originalGuard, observation, checkpoints: checkpoints.length, navigation: page.__navigation, errors: page.__diagnosticErrors, ...trace };
  await writeFile(path.join(output, 'search-trace.json'), JSON.stringify(report));
  await page.screenshot({ path: path.join(output, 'search-outcome.png') });
  if (failure) throw new Error(failure);
  if (observation.failure) throw new Error('Additive post-guard observation: ' + observation.failure);
  return { outcome, observation: observation.outcome, checkpoints: checkpoints.length };
}

function browserProbe() {
  const events = [];
  const probe = window.__sparkSearchProbe = {
    enabled: true, events, dropped: 0, owner: null, activeRaf: null,
    mark(phase, data = {}) {
      if (!this.enabled) return;
      if (events.length >= 25000) { this.dropped++; return; }
      events.push({ sequence: events.length, at: performance.now(), phase, owner: this.owner, raf: this.activeRaf, ...data });
    },
    clear() { events.length = 0; this.dropped = 0; },
    dom() {
      const el = document.querySelector('[data-testid="chat-scroll"]');
      const viewport = el?.getBoundingClientRect();
      return { sid: document.querySelector('[data-testid="chat-panel"]')?.getAttribute('data-session-id'), scrollTop: el?.scrollTop, viewportHeight: el?.clientHeight, scrollHeight: el?.scrollHeight, viewport: viewport ? {top:viewport.top,bottom:viewport.bottom}:null,
        rows: el ? [...el.querySelectorAll('[data-row-id]')].map(row => { const r = row.getBoundingClientRect(); return {id:row.dataset.rowId,index:Number(row.dataset.index),top:r.top,bottom:r.bottom,height:r.height,visible:r.bottom>viewport.top&&r.top<viewport.bottom}; }) : [],
      };
    },
  };
  const stack = () => new Error().stack?.split('\n').slice(2, 9).join('\n');
  const nativeRaf = window.requestAnimationFrame.bind(window);
  const nativeCancel = window.cancelAnimationFrame.bind(window);
  window.requestAnimationFrame = callback => {
    const scheduledBy = stack();
    const id = nativeRaf(timestamp => {
      const previous = probe.activeRaf; probe.activeRaf = id;
      probe.mark('raf:run', {id});
      try { callback(timestamp); } finally { probe.mark('raf:end', {id}); probe.activeRaf = previous; }
    });
    probe.mark('raf:scheduled', {id, stack:scheduledBy}); return id;
  };
  window.cancelAnimationFrame = id => { probe.mark('raf:cancel', {id}); return nativeCancel(id); };
  const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
  if (descriptor?.set) Object.defineProperty(Element.prototype, 'scrollTop', {
    ...descriptor, set(value) {
      if (this.matches?.('[data-testid="chat-scroll"]')) probe.mark('native:scrollTop-before', {requested:value,stack:stack(),...probe.dom()});
      descriptor.set.call(this, value);
      if (this.matches?.('[data-testid="chat-scroll"]')) probe.mark('native:scrollTop-after', probe.dom());
    },
  });
  for (const name of ['scrollTo', 'scrollBy', 'scrollIntoView']) {
    const original = Element.prototype[name];
    Element.prototype[name] = function(...args) {
      if (this.matches?.('[data-testid="chat-scroll"], [data-row-id]')) probe.mark(`native:${name}`, {args,stack:stack(),...probe.dom()});
      return original.apply(this, args);
    };
  }
  const NativeResizeObserver = window.ResizeObserver;
  window.ResizeObserver = class extends NativeResizeObserver {
    constructor(callback) { super((entries, observer) => {
      probe.mark('resize:callback-start', {entries:entries.map(entry=>({id:entry.target.dataset?.rowId,testid:entry.target.dataset?.testid,height:entry.contentRect.height}))});
      try { callback(entries, observer); } finally { probe.mark('resize:callback-end'); }
    }); }
  };
  document.addEventListener('scroll', event => { if (event.target.matches?.('[data-testid="chat-scroll"]')) probe.mark('native:scroll-event', probe.dom()); }, true);
  window.addEventListener('pagehide', event => probe.mark('document:pagehide', {timeOrigin:performance.timeOrigin,persisted:event.persisted}));
  setInterval(() => { if(probe.enabled) probe.mark('sample', probe.dom()); }, 100);
}
