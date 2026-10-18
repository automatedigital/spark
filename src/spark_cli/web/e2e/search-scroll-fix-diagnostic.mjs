/** Additive candidate checks around the historical, unchanged search driver.
 * --source ROOT --source-ref COMMIT --output-dir NEW prepares only.
 * Run via search-scroll-diagnostic.mjs --run-prepared after root clearance.
 */
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ options: { source: { type: 'string' }, 'source-ref': { type: 'string' }, 'output-dir': { type: 'string' } } });
assert.equal(process.version, 'v22.22.1');
assert.ok(values.source && values['source-ref'] && values['output-dir']);
const here = path.dirname(fileURLToPath(import.meta.url));
const output = path.resolve(values['output-dir']);
const prepared = spawnSync(process.execPath, [path.join(here, 'search-scroll-diagnostic.mjs'), '--source', values.source, '--source-ref', values['source-ref'], '--output-dir', output, '--observe-after-guard', '--prepare-only'], { encoding: 'utf8' });
assert.equal(prepared.status, 0, prepared.stdout + prepared.stderr);
const prepFile = path.join(output, 'preparation.json');
const prep = JSON.parse(await readFile(prepFile, 'utf8'));
const fallbackWriter = prep.writers.find(writer => writer.statement === 'element.scrollTop = saved.top;')?.label;
assert.ok(fallbackWriter);
let code = await readFile(prep.driver, 'utf8');
const replace = (from, to) => { assert.equal(code.split(from).length, 2, `Expected unique candidate seam ${from.slice(0, 100)}`); code = code.replace(from, to); };
replace("  const observation = { requested: observeAfterGuard, outcome: 'not-requested', failure: null };", "  let uiRegressions = null;\n  const observation = { requested: observeAfterGuard, outcome: 'not-requested', failure: null };");
replace("  const trace = await page.evaluate(() => {\n    const probe = window.__sparkSearchProbe;", `  if (!failure && observation.outcome === 'passed') uiRegressions = await candidateRegressions(page, output, ${JSON.stringify(fallbackWriter)});
  const trace = await page.evaluate(() => {
    const probe = window.__sparkSearchProbe;`);
replace('const report = { outcome, failure, originalGuard, observation, checkpoints:', 'const report = { outcome, failure, originalGuard, observation, uiRegressions, checkpoints:');
replace("  if (observation.failure) throw new Error('Additive post-guard observation: ' + observation.failure);", "  if (observation.failure) throw new Error('Additive post-guard observation: ' + observation.failure);\n  if (uiRegressions?.outcome !== 'passed') throw new Error('Candidate UI regression failure: ' + JSON.stringify(uiRegressions));");
code += `\n${candidateRegressions.toString()}\n`;
await writeFile(path.join(output, 'historical-driver-before-additive-checks.mjs'), await readFile(prep.driver), { flag: 'wx' });
await writeFile(prep.driver, code);
const syntax = spawnSync(process.execPath, ['--check', prep.driver], { encoding: 'utf8' });
assert.equal(syntax.status, 0, syntax.stderr);
prep.historicalPreparedDriverHash = prep.driverHash;
prep.driverHash = createHash('sha256').update(code).digest('hex');
prep.candidateRegressions = { fallbackWriter, phases: ['actual search intent/ownership', 'cached saved-position switch/restore', 'small-chat match and next-match', 'history prepend anchor after explicit search'] };
await writeFile(prepFile, JSON.stringify(prep, null, 2));
await writeFile(path.join(output, 'search-scroll-fix-diagnostic.mjs'), await readFile(fileURLToPath(import.meta.url)), { flag: 'wx' });
console.log(`READY candidate: ${prep.driver}; historical guard intact, no build/browser/install`);

