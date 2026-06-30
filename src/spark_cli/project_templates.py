"""Project starter templates.

Pure-data registry of project scaffolds. Each template declares an ``id``,
a human ``label``, a short ``description`` and a ``files`` manifest mapping
relative paths to file contents. ``materialize_template`` writes the manifest
into a target directory.

No I/O or heavy imports happen at module load time, so this is cheap to import
from API routes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProjectTemplate:
    """A project starter template (pure data)."""

    id: str
    label: str
    description: str
    project_type: str
    # Relative POSIX path -> file contents.
    files: dict[str, str] = field(default_factory=dict)
    recommended: bool = False
    available: bool = True
    package_managers: tuple[str, ...] = ("pnpm", "npm", "yarn", "bun")
    default_package_manager: str = "pnpm"
    supported_options: tuple[str, ...] = ()
    recommended_skills: tuple[str, ...] = ()


# ── Template file bodies ────────────────────────────────────────────────────

_STATIC_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Static Starter</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body class="min-h-screen bg-slate-950 text-slate-100 antialiased">
    <main class="mx-auto flex max-w-2xl flex-col items-center gap-6 px-6 py-24 text-center">
      <h1 class="text-4xl font-bold tracking-tight">Static Starter</h1>
      <p class="text-slate-400">
        A minimal HTML + CSS + JS page styled with Tailwind via CDN. Edit
        <code class="rounded bg-slate-800 px-1.5 py-0.5">index.html</code> to get going.
      </p>
      <button
        id="counter"
        class="rounded-lg bg-indigo-500 px-5 py-2.5 font-medium transition hover:bg-indigo-400"
      >
        Clicked 0 times
      </button>
    </main>
    <script src="app.js"></script>
  </body>
</html>
"""

_STATIC_STYLES_CSS = """/* Project styles. Tailwind (via CDN) handles most utilities; put custom
   rules that go beyond utilities here. */
:root {
  color-scheme: dark;
}

code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
"""

_STATIC_APP_JS = """// Minimal vanilla JS starter.
const button = document.getElementById("counter");
let count = 0;

button?.addEventListener("click", () => {
  count += 1;
  button.textContent = `Clicked ${count} time${count === 1 ? "" : "s"}`;
});
"""

_WEBAPP_PACKAGE_JSON = """{
  "name": "webapp-starter",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "lint": "eslint ."
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "@tanstack/react-router": "^1.58.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/react": "^16.0.1",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.2",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.1",
    "postcss": "^8.4.47",
    "tailwindcss": "^3.4.13",
    "typescript": "^5.6.2",
    "vite": "^5.4.8",
    "vitest": "^2.1.2"
  }
}
"""

_WEBAPP_VITE_CONFIG = """import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
"""

_WEBAPP_TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src"]
}
"""

_WEBAPP_TAILWIND_CONFIG = """/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
"""

_WEBAPP_POSTCSS_CONFIG = """export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
"""

_WEBAPP_INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Web App Starter</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""

_WEBAPP_INDEX_CSS = """@tailwind base;
@tailwind components;
@tailwind utilities;
"""

_WEBAPP_MAIN_TSX = """import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { App } from "@/App";
import "./index.css";

const rootRoute = createRootRoute({ component: App });
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <p className="text-slate-400">Edit src/App.tsx to get started.</p>,
});

const routeTree = rootRoute.addChildren([indexRoute]);
const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
"""

_WEBAPP_APP_TSX = """import { Outlet } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";

export function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-6 p-8 text-center">
      <h1 className="text-4xl font-bold tracking-tight">Web App Starter</h1>
      <p className="text-slate-500">
        Vite + React + TypeScript + TanStack Router/Query + Tailwind + shadcn/ui.
      </p>
      <Button>Get started</Button>
      <Outlet />
    </main>
  );
}
"""

# A minimal shadcn/ui-style button (the canonical shadcn starter component),
# trimmed to avoid pulling extra deps in the scaffold.
_WEBAPP_BUTTON_TSX = """import * as React from "react";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline";
};

