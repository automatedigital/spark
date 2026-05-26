import { useEffect, useState } from "react";
import { Clock, Pause, Play, Plus, Trash2, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { CronJob } from "@/lib/api";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useI18n } from "@/i18n";
import { CronCardSkeleton } from "@/components/Skeleton";
import { timeUntil } from "@/lib/format";

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

function formatNextRun(iso?: string | null): string {
  if (!iso) return "—";
  return timeUntil(new Date(iso));
}

const STATUS_VARIANT: Record<string, "success" | "warning" | "destructive"> = {
  enabled: "success",
  scheduled: "success",
  paused: "warning",
  error: "destructive",
  completed: "destructive",
};

// ── Cron expression helpers ──────────────────────────────────────────────────

type Frequency = "hourly" | "daily" | "weekly" | "monthly" | "yearly" | "custom";

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function friendlyToCron(freq: Frequency, time: string, dayOfWeek: string, dayOfMonth: string, month: string): string {
  const [hStr = "9", mStr = "0"] = time.split(":");
  const h = parseInt(hStr, 10);
  const m = parseInt(mStr, 10);
  switch (freq) {
    case "hourly": return `${m} * * * *`;
    case "daily":  return `${m} ${h} * * *`;
    case "weekly": return `${m} ${h} * * ${dayOfWeek}`;
    case "monthly": return `${m} ${h} ${dayOfMonth} * *`;
    case "yearly": return `${m} ${h} ${dayOfMonth} ${month} *`;
    default: return "";
  }
}

function cronToFriendly(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, dom, mon, dow] = parts;
  if (min !== "*" && hour === "*" && dom === "*" && mon === "*" && dow === "*") return `Every hour at :${min.padStart(2, "0")}`;
  if (min !== "*" && hour !== "*" && dom === "*" && mon === "*" && dow === "*") return `Daily at ${hour}:${min.padStart(2, "0")}`;
  if (min !== "*" && hour !== "*" && dom === "*" && mon === "*" && dow !== "*") return `Weekly on ${DAYS[parseInt(dow, 10)] ?? dow} at ${hour}:${min.padStart(2, "0")}`;
  if (min !== "*" && hour !== "*" && dom !== "*" && mon === "*" && dow === "*") return `Monthly on day ${dom} at ${hour}:${min.padStart(2, "0")}`;
  if (min !== "*" && hour !== "*" && dom !== "*" && mon !== "*" && dow === "*") return `Yearly on ${MONTHS[parseInt(mon, 10) - 1] ?? mon} ${dom} at ${hour}:${min.padStart(2, "0")}`;
  return expr;
}

