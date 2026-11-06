# PR214 bounded Linux inspector comparison — 2026-11-06

## Outcome

**Hosted failure remains unresolved; no production or fixture fix justified.** One sequential, production-built comparison used exact baseline `a12205a5737d7539875d6af16b3bb58c194e8edb` and candidate `53d527d7f61a094ae258ac5afc6c4f8c61c2e3a5`. Both browser commands exited 0, passed all 11 original checks, recorded no page errors, and passed the original 21 asset response byte/ETag checks. The unchanged `abs(before - after) < 100` assertion passed **1000 → 1000** for both. No browser retry or additional causal run occurred because the failure did not reproduce.

No production files, published head, PR, CI run or remote branch changed. No children, provider requests, live Spark profile, shell worktree or existing service/container was used. SP02 retains production scroll ownership. Read the supplied AGENTS instructions, CONTEXT, STRUCTURE, accepted ADRs 0001/0012/0013, prior read-only report and fixture. The actual fixture path is `src/spark_cli/web/e2e/subagent-controls.py`, beneath the supplied read-only checkout.

## Environment and comparability limits

- Docker host: Linux aarch64. New container explicitly used `--platform linux/amd64`; `uname -m` returned `x86_64`. This is **emulated amd64**, not native hosted CI proof.
- Image: `ubuntu:24.04`, digest `sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852`. Userspace reports Ubuntu 24.04.5 LTS; kernel `7.0.14-linuxkit` differs from hosted Ubuntu.
- Node **v22.22.1**, verified executable `/opt/node-v22.22.1-linux-x64/bin/node`; frozen nested `npm ci` separately for both variants. Both installs and builds exited 0. Vite 7.3.7 reported builds of 1m16s / 1m12s.
- Python **3.12.3** from Ubuntu, not hosted 3.11.18. Python 3.11 was not pursued through alternative installation paths. One fresh container `/work/.venv` held the same resolved dependencies for both variants; full freeze retained. Project metadata and nested npm lockfiles are identical between exact commits. Backend subprocesses select their own archived source using fixture PYTHONPATH.
- Python Playwright **1.62.0**, installed with supported Ubuntu dependencies; Chromium / Headless Shell **151.0.7922.34**, revision **1234**. Browser setup succeeded on its first attempt. Viewport 1440×980, reduced motion, headless Chromium, synthetic backend/SSE fixture match the prior diagnostic protocol.
- Computed row font is `16px / 24px "Avenir Next", "Segoe UI", sans-serif`; document fonts report loaded. `fc-match` resolves each family request to WenQuanYi Zen Hei Regular. This is fontconfig evidence, not a direct Chromium glyph-font measurement or proof of hosted font parity.
- Emulation timing is materially different: base samples span 3501.3ms across 59 frames; candidate 8985.9ms across 42 frames. Sampling has overhead. These runs are source/dependency/fixture matched to each other, not timing-, kernel-, Python- or font-matched to hosted CI.

## Trace findings

The identical diagnostic fixture preserves the original assertion, original 1000ms return wait, setup/detachment checks, and all subsequent checks. It samples rAF scrollTop, scrollHeight, viewport, row IDs/indexes, tops/heights, computed fonts, font readiness and first intersecting keyed row. This follow-on adds only a snapshot of existing panel DOM attributes per frame: active session/owner, history loading/count, turn and streaming state. No setters or controllers are monkeypatched. Transition labels describe the fixture navigation; internal restoration flags are not exposed, so direct completion of the internal 30-frame restoration is **not** claimed.

| Measurement | Baseline | Candidate |
| --- | --- | --- |
| Original before → after | 1000 → 1000 | 1000 → 1000 |
| First/final visible key | `turn:user:db:39` | `turn:user:db:39` |
| First/final key top | −161.25px | −161.25px |
| First/final key height | 248.75px | 248.75px |
| Viewport | 601px | 601px |
| First/final scrollHeight | 5053 → 5343 | 5343 → 4279 |
| Trace frames | 59 | 42 |
| Final history loading/count | false / 51 | false / 51 |

Both return traces observe Alpha history loading true at height 635, then false at height 4395. Both then record raw top **0 → 826 → 770 → 710 → 1000**, with mounted row measurement changing the list height **4395 → 4339 → 4279**. Baseline subsequently records height 5246 → 5343 at unchanged raw top/key/offset. Candidate stops sampling at the first recorded 1000/4279 frame before the original assertion. Thus both preserve visible content at the measurement, but there is no proof that all row measurement/restoration work has settled, particularly for the slower candidate. Do not convert this observation into a claim that a fixed delay or frame budget caused the hosted failure.

