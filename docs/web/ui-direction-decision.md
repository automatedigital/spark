# Web UI direction decision

Date: 2026-08-04

## Decision

Use the dense/operational thread direction as Spark's production foundation.
Retain the calm direction's final-answer prominence and breathing room around
outcome cards. The prototype was a review surface only; production work should
be implemented in the real thread components and backed by the canonical
fixtures and interaction contracts.

## Durable design rules

- Final answers remain the primary reading surface, with generous line length,
  readable type, and enough separation to scan the result quickly.
- Changed-files and plan cards remain compact, directly beneath the answer that
  produced them, while detailed inspection stays in the right-hand workspace.
- Tool calls, reasoning, and subagent activity use dense settled-work rows that
  collapse after completion. Active work, failures, approvals, and unresolved
  input stay visible and expanded.
- The layout keeps Spark's amber accent, dark/light theme behavior,
  typography character, terminology, and existing controls. T3-inspired
  restraint, spacing, and thread rhythm are references for hierarchy and
  density, not a replacement for Spark's identity.
- At narrow widths, controls wrap without horizontal overflow; the composer
  remains reachable, thread context remains understandable, and outcome cards
  stack into a single readable column.

## Review evidence

The preserved six screenshots are the visual record for the accepted direction:

- Calm review: `src/spark_cli/web/screenshots/prototypes/calm-changed-file-1440.png`
- Calm review: `src/spark_cli/web/screenshots/prototypes/calm-changed-file-1024.png`
- Calm review: `src/spark_cli/web/screenshots/prototypes/calm-changed-file-768.png`
- Dense review: `src/spark_cli/web/screenshots/prototypes/dense-changed-file-1440.png`
- Dense review: `src/spark_cli/web/screenshots/prototypes/dense-changed-file-1024.png`
- Dense review: `src/spark_cli/web/screenshots/prototypes/dense-changed-file-768.png`

The prototype query route and its temporary source are intentionally removed;
these screenshots and this decision note are the retained review artifacts.
