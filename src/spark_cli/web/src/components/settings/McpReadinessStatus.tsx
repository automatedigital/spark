import { useEffect, useState } from "react";
import { getMcpReadiness, type McpReadiness } from "@/lib/mcpReadiness";
import { mcpApi } from "@/lib/api_mcp";
import { Button } from "@/components/ui/button";

const errors: Record<string, string> = {
  connection_failed: "Connection or discovery failed. Check the server and credentials.",
  sdk_unavailable: "The MCP SDK is unavailable.",
  auth_unsupported: "Interactive authorization is unavailable in readiness tests.",
  timeout: "The test exceeded its time limit.",
  invalid_result: "The test returned an invalid result.",
  unsupported_platform: "Safe probe cleanup is unavailable on this platform.",
  cancelled: "Configuration changed; test retired.",
};

export function McpReadinessStatus({ name }: { name: string }) {
  const [value, setValue] = useState<McpReadiness | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const read = async () => {
      try {
        const result = await getMcpReadiness();
        if (!active) return;
        const next = result.readiness[name] ?? null;
        setValue(next);
        if (next?.state === "testing") timer = setTimeout(() => void read(), 500);
      } catch {
        if (active) setError("Readiness unavailable. Retry the test explicitly.");
      }
    };
    void read();
    return () => { active = false; clearTimeout(timer); };
  }, [name, starting]);
  const test = async () => {
    setStarting(true);
    setError("");
    try {
      await mcpApi.testMcpServer(name);
    } catch {
      setError("Unable to start test. The queue may be full; retry later.");
    } finally {
      setStarting(false);
    }
  };
  return <div className="mt-2 space-y-2 text-xs text-muted-foreground">
    <p>Saved · {value?.state === "ready" ? "Verified ready" : value?.state === "testing" ? "Testing…" : value?.state === "failed" ? "Test failed" : "Verification unknown"}</p>
    {value?.last_test_at && <p>Last test: {new Date(value.last_test_at * 1000).toLocaleString()} · {value.duration_ms} ms{value.tool_count !== null ? ` · ${value.tool_count} tools` : ""}</p>}
    {value?.error && <p role="alert">{errors[value.error] ?? "Test failed."}</p>}
    {error && <p role="alert">{error}</p>}
    {value?.run_id && <p>Admin run: {value.run_id}</p>}
    <Button size="sm" disabled={starting || value?.state === "testing"} onClick={() => void test()}>{value?.state === "failed" ? "Retry" : "Test"}</Button>
  </div>;
}