export default function CronPage() {
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(true);
  const { toast, showToast } = useToast();
  const { t } = useI18n();

  // New job form state
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const [deliver, setDeliver] = useState("local");
  const [creating, setCreating] = useState(false);

  // Friendly picker state
  const [freq, setFreq] = useState<Frequency>("daily");
  const [schedTime, setSchedTime] = useState("09:00");
  const [schedDow, setSchedDow] = useState("1");       // day of week (0=Sun)
  const [schedDom, setSchedDom] = useState("1");       // day of month
  const [schedMonth, setSchedMonth] = useState("1");   // month (1-12)
  const [customExpr, setCustomExpr] = useState("");

  const loadJobs = () => {
    api
      .getCronJobs()
      .then(setJobs)
      .catch(() => showToast(t.common.loading, "error"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadJobs();
  }, []);

  const resolvedSchedule = freq === "custom"
    ? customExpr.trim()
    : friendlyToCron(freq, schedTime, schedDow, schedDom, schedMonth);

  const handleCreate = async () => {
    if (!prompt.trim() || !resolvedSchedule) {
      showToast(`${t.cron.prompt} & ${t.cron.schedule} required`, "error");
      return;
    }
    setCreating(true);
    try {
      await api.createCronJob({
        prompt: prompt.trim(),
        schedule: resolvedSchedule,
        name: name.trim() || undefined,
        deliver,
      });
      showToast(t.common.create + " ✓", "success");
      setPrompt("");
      setName("");
      setDeliver("local");
      setFreq("daily");
      setSchedTime("09:00");
      setCustomExpr("");
      loadJobs();
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setCreating(false);
    }
  };

  const handlePauseResume = async (job: CronJob) => {
    try {
      const isPaused = job.state === "paused";
      if (isPaused) {
        await api.resumeCronJob(job.id);
        showToast(`${t.cron.resume}: "${job.name || job.prompt.slice(0, 30)}"`, "success");
      } else {
        await api.pauseCronJob(job.id);
        showToast(`${t.cron.pause}: "${job.name || job.prompt.slice(0, 30)}"`, "success");
      }
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleTrigger = async (job: CronJob) => {
    try {
      await api.triggerCronJob(job.id);
      showToast(`${t.cron.triggerNow}: "${job.name || job.prompt.slice(0, 30)}"`, "success");
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  const handleDelete = async (job: CronJob) => {
    try {
      await api.deleteCronJob(job.id);
      showToast(`${t.common.delete}: "${job.name || job.prompt.slice(0, 30)}"`, "success");
      loadJobs();
    } catch (e) {
      showToast(`${t.status.error}: ${e}`, "error");
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col gap-4 px-1 py-2">
        <CronCardSkeleton />
        <CronCardSkeleton />
        <CronCardSkeleton />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Toast toast={toast} />

      {/* Create new job form */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4" />
            {t.cron.newJob}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="cron-name">{t.cron.nameOptional}</Label>
              <Input
                id="cron-name"
                placeholder={t.cron.namePlaceholder}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="grid gap-2">
              <Label htmlFor="cron-prompt">{t.cron.prompt}</Label>
              <textarea
                id="cron-prompt"
                className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                placeholder={t.cron.promptPlaceholder}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            {/* Friendly schedule picker */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="cron-freq">{t.cron.schedule}</Label>
                <Select
                  id="cron-freq"
                  value={freq}
                  onValueChange={(v) => setFreq(v as Frequency)}
                >
                  <option value="hourly">Every Hour</option>
                  <option value="daily">Every Day</option>
                  <option value="weekly">Every Week</option>
                  <option value="monthly">Every Month</option>
                  <option value="yearly">Every Year</option>
                  <option value="custom">Custom (cron expression)</option>
                </Select>
              </div>

              {freq !== "custom" && (
                <div className="grid gap-2">
                  <Label htmlFor="cron-time">Time</Label>
                  <input
                    id="cron-time"
                    type="time"
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                    value={schedTime}
                    onChange={(e) => setSchedTime(e.target.value)}
                  />
                </div>
              )}

              {freq === "weekly" && (
                <div className="grid gap-2">
                  <Label htmlFor="cron-dow">Day of Week</Label>
                  <Select id="cron-dow" value={schedDow} onValueChange={setSchedDow}>
                    {DAYS.map((d, i) => <option key={i} value={String(i)}>{d}</option>)}
                  </Select>
                </div>
              )}

              {(freq === "monthly" || freq === "yearly") && (
                <div className="grid gap-2">
                  <Label htmlFor="cron-dom">Day of Month</Label>
                  <Select id="cron-dom" value={schedDom} onValueChange={setSchedDom}>
                    {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
                      <option key={d} value={String(d)}>{d}</option>
                    ))}
                  </Select>
                </div>
              )}

              {freq === "yearly" && (
                <div className="grid gap-2">
                  <Label htmlFor="cron-month">Month</Label>
                  <Select id="cron-month" value={schedMonth} onValueChange={setSchedMonth}>
                    {MONTHS.map((m, i) => <option key={i} value={String(i + 1)}>{m}</option>)}
                  </Select>
                </div>
              )}

              {freq === "custom" && (
                <div className="grid gap-2">
                  <Label htmlFor="cron-schedule">Cron Expression</Label>
                  <Input
                    id="cron-schedule"
                    placeholder="0 9 * * *"
                    value={customExpr}
                    onChange={(e) => setCustomExpr(e.target.value)}
                  />
                </div>
              )}
            </div>

            {resolvedSchedule && freq !== "custom" && (
              <p className="text-xs text-muted-foreground">
                Schedule: <code className="font-mono">{resolvedSchedule}</code>
                {" — "}{cronToFriendly(resolvedSchedule)}
              </p>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label htmlFor="cron-deliver">{t.cron.deliverTo}</Label>
                <Select
                  id="cron-deliver"
                  value={deliver}
                  onValueChange={(v) => setDeliver(v)}
                >
                  <option value="local">{t.cron.delivery.local}</option>
                  <option value="telegram">{t.cron.delivery.telegram}</option>
                  <option value="discord">{t.cron.delivery.discord}</option>
                  <option value="slack">{t.cron.delivery.slack}</option>
                  <option value="email">{t.cron.delivery.email}</option>
                </Select>
              </div>

              <div className="flex items-end">
                <Button onClick={handleCreate} disabled={creating} className="w-full">
                  <Plus className="h-3 w-3" />
                  {creating ? t.common.creating : t.common.create}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Jobs list */}
      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          <Clock className="h-4 w-4" />
          {t.cron.scheduledJobs} ({jobs.length})
        </h2>

        {jobs.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              {t.cron.noJobs}
            </CardContent>
          </Card>
        )}

        {jobs.map((job) => (
          <Card key={job.id}>
            <CardContent className="flex items-center gap-4 py-4">
              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm truncate">
                    {job.name || job.prompt.slice(0, 60) + (job.prompt.length > 60 ? "..." : "")}
                  </span>
                  <Badge variant={STATUS_VARIANT[job.state] ?? "secondary"}>
                    {job.state}
                  </Badge>
                  {job.deliver && job.deliver !== "local" && (
                    <Badge variant="outline">{job.deliver}</Badge>
                  )}
                </div>
                {/* Prompt preview — always shown when there's a name; avoids duplicate when name IS the prompt */}
                {job.name && (
                  <p className="text-xs text-muted-foreground mb-1.5 line-clamp-2 leading-relaxed">
                    {job.prompt.slice(0, 100)}{job.prompt.length > 100 ? "…" : ""}
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span className="font-mono" title={job.schedule_display}>{cronToFriendly(job.schedule_display)}</span>
                  <span>{t.cron.last}: {formatTime(job.last_run_at)}</span>
                  <span
                    className={job.next_run_at && new Date(job.next_run_at) < new Date() ? "text-destructive" : ""}
                    title={job.next_run_at ? new Date(job.next_run_at).toLocaleString() : undefined}
                  >
                    {t.cron.next}: {formatNextRun(job.next_run_at)}
                  </span>
                </div>
                {job.last_error && (
                  <p className="text-xs text-destructive mt-1">{job.last_error}</p>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1 shrink-0">
                <Button
                  variant="ghost"
                  size="icon"
                  title={job.state === "paused" ? t.cron.resume : t.cron.pause}
                  aria-label={job.state === "paused" ? t.cron.resume : t.cron.pause}
                  onClick={() => handlePauseResume(job)}
                >
                  {job.state === "paused" ? (
                    <Play className="h-4 w-4 text-success" />
                  ) : (
                    <Pause className="h-4 w-4 text-warning" />
                  )}
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  title={t.cron.triggerNow}
                  aria-label={t.cron.triggerNow}
                  onClick={() => handleTrigger(job)}
                >
                  <Zap className="h-4 w-4" />
                </Button>

                <Button
                  variant="ghost"
                  size="icon"
                  title={t.common.delete}
                  aria-label={t.common.delete}
                  onClick={() => handleDelete(job)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