async function candidateRegressions(page, output, fallbackWriter) {
  const report = { outcome: 'failed', stages: [], failure: null };
  const stage = async (name, action) => {
    const at = await page.evaluate(() => performance.now());
    await page.evaluate(name => window.__sparkSearchProbe.mark('regression:start', { name }), name);
    const result = await action();
    report.stages.push({ name, at, outcome: 'passed', result });
  };
  const openSearch = async () => {
    const input = page.getByPlaceholder('Search messages…', { exact: true });
    if (!await input.count()) await page.getByTitle('Search messages (⌘F)', { exact: true }).click();
    return input;
  };
  const clearSearch = async () => {
    const input = await openSearch();
    await input.fill('');
    await page.waitForFunction(() => {
      const event = window.__sparkSearchProbe.events.filter(event => event.searchQuery !== undefined).at(-1);
      return event?.searchQuery === '' && event.searchMatches.length === 0;
    }, null, { timeout: 3000 });
    await input.press('Escape');
  };
  const intersect = async id => {
    await page.waitForFunction(id => window.__sparkSearchProbe.dom().rows.some(row => row.id === id && row.visible), id, { timeout: 10000 });
    await page.waitForTimeout(750);
    const dom = await page.evaluate(() => window.__sparkSearchProbe.dom());
    if (!dom.rows.some(row => row.id === id && row.visible)) throw new Error(`No settled viewport intersection for ${id}`);
    return dom;
  };
  try {
    await stage('actual-search-ownership-fence', async () => {
      const proof = await page.evaluate(fallbackWriter => {
        const events = window.__sparkSearchProbe.events;
        const intent = events.find(event => event.phase === 'search:intent' && event.searchQuery === 'Response 1952:');
        const after = events.filter(event => event.sequence > intent.sequence);
        const writes = after.filter(event => event.phase === 'writer:before');
        return { intent, searchWriter: writes[0], oldFallbackWrites: writes.filter(event => event.writer === fallbackWriter), dom: window.__sparkSearchProbe.dom() };
      }, fallbackWriter);
      if (proof.intent.messageIndex !== 251 || proof.intent.mappedIndex !== 125 || proof.intent.actualTurnId !== 'turn:user:db:2501') throw new Error('Unexpected target mapping');
      if (proof.oldFallbackWrites.length) throw new Error('Bookmark fallback wrote after explicit search intent');
      if (proof.searchWriter.restoreGeneration !== proof.intent.restoreGeneration + 1 || proof.searchWriter.pendingBookmark !== null || proof.searchWriter.restoringBookmark) throw new Error('Search writer did not own restore fence before scroll');
      if (!proof.dom.rows.some(row => row.id === 'turn:user:db:2501' && row.visible)) throw new Error('Original search target outside viewport');
      return proof;
    });
    await stage('cached-saved-position-switch-and-restore', async () => {
      await clearSearch();
      await page.getByTestId('chat-scroll').hover();
      await page.mouse.wheel(0, -240);
      await page.waitForTimeout(200);
      const before = await waitForStableAnchor(page);
      if (!before?.id) throw new Error('No saved-position anchor');
      await waitForChatSession(page, 'baseline_thread_50', 'Baseline thread 50 rows');
      await page.waitForTimeout(600);
      await waitForChatSession(page, 'baseline_thread_2000', 'Baseline thread 2000 rows');
      await page.waitForFunction(({ id, top }) => {
        const row = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
        return row && Math.abs(row.getBoundingClientRect().top - top) <= 2;
      }, before, { timeout: 5000 });
      await page.waitForTimeout(1500);
      const after = await page.evaluate(id => {
        const row = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
        return row ? { id, top: row.getBoundingClientRect().top } : null;
      }, before.id);
      if (!after || Math.abs(after.top - before.top) > 2) throw new Error(`Saved-position anchor drift ${JSON.stringify({ before, after })}`);
      return { before, after };
    });
    await stage('small-chat-search-and-next-match', async () => {
      await waitForChatSession(page, 'baseline_thread_50', 'Baseline thread 50 rows');
      const input = await openSearch();
      const since = await page.evaluate(() => window.__sparkSearchProbe.events.length);
      await input.fill('Response 00');
      await page.waitForFunction(since => window.__sparkSearchProbe.events.slice(since).some(event => event.phase === 'search:intent' && event.searchQuery === 'Response 00' && event.mappedIndex === 0), since, { timeout: 5000 });
      const first = await intersect('turn:user:db:1');
      await input.press('Enter');
      await page.waitForFunction(since => window.__sparkSearchProbe.events.slice(since).some(event => event.phase === 'search:intent' && event.searchQuery === 'Response 00' && event.mappedIndex === 1 && event.searchMatchIdx === 1), since, { timeout: 5000 });
      const next = await intersect('turn:user:db:3');
      await clearSearch();
      return { first, next };
    });
    await stage('history-prepend-anchor-after-search', async () => {
      await waitForChatSession(page, 'baseline_thread_2000', 'Baseline thread 2000 rows');
      // Match the existing history-anchor browser gate's deterministic start.
      await page.getByTestId('chat-scroll').evaluate(element => new Promise(resolve => {
        let remaining = 45;
        const hold = () => requestAnimationFrame(() => { element.scrollTop = 0; if (--remaining) hold(); else resolve(); });
        hold();
      }));
      const before = await waitForStableAnchor(page);
      if (!before?.id) throw new Error('No prepend anchor');
      const loaded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/sessions/baseline_thread_2000/messages' && response.ok());
      await page.getByRole('button', { name: 'Load earlier messages', exact: true }).click();
      await loaded;
      await page.evaluate(({ id, top }) => new Promise((resolve, reject) => {
        let remaining = 120, stable = 0;
        const check = () => requestAnimationFrame(() => {
          const row = document.querySelector(`[data-row-id="${CSS.escape(id)}"]`);
          const drift = row ? row.getBoundingClientRect().top - top : null;
          stable = drift !== null && Math.abs(drift) <= 1 ? stable + 1 : 0;
          if (stable >= 5) return resolve();
          if (--remaining <= 0) return reject(new Error(`Prepend anchor did not settle: ${id} drift=${drift}`));
          check();
        });
        check();
      }), before);
      const after = await page.evaluate(id => ({ id, top: document.querySelector(`[data-row-id="${CSS.escape(id)}"]`).getBoundingClientRect().top }), before.id);
      return { before, after, driftPx: after.top - before.top };
    });
    report.outcome = 'passed';
  } catch (error) { report.failure = String(error.stack ?? error); report.final = await page.evaluate(() => window.__sparkSearchProbe.dom()); }
  await writeFile(path.join(output, 'ui-regressions.json'), JSON.stringify(report, null, 2));
  return report;
}
