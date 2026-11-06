import { useEffect, useState } from "react";
import { getRoutingSettings, ROUTING_SETTINGS_SAVED_EVENT, type RoutingSettings } from "@/lib/api_routing";
import { getNestedValue, setNestedValue } from "@/lib/nested";

export function RoutingRolesEditor({ config, setConfig }: {
  config: Record<string, unknown>;
  setConfig: (updater: (config: Record<string, unknown> | null) => Record<string, unknown> | null) => void;
}) {
  const [effective, setEffective] = useState<RoutingSettings | null>(null);
  const [failed, setFailed] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const refresh = () => setRevision((value) => value + 1);
    window.addEventListener(ROUTING_SETTINGS_SAVED_EVENT, refresh);
    return () => window.removeEventListener(ROUTING_SETTINGS_SAVED_EVENT, refresh);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void getRoutingSettings(controller.signal).then((result) => {
      if (!controller.signal.aborted) { setEffective(result); setFailed(false); }
    }).catch(() => { if (!controller.signal.aborted) setFailed(true); });
    return () => controller.abort();
  }, [revision]);
  const edit = (role: string, field: string, value: string) => setConfig((draft) => draft
    ? setNestedValue(draft, `model_auto.roles.${role}.${field}`, value) : draft);
  return <section aria-label="Auto role mappings" className="space-y-3">
    <h3 className="text-sm font-semibold">Auto role mappings</h3>
    <p className="text-xs text-muted-foreground">Save changes to use these mappings for future turns and new threads. A running turn keeps its chosen route. An explicit model stays pinned until you select Auto.</p>
    <p className="text-xs text-muted-foreground">Credential presence is configuration only; availability and model capabilities remain unknown until exercised.</p>
    {failed && <p role="status">Effective routes unavailable. Saved role values remain editable.</p>}
    {["lead", "balanced", "fast", "subagent"].map((role) => <fieldset key={role} className="space-y-2 rounded-lg border border-border p-3">
      <legend className="px-1 text-sm font-medium capitalize">{role}</legend>
      {effective?.roles[role] && <p className="text-xs text-muted-foreground">Saved route: {effective.roles[role].provider || "Provider unknown"} / {effective.roles[role].model || "Model unknown"}. Credentials: {effective.roles[role].credential_presence === "present" ? "present (unverified)" : effective.roles[role].credential_presence === "unknown" ? "unknown" : "not detected"}. Capabilities: unknown.</p>}
      {([ ["provider", "Provider ID"], ["model", "Model ID"], ["base_url", "Custom endpoint"], ["api_mode", "API mode"], ["reasoning_effort", "Reasoning effort"] ] as const).map(([field, label]) => <label key={field} className="grid gap-1 text-xs">
        {role} {label}
        <input aria-label={`${role} ${label}`} className="rounded-md border border-input bg-background px-2 py-1.5" value={String(getNestedValue(config, `model_auto.roles.${role}.${field}`) ?? "")} onChange={(event) => edit(role, field, event.target.value)} />
      </label>)}
    </fieldset>)}
  </section>;
}
