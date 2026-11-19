# Deferred frontend toolchain majors — 2026-11-16

Baseline: main `90575dd7`. The following independent Dependabot proposals fail
normal `npm ci` with ERESOLVE. Their web lint/test/build, browser and supply-chain
jobs all fail during dependency installation, before app tests execute. This is
an incompatible proposed dependency graph, not evidence of a main regression.
The peer ranges below were confirmed against the npm registry for these exact
installed versions as well as the hosted failure logs.

| Proposal | Concrete blocker | Hosted evidence | Revisit when |
| --- | --- | --- | --- |
| [#258 Vite 8.3.8](https://github.com/automatedigital/spark/pull/258) | `@tailwindcss/vite@4.2.1` requires Vite `^5.2.0 || ^6 || ^7`. | [npm ci failure](https://github.com/automatedigital/spark/actions/runs/43933979497) | Upgrade the Tailwind plugin and any coupled plugins together, verify Vite 8 support, then run frozen install, lint, types, tests, bundle budgets and browser flows. |
| [#259 ESLint 10.14.0](https://github.com/automatedigital/spark/pull/259) | `eslint-plugin-react-hooks@5.1.0` supports ESLint 3–9, not 10. `@eslint/js` remains on 9.39.4 too. | [npm ci failure](https://github.com/automatedigital/spark/actions/runs/43934002770) | Migrate React Hooks plugin/config and align `@eslint/js` with ESLint; preserve active lint rules and resolve new findings before running web acceptance. |
| [#260 TypeScript 7.0.2](https://github.com/automatedigital/spark/pull/260) | `typescript-eslint@8.57.0` requires TypeScript `>=4.8.4 <6.0.0`, excluding both 6 and 7. | [npm ci failure](https://github.com/automatedigital/spark/actions/runs/43934031481) | Adopt a compatible parser/linter stack and review compiler/config changes; validate full frontend and browser gates without peer overrides. |

Migration follow-up: [#262](https://github.com/automatedigital/spark/issues/262).

## Deferral scope

These upgrades remain deferred until the peer compatibility and acceptance
criteria above are met. Review proposed upgrades manually.

No dependency version, lockfile, npm install behavior, CI check, audit threshold
or application source is changed. Security findings in a deferred major require
an explicit compatible fix or a coordinated migration; do not override peers or
suppress advisory failures to make an installation pass. Historical failed runs
remain visible on the closed proposals; closing is a documented deferral, not a
successful upgrade.

## Main verification

Before this configuration-only change, latest main workflow runs passed:
[actionlint](https://github.com/automatedigital/spark/actions/runs/43935605994),
[Python](https://github.com/automatedigital/spark/actions/runs/43935594664),
[web including browser e2e](https://github.com/automatedigital/spark/actions/runs/43935594722),
and [npm supply chain](https://github.com/automatedigital/spark/actions/runs/43935594932).
The latter three ran on `2d05317c`; the subsequent main commit `90575dd7` adds
only the separately passing actionlint workflow. These source-identical checks
remain applicable; the original follow-up changed only Dependabot configuration and documentation.
