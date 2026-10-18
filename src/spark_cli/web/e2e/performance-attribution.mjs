/** P09 request/flush/render attribution. Never overwrites earlier evidence.
 * Requires Node 22, activated root venv, PYTHON, target's own npm ci. First use
 * --prepare-only while coordinating the exclusive measurement window.
 * --probe thread|sidebar --mode dev|production --source ROOT --output-dir NEW
 * Production uses temporary transformed assets; canonical bundles are untouched.
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { createHash } from 'node:crypto';
import { instrumentSource } from './performance-attribution-source.mjs';

const { values } = parseArgs({ options: {
  source: { type: 'string' }, 'source-sha': { type: 'string' },
  'output-dir': { type: 'string' }, probe: { type: 'string' },
  mode: { type: 'string', default: 'dev' },
  'prepare-only': { type: 'boolean', default: false },
  heap: { type: 'boolean', default: false },
} });
assert.ok(['thread', 'sidebar'].includes(values.probe));
assert.ok(['dev', 'production'].includes(values.mode));
assert.equal(process.versions.node.split('.')[0], '22');
assert.ok(process.env.VIRTUAL_ENV && process.env.PYTHON);
const here = path.dirname(fileURLToPath(import.meta.url));
const backendPath = path.resolve(here, '../../../../scripts/performance_attribution_backend.py');
const output = path.resolve(values['output-dir']);
const source = path.resolve(values.source);
const web = path.join(source, 'src/spark_cli/web');
const hash = (s) => createHash('sha256').update(s).digest('hex');
const sourceHashes = {};
for (const name of ['hooks/useChatStreamController.ts', 'components/ChatPanel.tsx']) {
  const text = await readFile(path.join(web, 'src', name), 'utf8');
  // Assert exact source seams now, before any processes or measurements.
  instrumentSource(text, `/${name}`);
  sourceHashes[name] = hash(text);
}
const prepared = spawnSync(process.execPath, [path.join(here, 'performance-ab.mjs'),
  '--source', source, '--source-sha', values['source-sha'] ?? 'unrecorded',
  '--probe', values.probe, '--output-dir', output, '--prepare-only'], { encoding: 'utf8' });
assert.equal(prepared.status, 0, prepared.stdout + prepared.stderr);
let code = await readFile(path.join(output, 'instrumented-driver.mjs'), 'utf8');
const replace = (from, to) => {
  assert.equal(code.split(from).length, 2, `Expected exact generated-driver seam: ${from.slice(0, 100)}`);
  code = code.replace(from, to);
};
const backend = `import runpy; runpy.run_path(${JSON.stringify(backendPath)}, run_name='__main__')`;
const runner = path.join(here, 'performance-attribution-source.mjs');
const mode = JSON.stringify(values.mode);
if (values.probe === 'thread') {
  const startup = code.match(/^      ("import time, sys, json.*"),$/m)?.[1];
  assert.ok(startup, 'Generated backend startup found');
  replace(startup, JSON.stringify(backend));
  replace('const viteBin = path.join(webRoot, "node_modules", ".bin", "vite");', 'const viteBin = process.execPath;');
  replace('[webRoot, "--host", "127.0.0.1", "--port", String(webPort)]', `[${JSON.stringify(runner)}, '--serve', webRoot, String(webPort), ${mode}, ${JSON.stringify(output)}]`);
  replace('    window.__sparkBaselineInstrumentation = {', `    (${browserProbe.toString()})();\n    window.__sparkBaselineInstrumentation = {`);
  replace('    const stream = await measureStream(page, apiBase, `${size}-${theme.name}-${viewport}`);', `    const heap = ${values.heap} ? await retainedHeap(page, apiBase, ${JSON.stringify(output)}) : null;
    const stream = await measureStream(page, apiBase, size + '-' + theme.name + '-' + viewport);
    const streamTrials = [];
    for (const [index, delay] of [0,20,40,60,0,20,40,60].entries()) {
      process.env.ATTR_INITIAL_DELAY = String(delay);
      streamTrials.push({ initialDelay: delay, ...await measureStream(page, apiBase, 'phase-' + index) });
    }`);
  replace('  return page.evaluate(() => {\n    const trace = window.__sparkStreamTrace;', '  return page.evaluate((initialDelay) => {\n    const trace = window.__sparkStreamTrace;');
  replace('      syntheticInitialDelayMs: 60,', '      phases: window.__sparkAttribution.events,\n      syntheticInitialDelayMs: initialDelay,');
  replace('samples[0].at - trace.startedAt - 60 : null,', 'samples[0].at - trace.startedAt - initialDelay : null,');
  replace('      efficiency,\n    };\n  });\n}\n\nasync function captureCase', '      efficiency,\n    };\n  }, Number(process.env.ATTR_INITIAL_DELAY ?? 60));\n}\n\nasync function captureCase');
  replace('    delay_ms: 60,', '    delay_ms: index === 0 ? Number(process.env.ATTR_INITIAL_DELAY ?? 60) : 60,');
  replace('      stream,\n      streamProfile:', '      stream, streamTrials, heap,\n      streamProfile:');
  code += `\n${retainedHeap.toString()}\n`;
} else {
  replace("start(path.join(web, 'node_modules/.bin/vite'), [web, '--host','127.0.0.1','--port',String(webPort),'--strictPort']", `start(process.execPath, [${JSON.stringify(runner)}, '--serve', web, String(webPort), ${mode}, ${JSON.stringify(output)}]`);
  replace('    // Replaced with the exact same browser instrumentation as the thread probe.', `    (${browserProbe.toString()})();\n    // Original matching browser instrumentation follows.`);
  replace("  metrics.searchProfile=await profiler.sample('historySearch');", `  metrics.searchProfile=await profiler.sample('historySearch');
  metrics.searchTrials = [];
  for(let i=0; i<20; i++) {
    await search.fill(''); await row('000').waitFor();
    await page.waitForTimeout(50);
    await page.evaluate(() => window.__sparkAttribution.clear());
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/sessions/search' && r.ok());
    const started = await page.evaluate(() => performance.now());
    await search.fill('ancient needle ' + ' '.repeat(i));
    const body = await (await response).json();
    assert.ok(body.results.some(r => r.session_id === 'scale-499'));
    await row('499').waitFor();
    metrics.searchTrials.push(await page.evaluate(started => ({ elapsed: performance.now()-started, phases: window.__sparkAttribution.events }), started));
  }
  metrics.directSearchTrials = [];
  for(let i=0; i<20; i++) {
    const started=performance.now();
    const response=await fetch(api+'/api/sessions/search?q=ancient%20needle&limit=100&attr_direct='+i);
    assert.ok(response.ok); await response.json();
    metrics.directSearchTrials.push(performance.now()-started);
  }`);
}
const driver = path.join(output, 'attribution-driver.mjs');
await writeFile(driver, code);
const syntax = spawnSync(process.execPath, ['--check', driver], { encoding: 'utf8' });
assert.equal(syntax.status, 0, syntax.stderr);
await writeFile(path.join(output, 'preparation.json'), JSON.stringify({
  ...values, sourceHashes, driverSha256: hash(code),
  backendSha256: hash(await readFile(backendPath)),
  transformSha256: hash(await readFile(runner)),
}, null, 2));
if (values['prepare-only']) { console.log('Prepared; no servers/builds/browser started: '+driver); process.exit(0); }
const env = { ...process.env, PYTHONPATH: path.join(source, 'src'),
  SPARK_AB_SOURCE: source, SPARK_AB_OUTPUT: output, SPARK_AB_STARTUP: backend };
const args = values.probe === 'thread'
  ? [driver, '--repeat', '1', '--case', 'dark:2000:1440', '--output-dir', output] : [driver];
const startedAt = new Date().toISOString();
await writeFile(path.join(output, 'host-before.txt'), spawnSync('ps', ['-Ao', 'pid,pcpu,comm', '-r'], { encoding: 'utf8' }).stdout);
const child = spawn(process.execPath, args, { cwd: web, env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
let stdout='', stderr='', timedOut=false;
child.stdout.on('data', d => { stdout+=d; process.stdout.write(d); });
child.stderr.on('data', d => { stderr+=d; process.stderr.write(d); });
const kill = signal => { try { process.kill(-child.pid, signal); } catch { /* exited */ } };
let escalation;
const timer=setTimeout(() => { timedOut=true; kill('SIGTERM'); escalation=setTimeout(() => kill('SIGKILL'),3000); },240000);
const result=await new Promise(resolve => {
  child.once('error', e => resolve({ error:String(e), exit:null }));
  child.once('exit', (exit, signal) => resolve({ exit, signal }));
});
clearTimeout(timer); clearTimeout(escalation); kill('SIGKILL');
await writeFile(path.join(output,'stdout.log'),stdout); await writeFile(path.join(output,'stderr.log'),stderr);
await writeFile(path.join(output,'host-after.txt'),spawnSync('ps',['-Ao','pid,pcpu,comm','-r'],{encoding:'utf8'}).stdout);
await writeFile(path.join(output,'attempt.json'),JSON.stringify({schema:'spark.performance-attribution.attempt.v1',...values,source,startedAt,endedAt:new Date().toISOString(),...result,timedOut,node:process.version},null,2));
process.exitCode=result.exit===0&&!timedOut?0:1;

