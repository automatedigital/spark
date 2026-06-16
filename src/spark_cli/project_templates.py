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
    # Relative POSIX path -> file contents.
    files: dict[str, str] = field(default_factory=dict)


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

## TODO (Phase 4: skill enablement)

Automatic enablement of the skills above when this template is selected is not
wired up yet. Track this under Phase 4 — for now, enable the skills you want
manually via the skills UI / config.
"""

_PRODUCTIVITY_NOTES = """# Notes

Use this file to capture tasks, ideas and meeting notes for the project.

- [ ] First task
"""


# ── Registry ────────────────────────────────────────────────────────────────

_TEMPLATES: dict[str, ProjectTemplate] = {
    "scratch": ProjectTemplate(
        id="scratch",
        label="Scratch",
        description="Empty project — start from a blank directory.",
        files={},
    ),
    "static": ProjectTemplate(
        id="static",
        label="Static website",
        description="HTML + CSS + JS starter styled with Tailwind via CDN.",
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
        files={
            "README.md": _PRODUCTIVITY_README,
            "NOTES.md": _PRODUCTIVITY_NOTES,
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
    return template_id in _TEMPLATES


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