The candidate screenshot was visually inspected: prompt/answer 20 and 21 occupy the viewport with the tail of answer 19 above, retained attachment/draft below and Alpha child detail at right. Geometry agrees with the keyed trace. Hosted retained evidence reports 1000 → 1410, but lacks its pre-switch keyed geometry; this run cannot determine whether that hosted change was a wrong restore, legitimate anchor preservation, or fixture timing. No threshold waiver, synchronization change, production hunk or semantic gate replacement is proposed without that evidence.

## Reproduction commands and retained evidence

Host sources were immutable `git archive` exports into `/tmp/pr214-linux-ab/{base,candidate}`; no host venv/node_modules was copied. The container had no host bind mounts, privileged mode, published port or live credentials. Setup commands ran inside its own filesystem:

```sh
docker run -d --platform linux/amd64 --name pr214-linux-inspector-95003 ubuntu:24.04 sleep infinity
docker cp /tmp/pr214-linux-ab pr214-linux-inspector-95003:/work
# Inside the scoped container:
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv curl xz-utils ca-certificates
curl -fsSL https://nodejs.org/dist/v22.22.1/node-v22.22.1-linux-x64.tar.xz -o /tmp/node.tar.xz
tar -xJf /tmp/node.tar.xz -C /opt
python3 -m venv /work/.venv
source /work/.venv/bin/activate
export PATH=/opt/node-v22.22.1-linux-x64/bin:$PATH
node --version
node -p process.execPath
python --version
pip install -e '/work/candidate[dev,web]' playwright==1.62.0
python -m playwright install --with-deps chromium
pip freeze > /work/python-freeze.txt
```

For base then candidate, the retained `run.sh` copied the identical diagnostic fixture into the archived source and ran from its nested web directory:

```sh
npm ci > /work/VARIANT-npm.log 2>&1
npx vite build --outDir /work/VARIANT-dist > /work/VARIANT-build.log 2>&1
SPARK_E2E_BUILT_WEB=1 SPARK_E2E_ASSET_DIR=/work/VARIANT-dist \
  SPARK_E2E_REPORTS=/work/VARIANT-report \
  python e2e/subagent-controls.py > /work/VARIANT-inspector.log 2>&1
```

The fixture creates/cleans synthetic SPARK_HOME, configures provider loopback port 1, and uses real SQLite/backend/SSE plus synthetic streams. The scoped container was stopped and removed after artifact extraction; other containers were untouched. Pulled Ubuntu image/cache remains available.

Durable local evidence directory: `/Users/joe/.t3/artifacts/pr214-linux-inspector-2026-11-06/`.

- `evidence.tar.gz`: SHA256 `e4d17bd9c061059c6826e755bec367edc33af39721588dd51b6216ae25ad799d`. Contains both full reports, screenshots/DOM/backend logs, per-frame traces, npm/build/browser logs and exit codes, environment/freeze, exact fixture, runner and summarizer, plus `summary.json` with geometry transitions.
- `setup.log`: SHA256 `8e63a8e3cbda38e15d13b090079eb1174daacd656b6bb0802732912d1101f56b`.
- `font-resolution.txt`: SHA256 `39d0ff02bc00825a16624de8e17f36270ae077ab0896ab680c441e87cbb3c908`.
- Exact diagnostic fixture SHA256 `f9803a458ef6d4fc67057df9c02245b8ae9f4e3aab47db13041b2863edb9cd8c`.

Original hosted artifact remains `/tmp/spark-pr214-browser-gates.zip` (SHA256 `7eebc6d23493d820577af9c6c3c96ba18a363e9f63ccd11da6fe101229509fe3`), logs `/tmp/spark-pr214-e2e-failed.log`, extracted inspector under `/tmp/spark-pr214-browser-gates/tmp/spark-browser-gates/inspector`. Prior macOS comparison/report was read only, not rerun or modified.

Stop decision: the one authorized Linux pair is complete. No cause is proven and no fix is proposed. Parent should retain the hosted gate as unresolved; any further native hosted diagnostic must be separately authorized and preserve the original acceptance check while capturing its pre/post keyed viewport and loading/measurement trajectory.
