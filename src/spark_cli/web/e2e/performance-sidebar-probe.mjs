/** Internal matching P00/P09 Inbox probe, launched by performance-ab.mjs.
 * Kept separate from the canonical sidebar gate because P00 lacks its new APIs.
 * No paging/organization correctness or production acceptance claim is made.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { chromium } from "playwright";

const root = process.env.SPARK_AB_SOURCE;
const web = path.join(root, 'src/spark_cli/web');
const output = process.env.SPARK_AB_OUTPUT;
const python = process.env.PYTHON;
const home = await mkdtemp(path.join(os.tmpdir(), 'spark-ab-sidebar-'));
const port = () => new Promise((resolve) => {
  const server = net.createServer();
  server.listen(0, '127.0.0.1', () => { const value = server.address().port; server.close(() => resolve(value)); });
});
const apiPort = await port(), webPort = await port();
const api = `http://127.0.0.1:${apiPort}`, url = `http://127.0.0.1:${webPort}`;
const env = { ...process.env, SPARK_HOME: home, PYTHONPATH: path.join(root, 'src'), SPARK_WEB_FAKE_STREAMS: '1' };
await writeFile(path.join(home, 'config.yaml'), 'model:\n  default: test-model\n  provider: ollama\n  base_url: http://127.0.0.1:1/v1\n');
for (let i = 0; i < 10; i++) await mkdir(path.join(home, 'workspace', `project-${i}`), { recursive: true });
const seed = spawnSync(python, ['-c', String.raw`
from core.spark_state import SessionDB
base=1700000000
db=SessionDB()
for index in range(1000):
    sid=f"scale-{index:03d}"
    db.create_session(sid, f"workspace:project-{index%10}", model="test-model")
    db.set_session_title(sid, f"Scale chat {index:03d}")
    db._conn.execute("UPDATE sessions SET started_at=? WHERE id=?", (base-index,sid))
# One old match preserves the original P00 sidebar fixture.
if ${process.env.SPARK_AB_SEARCH10K === '1' ? 'True' : 'False'}:
    for index in range(10000):
        text="ancient needle full history result" if index%100==0 else f"Deterministic filler message {index}"
        db.append_message("scale-499", "user", text)
else:
    db.append_message("scale-499", "user", "ancient needle full history result")
db._conn.execute("UPDATE messages SET timestamp=? WHERE session_id=?",(base-499,"scale-499"))
db._conn.commit()
db.close()
`], { cwd: root, env, encoding: 'utf8' });
assert.equal(seed.status, 0, seed.stderr);
const processes = [];
function start(bin, args, environment, name) {
  const child = spawn(bin, args, { cwd: web, env: environment, stdio: ['ignore', 'pipe', 'pipe'] });
  const logs = [];
  child.stdout.on('data', (data) => logs.push(String(data)));
  child.stderr.on('data', (data) => logs.push(String(data)));
  processes.push({ child, logs, name });
  return child;
}
async function ready(target) {
  const deadline = Date.now()+45000;
  while (Date.now()<deadline) {
    try { if ((await fetch(target)).ok) return; } catch { /* retry startup */ }
    await new Promise((resolve) => setTimeout(resolve,25));
  }
  throw new Error(`Timed out ${target}`);
}
let browser, page;
const metrics = { fixture: { sessions:1000, projects:10, historyMessages:1 }, checks: [], errors: [] };
try {
  const started = performance.now();
  start(python, ['-c', process.env.SPARK_AB_STARTUP, String(apiPort)], env, 'backend');
  start(path.join(web, 'node_modules/.bin/vite'), [web, '--host','127.0.0.1','--port',String(webPort),'--strictPort'], { ...env, SPARK_API_TARGET:api }, 'vite');
  await ready(`${api}/api/status`);
  metrics.backendReadyMs=performance.now()-started;
  await ready(url);
  browser=await chromium.launch({ headless:true });
  metrics.browser=await browser.version();
  const context=await browser.newContext({ viewport:{width:1440,height:900},deviceScaleFactor:1 });
  await context.addInitScript(() => {
    localStorage.setItem('spark-webui-theme','codex');
    localStorage.setItem('spark-web-efficiency-test','1');
    // Replaced with the exact same browser instrumentation as the thread probe.
    BROWSER_PROBE_PLACEHOLDER();
  });
  page=await context.newPage(); page.setDefaultTimeout(15000);
  page.on('pageerror',(e)=>metrics.errors.push(String(e)));
  page.on('console',(m)=>{ if(m.type()==='error') metrics.errors.push(m.text()); });
  const profiler=await attachProfiler(page);
  // P00 Inbox cards have no aria-label; both revisions expose the title as
  // actual text inside a role=button. Keep one matching locator for both.
  const row=(id)=>page.getByRole('button').filter({hasText:`Scale chat ${id}`}).first();
  const startupAt=performance.now();
  await page.goto(`${url}/?spark_efficiency_test=1`,{waitUntil:'domcontentloaded'});
  await row('000').waitFor();
  metrics.firstUsefulMs=performance.now()-startupAt;
  metrics.firstUsefulProfile=await profiler.sample('firstUseful');
  await row('000').evaluate((el)=>{ window.__abSelectionStart=performance.now(); el.click(); });
  await page.waitForFunction(()=>document.querySelector('[data-testid="chat-panel"]')?.getAttribute('data-session-id')==='scale-000');
  metrics.selectionMs=await page.evaluate(()=>performance.now()-window.__abSelectionStart);
  metrics.selectionStart=await page.evaluate(()=>window.__abSelectionStart);
  metrics.selectionProfile=await profiler.sample('selected');
  // DOM-observer timing matches the canonical gate and avoids Playwright input overhead.
  const search=page.getByPlaceholder('Search',{exact:true});
  const searchFor=async(value,id,local=false)=>search.evaluate((el,args)=>new Promise((resolve,reject)=>{
    const start=performance.now();
    const timeout=setTimeout(()=>{observer.disconnect();reject(new Error(`Search timeout ${args.value}`));},5000);
    const observer=new MutationObserver(()=>{
      const cards=[...document.querySelectorAll('[role="button"]')].filter((node)=>node.textContent.includes('Scale chat '));
      const result=cards.find((node)=>node.textContent.includes(`Scale chat ${args.id}`));
      if(!result || (args.local && cards.length>=50)) return;
      clearTimeout(timeout);observer.disconnect();resolve(performance.now()-start);
    });
    observer.observe(document.body,{childList:true,subtree:true});
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,args.value);
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }),{value,id,local});
  metrics.localSearchMs=await searchFor('Scale chat 049','049',true);
  metrics.localSearchProfile=await profiler.sample('localSearch');
  await search.fill('');await row('000').waitFor();
  metrics.fullHistorySearchMs=await searchFor('ancient needle','499');
  metrics.searchProfile=await profiler.sample('historySearch');
  if(process.env.SPARK_AB_SEARCH10K==='1') {
    metrics.fixture.historyMessages=10000;
    metrics.fixture.matchingMessages=100;
    metrics.warmSearchMs=[];
    for(let i=0;i<3;i++) {
      await search.fill('');await row('000').waitFor();
      // Hydrated row 499 is now local. Require a real search response containing
      // it and the visible result; a local title match cannot satisfy the gate.
      const query=`ancient needle ${' '.repeat(i)}`;
      const started=await page.evaluate(()=>performance.now());
      const response=page.waitForResponse((r)=>new URL(r.url()).pathname==='/api/sessions/search' && r.ok());
      await search.fill(query);
      const body=await (await response).json();
      assert.ok(body.results.some((r)=>r.session_id==='scale-499'),'real SQLite search returns fixture match');
      await row('499').waitFor();
      metrics.warmSearchMs.push(await page.evaluate(()=>performance.now())-started);
    }
    metrics.warmSearchProfile=await profiler.sample('warmSearch10k');
    assert.ok(Math.max(...metrics.warmSearchMs)<=500,'10k warm browser search p95 <=500ms');
  }
  metrics.checks.push('1000 sessions/10 projects, matching first page, selection, local title filter, server-backed old message search');
  await page.screenshot({path:path.join(output,'sidebar.png')});
  metrics.networkProfile=profiler.network;
  assert.equal(metrics.errors.length,0,JSON.stringify(metrics.errors));
  assert.ok(metrics.selectionMs<100,`Original selection budget: ${metrics.selectionMs}ms <100ms`);
  assert.ok(metrics.localSearchMs<100,`Original local-filter budget: ${metrics.localSearchMs}ms <100ms`);
  assert.ok(metrics.fullHistorySearchMs<600,`Original full-history budget: ${metrics.fullHistorySearchMs}ms <600ms`);
} catch(error) {
  metrics.failure=String(error.stack);process.exitCode=1;
  await page?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});
} finally {
  for(const proc of processes) await writeFile(path.join(output,`${proc.name}.log`),proc.logs.join(''));
  await writeFile(path.join(output,'sidebar.json'),JSON.stringify(metrics,null,2));
  await browser?.close();
  for(const {child} of processes) child.kill('SIGTERM');
  await new Promise((resolve)=>setTimeout(resolve,750));
  for(const {child} of processes) if(child.exitCode===null) child.kill('SIGKILL');
  await rm(home,{recursive:true,force:true});
}
