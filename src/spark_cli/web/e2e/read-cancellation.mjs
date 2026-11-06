// Matched SP04 source comparison: 20 real sessions, delayed read responses.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtemp, writeFile, mkdir } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
const ownRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const root = process.env.SP04_SOURCE_ROOT || ownRoot;
const baseline = Boolean(process.env.SP04_BASELINE);
const python = process.env.PYTHON;
assert(python);
const output = process.env.SP04_OUTPUT;
assert(output);
await mkdir(output, { recursive: true });
const home = await mkdtemp(path.join(os.tmpdir(), 'spark-sp04-home-'));
await writeFile(path.join(home, 'config.yaml'), 'model:\n  default: fixture\n  provider: ollama\n');
const env = { ...process.env, SPARK_HOME: home, PYTHONPATH: path.join(root, 'src') };
execFileSync(python, ['-c', `
from core.spark_state import SessionDB
db = SessionDB()
for i in range(20):
    sid = f'sp04_{i:02}'
    db.ensure_session(sid, source='web', model='fixture')
    db.set_session_title(sid, f'Cancellation Thread {i:02}')
    for j in range(120):
        db.append_message(sid, 'user' if j % 2 == 0 else 'assistant', f'ONLY_THREAD_{i:02} history {j} ' + 'read payload ' * 100)
db.close()
`], { env, cwd: root });
const port = () => new Promise(resolve => { const server = net.createServer(); server.listen(0, '127.0.0.1', () => { const p = server.address().port; server.close(() => resolve(p)); }); });
const apiPort = await port(), webPort = await port();
const logs = [], children = [];
const start = (cmd, args, extra) => { const p = spawn(cmd, args, { cwd: root, env: { ...env, ...extra }, stdio: ['ignore', 'pipe', 'pipe'] }); children.push(p); for (const stream of [p.stdout, p.stderr]) stream.on('data', b => logs.push(b.toString())); };
const api = `http://127.0.0.1:${apiPort}`, web = `http://127.0.0.1:${webPort}`;
start(python, ['-c', `from spark_cli.web_server import start_server; start_server('127.0.0.1', ${apiPort}, False)`]);
start(path.join(ownRoot, 'src/spark_cli/web/node_modules/.bin/vite'), [path.join(root, 'src/spark_cli/web'), '--host', '127.0.0.1', '--port', String(webPort)], { SPARK_API_TARGET: api });
const ready = async url => { for (let i = 0; i < 180; i++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(r => setTimeout(r, 250)); } throw Error(`Not ready: ${url}`); };
let browser;
const requests = [], completed = [], cancelled = [], errors = [];
try {
  await ready(`${api}/api/status`); await ready(web);
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 980 } });
  page.on('pageerror', error => errors.push(String(error)));
  const tracked = url => /\/api\/(conversations|sessions)\/sp04_\d+\/(recovery|forks)/.test(url);
  page.on('request', request => { if (tracked(request.url())) requests.push(request.url()); });
  page.on('requestfailed', request => { if (tracked(request.url())) cancelled.push({ url: request.url(), error: request.failure()?.errorText }); });
  page.on('requestfinished', async request => { if (tracked(request.url())) { try { const response = await request.response(); completed.push({ url: request.url(), bytes: (await response.body()).length }); } catch {} } });
  let closing = false;
  // Deterministic one-second latency, identical on both sources. Real backend responses.
  await page.route(/\/api\/(conversations|sessions)\/sp04_\d+\/(recovery|forks)/, async route => {
    try {
      const response = await route.fetch();
      await new Promise(resolve => setTimeout(resolve, 1000));
      await route.fulfill({ response });
    } catch (error) {
      if (!closing && !/disposed|closed|aborted|Invalid InterceptionId/i.test(String(error))) errors.push(String(error));
    }
  });
  await page.goto(web);
  const panel = page.getByTestId('chat-panel');
  for (let i = 0; i < 20; i++) {
    await page.getByRole('button', { name: new RegExp(`Cancellation Thread ${String(i).padStart(2, '0')}`) }).first().click();
    await page.waitForFunction(id => document.querySelector('[data-testid="chat-panel"]')?.getAttribute('data-session-id') === id, `sp04_${String(i).padStart(2, '0')}`);
    const text = await panel.innerText();
    assert(!text.includes('Unable to reconcile'), `stale error at ${i}`);
    if (!text.includes(`ONLY_THREAD_${String(i).padStart(2, '0')}`)) assert.equal(await panel.getAttribute('data-history-loading'), 'true', `premature loading cleanup at ${i}`);
    const markers = text.match(/ONLY_THREAD_\d+/g) || [];
    assert(markers.every(marker => marker === `ONLY_THREAD_${String(i).padStart(2, '0')}`), `stale content at ${i}: ${markers}`);
    await page.waitForTimeout(60);
  }
  await panel.getByText('ONLY_THREAD_19 history 119', { exact: false }).first().waitFor();
  await page.waitForTimeout(1600);
  assert(!(await panel.innerText()).includes('Unable to reconcile'));
  assert.equal(await panel.getAttribute('data-history-loading'), 'false');
  assert.deepEqual(errors, []);
  if (!baseline) assert(cancelled.length >= 30, `expected obsolete recovery/fork cancellation: ${cancelled.length}`);
  await page.screenshot({ path: path.join(output, 'rapid-switch.png') });
  const result = { source: root, baseline, switches: 20, latencyMs: 1000, requests: requests.length, completedRequests: completed.length, completedBytes: completed.reduce((n, item) => n + item.bytes, 0), cancelled: cancelled.length, errors, completed, cancellations: cancelled };
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  closing = true;
} catch (error) {
  await writeFile(path.join(output, 'failure.log'), `${error.stack}\n${logs.join('')}`);
  throw error;
} finally {
  await browser?.close();
  for (const p of children.reverse()) { if (p.exitCode === null) { p.kill('SIGTERM'); await new Promise(r => setTimeout(r, 500)); if (p.exitCode === null) p.kill('SIGKILL'); } }
}
