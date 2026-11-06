// SP02 matched source A/B fixture. SP02_SOURCE_ROOT may point at an immutable archive.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
const ownRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const root = process.env.SP02_SOURCE_ROOT || ownRoot;
const baseline = Boolean(process.env.SP02_BASELINE);
const longHistory = Boolean(process.env.SP02_LONG_HISTORY);
const python = process.env.PYTHON;
assert(python, 'Set PYTHON to the fresh interpreter');
const port = () => new Promise(resolve => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); }); });
const apiPort = await port(), webPort = await port();
const home = await mkdtemp(path.join(os.tmpdir(), 'spark-sp02-browser-'));
await mkdir(path.join(home, 'workspace'));
await writeFile(path.join(home, 'config.yaml'), 'model:\n  default: test-model\n  provider: ollama\n  base_url: http://localhost:11434/v1\n');
const logs = [];
const start = (cmd, args, env) => { const p = spawn(cmd, args, { cwd: root, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] }); for (const stream of [p.stdout, p.stderr]) stream.on('data', b => logs.push(b.toString())); return p; };
const stop = async p => { if (p.exitCode !== null) return; p.kill('SIGTERM'); await new Promise(r => setTimeout(r, 700)); if (p.exitCode === null) p.kill('SIGKILL'); };
const ready = async url => { for (let i = 0; i < 180; i++) { try { if ((await fetch(url)).ok) return; } catch {} await new Promise(r => setTimeout(r, 250)); } throw Error(`Not ready: ${url}\n${logs.slice(-10).join('')}`); };
const api = `http://127.0.0.1:${apiPort}`, web = `http://127.0.0.1:${webPort}`;
if (longHistory) execFileSync(python, ['-c', `
from core.spark_state import SessionDB
db = SessionDB()
for sid, title in [('sp02_a', 'Snapshot alpha'), ('sp02_b', 'Snapshot bravo')]:
    db.ensure_session(sid, source='web', model='replay')
    db.set_session_title(sid, title)
    for i in range(240):
        db.append_message(sid, 'user' if i % 2 == 0 else 'assistant', f'History {i}: ' + 'retained history ' * 40)
db.close()
`], { cwd: root, env: { ...process.env, SPARK_HOME: home, PYTHONPATH: path.join(root, 'src') } });
const backend = start(python, ['-c', `import spark_cli.web_server as w; w._WEB_TURN_STALE_AFTER_S=1; w.start_server('127.0.0.1', ${apiPort}, False)`], { SPARK_HOME: home, PYTHONPATH: path.join(root, 'src'), SPARK_WEB_FAKE_STREAMS: '1' });
const frontend = start(path.join(ownRoot, 'src/spark_cli/web/node_modules/.bin/vite'), [path.join(root, 'src/spark_cli/web'), '--host', '127.0.0.1', '--port', String(webPort)], { SPARK_API_TARGET: api });
let browser, page;
const recovered = [];
try {
  await ready(`${api}/api/status`); await ready(web);
  for (const [id, title] of [['sp02_a', 'Snapshot alpha'], ['sp02_b', 'Snapshot bravo']]) {
    const response = await fetch(`${api}/api/dev/fake-streams`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ session_id: id, title, reuse_existing: longHistory, message: `${title} prompt`, events: [{ type: 'token', text: `${title} retained text` }, { type: 'stall', phase: 'api', text: 'waiting for provider' }, { type: 'token', text: ' finished', delay_ms: 120000 }] }) });
    assert(response.ok, await response.text());
  }
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage({ viewport: { width: 1440, height: 980 } });
  const requests = [], responses = [];
  let posts = 0;
  page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/api/conversations')) posts++; if (request.method() === 'GET' && /\/api\/(conversations|sessions)\/sp02_[ab]\//.test(request.url())) requests.push({ url: request.url(), at: performance.now() }); });
  page.on('response', async response => { if (response.url().includes('/recovery')) { try { const data = await response.json(); recovered.push({ status: response.status(), session: data.session_id, text: data.stream_text, history: data.history?.messages.length, detail: data.detail }); } catch {} } if (/\/api\/(conversations|sessions)\/sp02_[ab]\//.test(response.url())) { try { responses.push({ url: response.url(), bytes: (await response.body()).length }); } catch {} } });
  await page.goto(web); await page.getByText('Spark').first().waitFor();
  await page.getByText('Running', { exact: false }).first().click();
  const panel = page.getByTestId('chat-panel');
  const samples = [];
  // Switch away and back; first restored content includes real history + active tail.
  for (let i = 0; i < 5; i++) {
    await page.getByRole('button', { name: /Snapshot bravo/ }).first().click();
    await panel.getByText('Snapshot bravo retained text', { exact: false }).first().waitFor();
    const before = requests.length, beforeBytes = responses.length, began = performance.now();
    await page.getByRole('button', { name: /Snapshot alpha/ }).first().click();
    await panel.getByText('Snapshot alpha retained text', { exact: false }).first().waitFor();
    const restoredMs = performance.now() - began;
    assert(!(await panel.innerText()).includes('Snapshot bravo retained text'), 'cross-chat token bleed');
    await page.waitForTimeout(500);
    const used = requests.slice(before).filter(x => x.url.includes('/sp02_a/'));
    const recovery = used.filter(x => /\/(recovery|turn-status|stream-snapshot|turn-outcome|plan|pending-actions|messages)(\?|$)/.test(x.url));
    if (!baseline) assert.equal(recovery.length, 1, JSON.stringify(used));
    samples.push({ restoredMs, recoveryRequests: recovery.length, bytes: responses.slice(beforeBytes).filter(x => /\/sp02_a\//.test(x.url)).reduce((n, x) => n + x.bytes, 0) });
  }
  if (!baseline) {
    // Delay an old snapshot across navigation, then release it after the new view loads.
    let release, intercepted;
    const held = new Promise(r => { intercepted = r; });
    const unblock = new Promise(r => { release = r; });
    await page.route('**/api/conversations/sp02_b/recovery*', async route => { const response = await route.fetch(); intercepted(); await unblock; await route.fulfill({ response }); });
    await page.getByRole('button', { name: /Snapshot bravo/ }).first().click();
    await held;
    await page.getByRole('button', { name: /Snapshot alpha/ }).first().click();
    await panel.getByText('Snapshot alpha retained text', { exact: false }).first().waitFor();
    release(); await page.waitForTimeout(500);
    assert(!(await panel.innerText()).includes('Snapshot bravo retained text'), 'delayed reply adopted another chat');
    await page.unroute('**/api/conversations/sp02_b/recovery*');
    // Explicit reconnect consumes the same single response and issues no history fetch.
    const count = requests.length;
    await panel.getByTestId('recovery-card').getByRole('button', { name: 'Reconnect' }).click();
    await page.waitForTimeout(500);
    const reconnect = requests.slice(count).filter(x => /\/(recovery|turn-status|stream-snapshot|turn-outcome|plan|pending-actions|messages)(\?|$)/.test(x.url));
    assert.equal(reconnect.length, 1, JSON.stringify(reconnect));
    await page.reload();
    await page.getByText('Running', { exact: false }).first().click();
    await page.getByRole('button', { name: /Snapshot alpha/ }).first().click();
    await panel.getByText('Snapshot alpha retained text', { exact: false }).first().waitFor();
  }
  assert.equal(posts, 0, 'recovery replayed a conversation action');
  const sorted = samples.map(x => x.restoredMs).sort((a,b) => a-b);
  console.log(JSON.stringify({ mode: baseline ? 'baseline' : 'candidate', longHistory, samples, medianMs: sorted[2], p95Ms: sorted[4], posts }, null, 2));
} catch (error) { console.error('recovery responses', JSON.stringify(recovered)); if (page) { console.error((await page.locator('body').innerText()).slice(-12000)); await page.screenshot({ path: '/tmp/sp02-snapshot-failure.png' }); } console.error(logs.slice(-10).join('')); throw error; } finally { if (browser) await browser.close(); await stop(frontend); await stop(backend); await rm(home, { recursive: true, force: true }); }
