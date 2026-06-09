import { useEffect, useMemo, useState } from "react";
import { ChevronRight, ExternalLink, Save, Search } from "lucide-react";
import { api, openExternal } from "@/lib/api";
import type { MessagingField, MessagingPlatform } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Switch } from "@/components/ui/switch";

/* ------------------------------------------------------------------ */
/*  Platform icon: brand-colored chip with an initial                  */
/* ------------------------------------------------------------------ */

const BRAND: Record<string, { bg: string; fg: string; initial?: string }> = {
  telegram: { bg: "#229ED9", fg: "#fff", initial: "T" },
  discord: { bg: "#5865F2", fg: "#fff", initial: "D" },
  slack: { bg: "#4A154B", fg: "#fff", initial: "S" },
  mattermost: { bg: "#0058CC", fg: "#fff", initial: "M" },
  matrix: { bg: "#0DBD8B", fg: "#fff", initial: "M" },
  whatsapp: { bg: "#25D366", fg: "#fff", initial: "W" },
  signal: { bg: "#3A76F0", fg: "#fff", initial: "S" },
  bluebubbles: { bg: "#34C759", fg: "#fff", initial: "B" },
  homeassistant: { bg: "#18BCF2", fg: "#fff", initial: "H" },
  email: { bg: "#EA4335", fg: "#fff", initial: "E" },
  sms: { bg: "#F22F46", fg: "#fff", initial: "S" },
  dingtalk: { bg: "#0089FF", fg: "#fff", initial: "D" },
  feishu: { bg: "#3370FF", fg: "#fff", initial: "F" },
  wecom: { bg: "#07C160", fg: "#fff", initial: "W" },
  wecom_callback: { bg: "#07C160", fg: "#fff", initial: "W" },
  weixin: { bg: "#09B83E", fg: "#fff", initial: "W" },
  qqbot: { bg: "#EB1923", fg: "#fff", initial: "Q" },
  webhook: { bg: "#52525B", fg: "#fff", initial: "W" },
  api_server: { bg: "#52525B", fg: "#fff", initial: "A" },
};