export function Button({ className = "", variant = "default", ...props }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2";
  const variants = {
    default: "bg-slate-900 text-slate-50 hover:bg-slate-800",
    outline: "border border-slate-300 hover:bg-slate-100",
  } as const;
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}
"""

_WEBAPP_APP_TEST = """import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/ui/button";

describe("Button", () => {
  it("renders its children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeTruthy();
  });
});
"""

_WEBAPP_TEST_SETUP = """import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});
"""

_WEBAPP_README = """# Web App Starter

Vite + TypeScript + React with TanStack Router & Query, Tailwind CSS,
shadcn/ui-style components and Vitest.

## Getting started

```bash
npm install
npm run dev      # start the dev server
npm run test     # run unit tests (Vitest)
npm run build    # type-check + production build
```

## Layout

- `src/main.tsx` — app entry, router + query client wiring
- `src/App.tsx` — root component
- `src/components/ui/` — shadcn/ui-style components
- `src/App.test.tsx` — example Vitest test
"""

_WEBAPP_GITIGNORE = """node_modules
dist
*.local
.DS_Store
"""

_PRODUCTIVITY_README = """# Productivity Project

A lightweight starting point for a productivity-focused workspace.

## Helpful skills

This template is meant to pair with Spark's skill system. Useful skills for a
productivity workflow include:

- Google Workspace skills (`gws-gmail`, `gws-calendar`, `gws-tasks`,
  `gws-docs`, `gws-sheets`) for email, scheduling, tasks and documents.
- Workflow skills (`gws-workflow-weekly-digest`,
  `gws-workflow-standup-report`, `gws-workflow-meeting-prep`).
- Persona skills such as `persona-exec-assistant` and
  `persona-project-manager`.
"""

_PRODUCTIVITY_NOTES = """# Notes

Use this file to capture tasks, ideas and meeting notes for the project.

- [ ] First task
"""


def _package_json(name: str, scripts: dict[str, str], dependencies: dict[str, str], dev_dependencies: dict[str, str] | None = None) -> str:
    """Return compact package.json text for starter manifests."""
    lines = [
        "{",
        f'  "name": "{name}",',
        '  "private": true,',
        '  "version": "0.0.0",',
        '  "type": "module",',
        '  "scripts": {',
    ]
    script_items = list(scripts.items())
    for index, (key, value) in enumerate(script_items):
        comma = "," if index < len(script_items) - 1 else ""
        lines.append(f'    "{key}": "{value}"{comma}')
    lines.extend(["  },", '  "dependencies": {'])
    dep_items = list(dependencies.items())
    for index, (key, value) in enumerate(dep_items):
        comma = "," if index < len(dep_items) - 1 else ""
        lines.append(f'    "{key}": "{value}"{comma}')
    lines.append("  }")
    if dev_dependencies:
        lines[-1] += ","
        lines.append('  "devDependencies": {')
        dev_items = list(dev_dependencies.items())
        for index, (key, value) in enumerate(dev_items):
            comma = "," if index < len(dev_items) - 1 else ""
            lines.append(f'    "{key}": "{value}"{comma}')
        lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


_ASTRO_PACKAGE_JSON = _package_json(
    "astro-starter",
    {"dev": "astro dev", "build": "astro check && astro build", "preview": "astro preview"},
    {"@astrojs/check": "^0.9.4", "astro": "^5.0.0", "typescript": "^5.6.2"},
)

_ASTRO_PAGE = """---
const features = ["Content collections", "Fast static output", "Component islands"];
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width" />
    <title>Astro Starter</title>
  </head>
  <body>
    <main>
      <h1>Astro Starter</h1>
      <p>Edit <code>src/pages/index.astro</code> to begin.</p>
      <ul>
        {features.map((feature) => <li>{feature}</li>)}
      </ul>
    </main>
  </body>
