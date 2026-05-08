---
name: design-md
description: Create, read, apply, audit, and validate Google DESIGN.md files so frontend and design work follows a durable design-system source of truth.
version: 1.0.0
author: Spark Agent
license: Apache-2.0
metadata:
  spark:
    tags: [design, design-systems, frontend, ui, ux, tokens, google-design-md]
    related_skills: [frontend-design, popular-web-designs]
---

# DESIGN.md

Use this skill when the user asks to create, update, audit, apply, or validate a `DESIGN.md` file, or when frontend/design work should follow a repo-local design system. `DESIGN.md` is Google's open format for describing visual identity to coding agents: machine-readable tokens in YAML front matter plus human-readable rationale in Markdown.

Source references:
- Google Labs `design.md` repo: https://github.com/google-labs-code/design.md
- Official spec: https://raw.githubusercontent.com/google-labs-code/design.md/main/docs/spec.md

## Core Workflow

1. Look for a repo-local `DESIGN.md` before starting frontend or visual design work.
2. If it exists, treat it as the source of truth for visual choices. Tokens are normative; prose explains how to apply them.
3. If the user asks to create one, inspect existing UI, CSS, design tokens, component libraries, screenshots, brand docs, and app copy before drafting.
4. Preserve unknown sections and unknown token names. Do not discard project-specific design guidance just because it is outside the current spec.
5. Validate with the official CLI when Node/npm are available:

```bash
npx @google/design.md lint DESIGN.md
```

If the CLI is unavailable, continue with a manual spec check and say validation was not run.

## File Structure

A `DESIGN.md` file has two layers:

1. YAML front matter, delimited by `---`, containing machine-readable design tokens.
2. Markdown body, using `##` sections, containing human-readable design rationale.

Minimal structure:

```md
---
version: alpha
name: Product Name
description: Short design-system summary
colors:
  primary: "#1A1C1E"
typography:
  body-md:
    fontFamily: Public Sans
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: 4px
spacing:
  md: 16px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: 12px
---

## Overview

Describe the product personality, density, audience, and emotional tone.
```

## Token Rules

- Colors are sRGB hex values such as `"#1A1C1E"`.
- Dimensions use `px`, `em`, or `rem`, such as `48px` or `1rem`.
- Token references use `{path.to.token}`, such as `{colors.primary}`.
- Typography tokens may include `fontFamily`, `fontSize`, `fontWeight`, `lineHeight`, `letterSpacing`, `fontFeature`, and `fontVariation`.
- Component tokens may include `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, and `width`.
- Component states are separate entries with related names, such as `button-primary-hover` and `button-primary-active`.

## Section Order

Sections are optional, but those present should appear in this order:

1. `Overview` or `Brand & Style`
2. `Colors`
3. `Typography`
4. `Layout` or `Layout & Spacing`
5. `Elevation & Depth` or `Elevation`
6. `Shapes`
7. `Components`
8. `Do's and Don'ts`

Unknown sections should be preserved. Duplicate parsed section headings are errors.

## Applying DESIGN.md

When implementing frontend work:

- Map token values into the project's existing styling system first: CSS variables, Tailwind config/theme, design tokens, component props, or native theme objects.
- Use the Markdown rationale to choose layout density, motion, tone, imagery, component shape, and hierarchy when tokens alone do not answer the question.
- Keep output consistent with the repo's existing frontend framework and component conventions.
- If the user's request conflicts with `DESIGN.md`, call out the conflict and follow the user's explicit request.
- Pair with `frontend-design` when the user is asking for new UI, redesigns, or visual polish.

## Creating or Updating DESIGN.md

When producing a `DESIGN.md`:

- Derive tokens from real implementation values where possible.
- Name colors semantically by role and describe their character in prose.
- Include enough typography, spacing, shape, and component guidance for another agent to implement a screen without guessing.
- Explain the "why" behind choices, not only the values.
- Keep the file useful for both humans and coding agents.

## Validation and Exports

Useful official CLI commands:

```bash
npx @google/design.md lint DESIGN.md
npx @google/design.md diff DESIGN.md DESIGN-v2.md
npx @google/design.md export --format css-tailwind DESIGN.md > theme.css
npx @google/design.md export --format json-tailwind DESIGN.md > tailwind.theme.json
npx @google/design.md export --format dtcg DESIGN.md > tokens.json
```

When reading lint output:

- Treat `error` findings as blockers for a generated or changed `DESIGN.md`.
- Treat WCAG contrast warnings as actionable for user-facing components unless the user explicitly accepts the tradeoff.
- Fix broken references before using exported tokens.
- Use `diff` before replacing an existing design system to catch regressions in token coverage or prose guidance.

## Common Pitfalls

- Do not treat the Markdown prose as decorative. It is the design rationale.
- Do not invent a generic palette if project CSS, screenshots, or brand docs already provide values.
- Do not remove unknown sections, unknown color names, or unknown typography names.
- Do not hardcode exported values into many components when the project already has theme variables.
- Do not rely on the Google CLI being installed globally; prefer `npx @google/design.md`.