function PlatformIcon({ id, name }: { id: string; name: string }) {
  const brand = BRAND[id] ?? { bg: "#3F3F46", fg: "#fff" };
  return (
    <span
      className="grid h-6 w-6 shrink-0 place-items-center rounded-md text-[11px] font-bold"
      style={{ backgroundColor: brand.bg, color: brand.fg }}
      aria-hidden="true"
    >
      {brand.initial ?? name.charAt(0).toUpperCase()}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Field input                                                        */
/* ------------------------------------------------------------------ */

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: MessagingField;
  value: string;
  onChange: (v: string) => void;
}) {
  if (field.type === "bool") {
    const on = ["1", "true", "yes", "on"].includes(value.trim().toLowerCase());
    return (
      <div className="flex items-start justify-between gap-8 py-4">
        <div className="min-w-0 max-w-md">
          <div className="text-[13px] font-semibold text-foreground">{field.label}</div>
          {field.description && (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{field.description}</p>
          )}
        </div>
        <Switch checked={on} onCheckedChange={(v) => onChange(v ? "true" : "false")} aria-label={field.label} />
      </div>
    );
  }
  return (
    <div className="flex items-start justify-between gap-8 py-4">
      <div className="min-w-0 max-w-md">
        <div className="text-[13px] font-semibold text-foreground">{field.label}</div>
        {field.description && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{field.description}</p>
        )}
      </div>
      <input
        type={field.type === "secret" && !value ? "password" : "text"}
        className="h-8 w-56 shrink-0 rounded-md border border-border bg-transparent px-2.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground/70 focus:border-foreground/30"
        placeholder={field.placeholder || field.label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Detail pane                                                        */
/* ------------------------------------------------------------------ */

function runtimeChip(p: MessagingPlatform, gatewayRunning: boolean): string {
  if (!gatewayRunning) return "Messaging gateway stopped";
  const rt = p.runtime as { state?: string } | null;
  return rt?.state ? `Gateway: ${rt.state}` : "Messaging gateway running";
}

function PlatformDetail({
  platform,
  gatewayRunning,
  onSaved,
}: {
  platform: MessagingPlatform;
  gatewayRunning: boolean;
  onSaved: (updated: MessagingPlatform) => void;
}) {
  const [enabled, setEnabled] = useState(platform.enabled);
  const [values, setValues] = useState<Record<string, string>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();

  const fieldValue = (f: MessagingField) => values[f.key] ?? f.value;
  const setField = (key: string, v: string) => setValues((prev) => ({ ...prev, [key]: v }));

  const dirty = Object.keys(values).length > 0 || enabled !== platform.enabled;

  const save = async () => {
    setSaving(true);
    try {
      const updated = await api.updateMessagingPlatform(platform.id, {
        enabled,
        values,
      });
      onSaved(updated);
      setValues({});
      const restarted = updated.restart?.ok ? " Gateway restart requested." : "";
      showToast(`${platform.name} saved.${restarted}`, "success");
    } catch (e) {
      showToast(`Failed to save: ${e instanceof Error ? e.message : e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const sections: Array<{ title: string; fields: MessagingField[] }> = [
    { title: "Required", fields: platform.fields.required },
    { title: "Recommended", fields: platform.fields.recommended },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Toast toast={toast} />
      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto max-w-2xl">
          {/* Header */}
          <div className="flex items-start gap-3">
            <PlatformIcon id={platform.id} name={platform.name} />
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-foreground">{platform.name}</h1>
              <p className="mt-1 text-[13px] text-muted-foreground">{platform.description}</p>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full bg-foreground/6 px-2.5 py-0.5 text-[11px] font-medium ${
                    enabled ? "text-emerald-400" : "text-muted-foreground"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${enabled ? "bg-emerald-400" : "bg-muted-foreground/60"}`} />
                  {enabled ? "Enabled" : "Disabled"}
                </span>
                {!platform.configured && (
                  <span className="rounded-full bg-foreground/6 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                    Needs setup
                  </span>
                )}
                <span className="rounded-full bg-foreground/6 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
                  {runtimeChip(platform, gatewayRunning)}
                </span>
              </div>
            </div>
          </div>

          {/* Get your credentials */}
          {platform.help_text && (
            <section className="mt-7">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Get your credentials
              </h2>
              <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">{platform.help_text}</p>
              {platform.setup_guide_url && (
                <button
                  type="button"
                  className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-foreground underline underline-offset-4 hover:opacity-80"
                  onClick={() => openExternal(platform.setup_guide_url)}
                >
                  Open setup guide <ExternalLink className="h-3.5 w-3.5" />
                </button>
              )}
            </section>
          )}

          {/* Required / Recommended */}
          {sections.map(
            ({ title, fields }) =>
              fields.length > 0 && (
                <section key={title} className="mt-7">
                  <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {title}
                  </h2>
                  <div className="divide-y divide-border/40">
                    {fields.map((f) => (
                      <FieldRow key={f.key} field={f} value={fieldValue(f)} onChange={(v) => setField(f.key, v)} />
                    ))}
                  </div>
                </section>
              ),
          )}

          {/* Advanced (collapsible) */}
          {platform.fields.advanced.length > 0 && (
            <section className="mt-7">
              <button
                type="button"
                className="flex w-full items-center justify-between text-left"
                onClick={() => setAdvancedOpen((o) => !o)}
              >
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  Advanced ({platform.fields.advanced.length})
                </h2>
                <ChevronRight
                  className={`h-4 w-4 text-muted-foreground transition-transform ${advancedOpen ? "rotate-90" : ""}`}
                />
              </button>
              {advancedOpen && (
                <div className="divide-y divide-border/40">
                  {platform.fields.advanced.map((f) => (
                    <FieldRow key={f.key} field={f} value={fieldValue(f)} onChange={(v) => setField(f.key, v)} />
                  ))}
                </div>
              )}
            </section>
          )}
        </div>
      </div>

      {/* Footer: enable toggle + save */}
      <div className="flex items-center justify-between gap-4 border-t border-border/50 px-8 py-3">
        <div className="flex items-center gap-2.5">
          <Switch checked={enabled} onCheckedChange={setEnabled} aria-label={`Enable ${platform.name}`} />
          <span className="text-[12px] text-muted-foreground">{enabled ? "Enabled" : "Disabled"}</span>
        </div>
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={save}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-foreground/10 px-3 text-[12px] font-medium text-foreground transition hover:bg-foreground/15 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Save className="h-3.5 w-3.5" />
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page: master list + detail                                         */
/* ------------------------------------------------------------------ */

export default function MessagingPage() {
  const [platforms, setPlatforms] = useState<MessagingPlatform[]>([]);
  const [gatewayRunning, setGatewayRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    api
      .listMessagingPlatforms()
      .then((res) => {
        setPlatforms(res.platforms);
        setGatewayRunning(res.gateway_running);
        setSelectedId((cur) => cur ?? res.platforms[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return platforms.filter(
      (p) => !q || p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q),
    );
  }, [platforms, search]);

  const selected = platforms.find((p) => p.id === selectedId) ?? null;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center">
        <p className="max-w-sm text-sm text-muted-foreground">Failed to load messaging platforms: {error}</p>
      </div>
    );
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-[260px_1fr]">
      {/* Master list */}
      <div className="flex min-h-0 flex-col border-r border-border/50">
        <div className="relative px-3 pb-2 pt-4">
          <Search className="pointer-events-none absolute left-5 top-1/2 mt-1 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className="h-8 w-full rounded-md bg-transparent pl-7 pr-2 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:bg-foreground/5"
            placeholder="Search messaging..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {filtered.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setSelectedId(p.id)}
              className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left transition ${
                selectedId === p.id
                  ? "bg-foreground/8 text-foreground"
                  : "text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
              }`}
            >
              <PlatformIcon id={p.id} name={p.name} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{p.name}</span>
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                  p.enabled && p.configured ? "bg-emerald-400" : "bg-muted-foreground/30"
                }`}
                aria-hidden="true"
              />
            </button>
          ))}
          {filtered.length === 0 && (
            <p className="px-3 py-8 text-center text-xs text-muted-foreground">No platforms match.</p>
          )}
        </div>
      </div>

      {/* Detail */}
      {selected ? (
        <PlatformDetail
          key={selected.id}
          platform={selected}
          gatewayRunning={gatewayRunning}
          onSaved={(updated) =>
            setPlatforms((prev) => prev.map((p) => (p.id === updated.id ? { ...p, ...updated } : p)))
          }
        />
      ) : (
        <div className="flex items-center justify-center text-sm text-muted-foreground">
          Select a platform to configure.
        </div>
      )}
    </div>
  );
}