</html>
"""

_ELEVENTY_PACKAGE_JSON = _package_json(
    "eleventy-starter",
    {"dev": "eleventy --serve", "build": "eleventy"},
    {"@11ty/eleventy": "^3.0.0"},
)

_ELEVENTY_CONFIG = """export default function (eleventyConfig) {
  eleventyConfig.addPassthroughCopy("src/styles.css");
  return {
    dir: {
      input: "src",
      output: "_site",
    },
  };
}
"""

_ELEVENTY_INDEX = """---
title: Eleventy Starter
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="stylesheet" href="/styles.css" />
    <title>{{ title }}</title>
  </head>
  <body>
    <main>
      <h1>{{ title }}</h1>
      <p>Edit <code>src/index.liquid</code> to begin.</p>
    </main>
  </body>
</html>
"""

_NEXT_PACKAGE_JSON = _package_json(
    "nextjs-starter",
    {"dev": "next dev", "build": "next build", "start": "next start", "lint": "next lint"},
    {"next": "^15.0.0", "react": "^19.0.0", "react-dom": "^19.0.0"},
    {
        "@types/node": "^22.0.0",
        "@types/react": "^19.0.0",
        "autoprefixer": "^10.4.20",
        "postcss": "^8.4.47",
        "tailwindcss": "^3.4.13",
        "typescript": "^5.6.2",
    },
)

_NEXT_PAGE_TSX = """export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 p-8">
      <h1 className="text-4xl font-bold">Next.js Starter</h1>
      <p className="text-slate-600">Edit app/page.tsx to begin.</p>
      <a className="inline-flex w-fit rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white" href="https://nextjs.org/docs">
        Read the docs
      </a>
    </main>
  );
}
"""

_NEXT_LAYOUT_TSX = """import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Next.js Starter",
  description: "Generated by Spark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
"""

_SVELTEKIT_PACKAGE_JSON = _package_json(
    "sveltekit-starter",
    {"dev": "vite dev", "build": "vite build", "preview": "vite preview", "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json"},
    {"@sveltejs/adapter-auto": "^3.0.0", "@sveltejs/kit": "^2.0.0", "@sveltejs/vite-plugin-svelte": "^5.0.0", "svelte": "^5.0.0", "vite": "^6.0.0"},
    {"svelte-check": "^4.0.0", "typescript": "^5.6.2"},
)

_SVELTE_CONFIG = """import adapter from "@sveltejs/adapter-auto";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter(),
  },
};
"""

_SVELTE_VITE_CONFIG = """import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [sveltekit()],
});
"""

_SVELTE_PAGE = """<script lang="ts">
  const features = ["File-based routing", "Server rendering", "Fast Vite builds"];
</script>

