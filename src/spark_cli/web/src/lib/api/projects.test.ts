import { describe, expect, it, vi } from "vitest";
import { createProjectsApi } from "./projects";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  const authHeaders = vi.fn(() => new Headers({ Authorization: "Bearer token" }));
  const mediaFileUrl = vi.fn((path: string) => `/media?path=${encodeURIComponent(path)}`);
  const sseUrl = vi.fn((path: string) => `/sse${path}`);
  return { api: createProjectsApi(fetchJSON, authHeaders, mediaFileUrl, sseUrl), calls, sseUrl };
}

describe("projects api client", () => {
  it("keeps project and file endpoints on existing paths", async () => {
    const { api, calls } = recorder();

    await api.listWorkspaceProjects();
    await api.createWorkspaceProject("My Project", "react");
    await api.getWorkspaceFile("my project", "src/App.tsx");
    await api.listWorkspaceDir("my project", "src", true);
    await api.writeWorkspaceFile("my project", "src/App.tsx", "code");

    expect(calls).toEqual([
      { url: "/api/workspace/projects", init: undefined },
      {
        url: "/api/workspace/projects",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "My Project", template: "react" }),
        },
      },
      { url: "/api/workspace/projects/my%20project/file?path=src%2FApp.tsx", init: undefined },
      { url: "/api/workspace/projects/my%20project/list?path=src&show_hidden=true", init: undefined },
      {
        url: "/api/workspace/projects/my%20project/file?path=src%2FApp.tsx",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: "code" }),
        },
      },
    ]);
  });

  it("keeps terminal and preview endpoints on existing paths", async () => {
    const { api, calls, sseUrl } = recorder();
    const OriginalEventSource = globalThis.EventSource;
    const eventSource = vi.fn();
    globalThis.EventSource = eventSource as unknown as typeof EventSource;

    try {
      await api.runWorkspaceTerminalCommand("demo", "npm test");
      api.streamWorkspaceTerminalRun("demo", "run/1");
      await api.startWorkspacePreview("demo", { port: 5173 });
      await api.streamBrowserNavigate("demo", "http://127.0.0.1:5173");
      api.streamWorkspacePreviewEvents("demo");
      await api.listArtifacts("image", 10);
    } finally {
      globalThis.EventSource = OriginalEventSource;
    }

    expect(calls).toEqual([
      {
        url: "/api/workspace/projects/demo/terminal/runs",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: "npm test" }),
        },
      },
      {
        url: "/api/workspace/projects/demo/preview/start",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ port: 5173 }),
        },
      },
      {
        url: "/api/workspace/projects/demo/preview/stream/navigate",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: "http://127.0.0.1:5173", persistent: true }),
        },
      },
      { url: "/api/artifacts?type=image&limit=10", init: undefined },
    ]);
    expect(sseUrl).toHaveBeenCalledWith("/api/workspace/projects/demo/terminal/runs/run%2F1/stream");
    expect(sseUrl).toHaveBeenCalledWith("/api/workspace/projects/demo/preview/events");
    expect(eventSource).toHaveBeenCalledWith("/sse/api/workspace/projects/demo/terminal/runs/run%2F1/stream");
    expect(eventSource).toHaveBeenCalledWith("/sse/api/workspace/projects/demo/preview/events");
  });
});