function browserProbe() {
  const events=[];
  window.__sparkAttribution={ events, clear:()=>{events.length=0;}, mark:(phase, data={})=>{
    if(events.length<20000) events.push({at:performance.now(),phase,...data});
  } };
  const mark=window.__sparkAttribution.mark;
  const nativeFetch=window.fetch;
  window.fetch=async function(input, options) {
    const url=String(input?.url??input);
    if(!url.includes('/api/sessions/search')) return nativeFetch.call(this,input,options);
    mark('search:fetch',{url});
    const response=await nativeFetch.call(this,input,options);
    mark('search:headers',{url,status:response.status});
    const json=response.json.bind(response);
    response.json=async()=>{ const value=await json(); mark('search:json',{url}); return value; };
    return response;
  };
  const NativeResizeObserver=window.ResizeObserver;
  window.ResizeObserver=class extends NativeResizeObserver {
    constructor(callback) { super((entries,observer)=>{const start=performance.now();callback(entries,observer);mark('rows:observer',{duration:performance.now()-start,count:entries.length});}); }
  };
}

async function retainedHeap(page, apiBase, output) {
  // No timing samples include GC/snapshot cost. Revisit only two EXISTING chats;
  // clear all probe-owned histories before GC so probes cannot create a slope.
  const cdp=await page.context().newCDPSession(page);
  await cdp.send('Performance.enable');
  const samples=[];
  for(let cycle=0; cycle<=12; cycle++) {
    if(cycle) {
      await waitForChatSession(page,'baseline_thread_50','Baseline thread 50 rows');
      await page.waitForTimeout(100);
      await waitForChatSession(page,'baseline_thread_2000','Baseline thread 2000 rows');
    }
    await page.waitForTimeout(250);
    await page.evaluate(()=>{
      window.__sparkAttribution.clear();
      for(const key of ['events','longTasks','dom','commits']) if(window.__ab?.[key]) window.__ab[key].length=0;
      window.__sparkWebEfficiency?.snapshot?.(true);
      performance.clearResourceTimings();
    });
    await cdp.send('HeapProfiler.collectGarbage');
    const metrics=Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m=>[m.name,m.value]));
    samples.push({cycle,...metrics});
    if(cycle===2||cycle===12) {
      let chunks=[];
      const receive=event=>chunks.push(event.chunk);
      cdp.on('HeapProfiler.addHeapSnapshotChunk',receive);
      await cdp.send('HeapProfiler.takeHeapSnapshot',{reportProgress:false});
      cdp.off('HeapProfiler.addHeapSnapshotChunk',receive);
      await writeFile(path.join(output,'heap-cycle-'+cycle+'.heapsnapshot'),chunks.join(''));
      chunks=[];
    }
  }
  await cdp.detach();
  return samples;
}