<main>
  <h1>SvelteKit Starter</h1>
  <p>Edit src/routes/+page.svelte to begin.</p>
  <ul>
    {#each features as feature}
      <li>{feature}</li>
    {/each}
  </ul>
</main>
"""

_NUXT_PACKAGE_JSON = _package_json(
    "nuxt-starter",
    {"dev": "nuxt dev", "build": "nuxt build", "preview": "nuxt preview"},
    {"nuxt": "^3.15.0", "vue": "^3.5.0"},
    {"typescript": "^5.6.2"},
)

_NUXT_APP = """<template>
  <main>
    <h1>Nuxt Starter</h1>
    <p>Edit app.vue to begin.</p>
  </main>
</template>
"""

_DOCS_README = """# Writing & Documentation Workspace

Use this workspace for long-form writing, documentation, notes and source assets.

## Structure

- `documents/` — drafts and final documents
- `notes/` — research notes and meeting notes
- `assets/` — images, diagrams and supporting files
"""

_RESEARCH_README = """# Research Workspace

Use this workspace to collect sources, synthesize findings and produce research outputs.

## Structure

- `research/` — working notes and synthesis
- `references/` — source PDFs, URLs and citation notes
- `images/` — figures, screenshots and visual evidence
"""

_KNOWLEDGE_BASE_README = """# AI Knowledge Base

Use this workspace for durable, structured knowledge that Spark can maintain over time.

## Structure

- `docs/` — curated documentation
- `decisions/` — architectural or project decisions
- `sources/` — imported source material
"""

_DESIGN_SYSTEM_PACKAGE_JSON = _package_json(
    "design-system-starter",
    {"dev": "vite --host 127.0.0.1", "build": "vite build", "preview": "vite preview"},
    {},
    {"vite": "^6.0.0"},
)

_DESIGN_SYSTEM_README = """# Design System Starter

A design-first workspace for visual direction, tokens and component decisions.

## Structure

- `design/brief.md` — product, audience and creative constraints
- `design/tokens.json` — color, type, spacing and radius decisions
- `design/components.md` — component inventory and interaction notes
- `src/` — lightweight token preview page
- `assets/` — reference images, exports and source files

## Recommended Spark skills

- `frontend-design` for polished UI direction and implementation
- `figma` and `figma-implement-design` for design handoff workflows
- `imagegen` for visual explorations and source imagery
- `theme-factory` for reusable palettes and artifact themes
- `excalidraw-diagram` for early flows and system sketches
"""

_DESIGN_BRIEF = """# Design Brief

## Product

- Name:
- Audience:
- Primary job to be done:
- Brand adjectives:

## Experience Goals

- First impression:
- What should feel effortless:
- What should feel distinctive:

## Constraints

- Platforms:
- Accessibility requirements:
- Existing brand or product rules:
"""

_DESIGN_COMPONENTS = """# Component Inventory

Use this file to describe components before implementation.

| Component | Purpose | States | Notes |
| --- | --- | --- | --- |
| Button | Primary actions | default, hover, focus, disabled | Define icon and loading behavior |
| Card | Group related content | default, selected, error | Keep radius and spacing consistent |
| Navigation | Move between work areas | active, collapsed | Prioritize scanability |
"""

_DESIGN_TOKENS = """{
  "color": {
    "canvas": "#f7f3ec",
    "ink": "#1f2933",
    "accent": "#146c94",
    "signal": "#d97706",
    "muted": "#d8d0c2"
  },
  "font": {
    "display": "Fraunces, Georgia, serif",
    "body": "Inter, ui-sans-serif, system-ui, sans-serif",
    "mono": "ui-monospace, SFMono-Regular, Menlo, monospace"
  },
  "space": {
    "xs": "0.5rem",
    "sm": "0.75rem",
    "md": "1rem",
    "lg": "1.5rem",
    "xl": "2.5rem"
  },
  "radius": {
    "sm": "4px",
    "md": "8px",
    "lg": "16px"
  }
}
"""

_DESIGN_PREVIEW_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Design System Preview</title>
    <link rel="stylesheet" href="/src/styles.css" />
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <p class="eyebrow">Design System</p>
        <h1>Shape the product before the product hardens.</h1>
        <p>
          Use this preview to test visual decisions from <code>design/tokens.json</code>
          and document the interaction rules that should travel with the build.
        </p>
      </section>
      <section class="swatches" aria-label="Color tokens">
        <div class="swatch canvas">Canvas</div>
        <div class="swatch ink">Ink</div>
        <div class="swatch accent">Accent</div>
        <div class="swatch signal">Signal</div>
      </section>
      <section class="components">
        <button>Primary action</button>
        <article>
          <h2>Component note</h2>
          <p>Capture states, motion, density and edge cases before implementation.</p>
        </article>
      </section>
    </main>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
"""

_DESIGN_PREVIEW_STYLES = """:root {
  color-scheme: light;
  --canvas: #f7f3ec;
  --ink: #1f2933;
  --accent: #146c94;
  --signal: #d97706;
  --muted: #d8d0c2;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--canvas);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.shell {
  display: grid;
  gap: 2rem;
  margin: 0 auto;
  max-width: 960px;
  padding: 6rem 1.5rem;
}

.hero {
  max-width: 720px;
}

.eyebrow {
  color: var(--accent);
  font-size: 0.8rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  font-family: Georgia, serif;
  font-size: clamp(3rem, 8vw, 6.5rem);
  line-height: 0.92;
  margin: 0;
}

.hero p:last-child {
  color: color-mix(in srgb, var(--ink), transparent 22%);
  font-size: 1.1rem;
  line-height: 1.7;
  max-width: 620px;
}

.swatches,
.components {
  display: grid;
  gap: 1rem;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
}

.swatch,
article {
  border: 1px solid color-mix(in srgb, var(--ink), transparent 82%);
  border-radius: 8px;
  min-height: 120px;
  padding: 1rem;
}

.canvas { background: var(--canvas); }
.ink { background: var(--ink); color: var(--canvas); }
.accent { background: var(--accent); color: white; }
.signal { background: var(--signal); color: white; }

button {
  align-self: start;
  background: var(--ink);
  border: 0;
  border-radius: 8px;
  color: var(--canvas);
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  padding: 0.85rem 1.1rem;
}
"""

_DESIGN_PREVIEW_MAIN = """console.info("Design system preview ready. Update design/tokens.json and src/styles.css as decisions settle.");
"""

_BRAND_KIT_README = """# Brand Kit Workspace

Use this workspace to develop a brand direction, collect references and prepare
handoff material.

## Structure

- `brand/voice.md` — tone, audience and messaging rules
- `brand/visual-direction.md` — color, type, imagery and composition notes
- `assets/references/` — inspiration, screenshots and source imagery
- `exports/` — shareable brand assets
"""

_BRAND_VOICE = """# Brand Voice

## Personality

- We are:
- We are not:

## Messaging

- Primary promise:
- Proof points:
- Words to use:
- Words to avoid:
"""

_BRAND_VISUAL_DIRECTION = """# Visual Direction

## Palette

- Core:
- Accent:
- Neutrals:

## Typography

- Display:
- Body:
- Mono:

## Imagery

- Subject matter:
- Lighting:
- Composition:
- Avoid:
"""

_HYPERFRAMES_README = """# HyperFrames Video Project

Use this workspace to plan and produce a HyperFrames video.

## Structure

- `frames/` — frame descriptions and generated assets
- `scripts/` — narration and shot lists
- `exports/` — rendered outputs
"""

_REMOTION_PACKAGE_JSON = _package_json(
    "remotion-starter",
    {"dev": "remotion studio", "build": "remotion render src/index.ts Main out/video.mp4"},
    {"@remotion/cli": "^4.0.0", "remotion": "^4.0.0", "react": "^18.3.1", "react-dom": "^18.3.1"},
    {"typescript": "^5.6.2"},
)

_REMOTION_INDEX = """import { registerRoot } from "remotion";
import { RemotionRoot } from "./Root";

registerRoot(RemotionRoot);
"""

_REMOTION_ROOT = """import { Composition } from "remotion";
import { Main } from "./Main";

export const RemotionRoot = () => (
  <Composition
    id="Main"
    component={Main}
    durationInFrames={150}
    fps={30}
    width={1920}
    height={1080}
  />
);
"""

_REMOTION_MAIN = """import { AbsoluteFill } from "remotion";

export function Main() {
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", background: "#111827", color: "white" }}>
      <h1>Remotion Starter</h1>
    </AbsoluteFill>
  );
}
"""

_FFMPEG_README = """# FFmpeg Workflow

Use this workspace for scriptable video processing.

## Structure

- `input/` — source media
- `scripts/` — repeatable shell scripts
- `output/` — rendered files

Run `sh scripts/example-transcode.sh input/source.mp4 output/result.mp4` after adding source media.
"""

_FFMPEG_SCRIPT = """#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 input output" >&2
  exit 1
fi

ffmpeg -i "$1" -c:v libx264 -c:a aac "$2"
"""


# ── Registry ────────────────────────────────────────────────────────────────

_TEMPLATES: dict[str, ProjectTemplate] = {
    "scratch": ProjectTemplate(
        id="scratch",
        label="Scratch",
        description="Empty project — start from a blank directory.",
        project_type="blank",
        files={},
        package_managers=(),
        default_package_manager="",
    ),
    "static": ProjectTemplate(
        id="static",
        label="Static website",
        description="HTML + CSS + JS starter styled with Tailwind via CDN.",
        project_type="static_website",
        recommended=True,
        supported_options=("init_git", "initial_commit"),
        files={
            "index.html": _STATIC_INDEX_HTML,
            "styles.css": _STATIC_STYLES_CSS,
            "app.js": _STATIC_APP_JS,
        },
    ),
    "webapp": ProjectTemplate(
        id="webapp",
        label="Web app",
        description=(
            "Vite + TypeScript + React with TanStack Router & Query, "
            "Tailwind, shadcn/ui and Vitest."
        ),
        project_type="web_application",
        recommended=True,
        supported_options=("init_git", "initial_commit", "vitest"),
        recommended_skills=("react", "typescript", "tailwind", "shadcn-ui", "github"),
        files={
            "package.json": _WEBAPP_PACKAGE_JSON,
            "vite.config.ts": _WEBAPP_VITE_CONFIG,
            "tsconfig.json": _WEBAPP_TSCONFIG,
            "tailwind.config.js": _WEBAPP_TAILWIND_CONFIG,
            "postcss.config.js": _WEBAPP_POSTCSS_CONFIG,
            "index.html": _WEBAPP_INDEX_HTML,
            ".gitignore": _WEBAPP_GITIGNORE,
            "README.md": _WEBAPP_README,
            "src/index.css": _WEBAPP_INDEX_CSS,
            "src/main.tsx": _WEBAPP_MAIN_TSX,
            "src/App.tsx": _WEBAPP_APP_TSX,
            "src/components/ui/button.tsx": _WEBAPP_BUTTON_TSX,
            "src/App.test.tsx": _WEBAPP_APP_TEST,
            "src/test/setup.ts": _WEBAPP_TEST_SETUP,
        },
    ),
    "productivity": ProjectTemplate(
        id="productivity",
        label="Productivity",
        description="Basic project with notes plus a guide to helpful skills.",
        project_type="productivity_workspace",
        recommended=True,
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("gws-docs", "gws-tasks", "gws-calendar"),
        files={
            "README.md": _PRODUCTIVITY_README,
            "NOTES.md": _PRODUCTIVITY_NOTES,
        },
    ),
    "astro": ProjectTemplate(
        id="astro",
        label="Astro",
        description="Modern static site framework for blogs, docs and marketing sites.",
        project_type="static_website",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("astro", "frontend-design"),
        files={
            "package.json": _ASTRO_PACKAGE_JSON,
            "README.md": "# Astro Starter\n\nRun `npm install` and `npm run dev` to start.\n",
            "src/pages/index.astro": _ASTRO_PAGE,
        },
    ),
    "eleventy": ProjectTemplate(
        id="eleventy",
        label="Eleventy (11ty)",
        description="Lightweight static site generator for content-focused websites.",
        project_type="static_website",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("frontend-design",),
        files={
            "package.json": _ELEVENTY_PACKAGE_JSON,
            ".eleventy.js": _ELEVENTY_CONFIG,
            "README.md": "# Eleventy Starter\n\nRun `npm install` and `npm run dev` to start.\n",
            "src/index.liquid": _ELEVENTY_INDEX,
            "src/styles.css": "body { font-family: system-ui, sans-serif; margin: 4rem; }\n",
        },
    ),
    "nextjs": ProjectTemplate(
        id="nextjs",
        label="Next.js",
        description="Full-stack React framework with TypeScript, Tailwind and shadcn/ui.",
        project_type="web_application",
        supported_options=("init_git", "initial_commit", "eslint"),
        recommended_skills=("react", "typescript", "tailwind", "shadcn-ui"),
        files={
            "package.json": _NEXT_PACKAGE_JSON,
            "README.md": "# Next.js Starter\n\nRun `npm install` and `npm run dev` to start.\n",
            "tsconfig.json": _WEBAPP_TSCONFIG.replace('"include": ["src"]', '"include": ["next-env.d.ts", "app/**/*.ts", "app/**/*.tsx", "components/**/*.ts", "components/**/*.tsx"]'),
            "tailwind.config.js": _WEBAPP_TAILWIND_CONFIG.replace("./src/**/*.{ts,tsx}", "./{app,components}/**/*.{ts,tsx}"),
            "postcss.config.js": _WEBAPP_POSTCSS_CONFIG,
            "app/page.tsx": _NEXT_PAGE_TSX,
            "app/layout.tsx": _NEXT_LAYOUT_TSX,
            "app/globals.css": "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n",
            "components/ui/button.tsx": _WEBAPP_BUTTON_TSX,
            "next-env.d.ts": "/// <reference types=\"next\" />\n/// <reference types=\"next/image-types/global\" />\n",
        },
    ),
    "sveltekit": ProjectTemplate(
        id="sveltekit",
        label="SvelteKit",
        description="Lightweight full-stack application framework with strong DX.",
        project_type="web_application",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("svelte", "typescript", "frontend-design"),
        files={
            "package.json": _SVELTEKIT_PACKAGE_JSON,
            "README.md": "# SvelteKit Starter\n\nRun `npm install` and `npm run dev` to start.\n",
            "svelte.config.js": _SVELTE_CONFIG,
            "vite.config.ts": _SVELTE_VITE_CONFIG,
            "tsconfig.json": "{\"extends\": \"./.svelte-kit/tsconfig.json\", \"compilerOptions\": {\"strict\": true}}\n",
            "src/routes/+page.svelte": _SVELTE_PAGE,
            "src/app.html": "<div>%sveltekit.body%</div>\n",
        },
    ),
    "nuxt": ProjectTemplate(
        id="nuxt",
        label="Nuxt",
        description="Vue-based full-stack application framework.",
        project_type="web_application",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("vue", "typescript", "frontend-design"),
        files={
            "package.json": _NUXT_PACKAGE_JSON,
            "README.md": "# Nuxt Starter\n\nRun `npm install` and `npm run dev` to start.\n",
            "nuxt.config.ts": "export default defineNuxtConfig({ devtools: { enabled: true } });\n",
            "app.vue": _NUXT_APP,
        },
    ),
    "docs_workspace": ProjectTemplate(
        id="docs_workspace",
        label="Writing & Documentation",
        description="Workspace layout for documents, notes and assets.",
        project_type="productivity_workspace",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("documents", "obsidian-cli"),
        files={
            "README.md": _DOCS_README,
            "documents/.gitkeep": "",
            "notes/.gitkeep": "",
            "assets/.gitkeep": "",
        },
    ),
    "research_workspace": ProjectTemplate(
        id="research_workspace",
        label="Research Workspace",
        description="Workspace layout for research, references and images.",
        project_type="productivity_workspace",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("notebooklm", "pdf", "google-drive"),
        files={
            "README.md": _RESEARCH_README,
            "research/.gitkeep": "",
            "references/.gitkeep": "",
            "images/.gitkeep": "",
        },
    ),
    "knowledge_base": ProjectTemplate(
        id="knowledge_base",
        label="AI Knowledge Base",
        description="Structured workspace for documentation and long-term knowledge.",
        project_type="productivity_workspace",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("notion-knowledge-capture", "obsidian-cli"),
        files={
            "README.md": _KNOWLEDGE_BASE_README,
            "docs/.gitkeep": "",
            "decisions/.gitkeep": "",
            "sources/.gitkeep": "",
        },
    ),
    "design_system": ProjectTemplate(
        id="design_system",
        label="Design System",
        description="Design-token workspace with a lightweight live preview.",
        project_type="design_project",
        recommended=True,
        supported_options=("init_git", "initial_commit", "design_tokens", "brand_kit", "figma_notes"),
        recommended_skills=(
            "frontend-design",
            "figma",
            "figma-implement-design",
            "imagegen",
            "theme-factory",
            "excalidraw-diagram",
        ),
        files={
            "package.json": _DESIGN_SYSTEM_PACKAGE_JSON,
            "README.md": _DESIGN_SYSTEM_README,
            "design/brief.md": _DESIGN_BRIEF,
            "design/tokens.json": _DESIGN_TOKENS,
            "design/components.md": _DESIGN_COMPONENTS,
            "index.html": _DESIGN_PREVIEW_INDEX,
            "src/styles.css": _DESIGN_PREVIEW_STYLES,
            "src/main.js": _DESIGN_PREVIEW_MAIN,
            "assets/.gitkeep": "",
        },
    ),
    "brand_kit": ProjectTemplate(
        id="brand_kit",
        label="Brand Kit",
        description="Workspace for brand voice, visual direction and handoff assets.",
        project_type="design_project",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit", "design_tokens", "brand_kit", "figma_notes"),
        recommended_skills=("frontend-design", "figma", "imagegen", "theme-factory"),
        files={
            "README.md": _BRAND_KIT_README,
            "brand/voice.md": _BRAND_VOICE,
            "brand/visual-direction.md": _BRAND_VISUAL_DIRECTION,
            "assets/references/.gitkeep": "",
            "exports/.gitkeep": "",
        },
    ),
    "hyperframes": ProjectTemplate(
        id="hyperframes",
        label="HyperFrames",
        description="Video project workspace for HyperFrames production.",
        project_type="video_project",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("hyperframes-registry",),
        files={
            "README.md": _HYPERFRAMES_README,
            "frames/.gitkeep": "",
            "scripts/.gitkeep": "",
            "exports/.gitkeep": "",
        },
    ),
    "remotion": ProjectTemplate(
        id="remotion",
        label="Remotion",
        description="React-based video project workspace.",
        project_type="video_project",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("remotion-best-practices",),
        files={
            "package.json": _REMOTION_PACKAGE_JSON,
            "README.md": "# Remotion Starter\n\nRun `npm install` and `npm run dev` to open Remotion Studio.\n",
            "src/index.ts": _REMOTION_INDEX,
            "src/Root.tsx": _REMOTION_ROOT,
            "src/Main.tsx": _REMOTION_MAIN,
        },
    ),
    "ffmpeg": ProjectTemplate(
        id="ffmpeg",
        label="FFmpeg Workflow",
        description="Scriptable video-processing workspace.",
        project_type="video_project",
        package_managers=(),
        default_package_manager="",
        supported_options=("init_git", "initial_commit"),
        recommended_skills=("transcribe",),
        files={
            "README.md": _FFMPEG_README,
            "input/.gitkeep": "",
            "output/.gitkeep": "",
            "scripts/example-transcode.sh": _FFMPEG_SCRIPT,
        },
    ),
}

# Default template id (current "create empty directory" behaviour).
DEFAULT_TEMPLATE = "scratch"


def list_templates() -> list[ProjectTemplate]:
    """Return all templates in display order."""
    return list(_TEMPLATES.values())


def get_template(template_id: str) -> ProjectTemplate | None:
    """Return the template with ``template_id`` or ``None`` if unknown."""
    return _TEMPLATES.get(template_id)


def is_valid_template(template_id: str) -> bool:
    """Return True if ``template_id`` names a known template."""
    template = _TEMPLATES.get(template_id)
    return bool(template and template.available)


def materialize_template(template_id: str, target_dir: Path) -> list[str]:
    """Write a template's files into ``target_dir``.

    Returns the list of relative paths written (empty for ``scratch``). Raises
    ``KeyError`` if ``template_id`` is unknown. Creates parent directories as
    needed. Does not overwrite pre-existing files.
    """
    template = _TEMPLATES.get(template_id)
    if template is None:
        raise KeyError(template_id)

    written: list[str] = []
    for rel_path, contents in template.files.items():
        dest = target_dir / Path(rel_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            continue
        dest.write_text(contents, encoding="utf-8")
        written.append(rel_path)
    return written
