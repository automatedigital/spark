import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  Cloud,
  Copy,
  Cpu,
  ExternalLink,
  Globe,
  KeyRound,
  Loader2,
  Network,
  Server,
  Sparkles,
} from "lucide-react";
import { api, openExternal, type OAuthStartResponse } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  onComplete: () => void;
}

type ProviderId =
  | "anthropic"
  | "openai-codex"
  | "openai"
  | "google"
  | "openrouter"
  | "ollama"
  | "custom";

type AuthKind = "oauth" | "apikey" | "ollama";

interface ProviderMeta {
  id: ProviderId;
  name: string;
  tagline: string;
  icon: typeof Cloud;
  auth: AuthKind;
  /** OAuth provider id passed to the OAuth endpoints (for auth: "oauth"). */
  oauthId?: string;
  /** Env var the API key is stored under (for auth: "apikey"). */
  envVar?: string;
  /** Default model written to config. */
  defaultModel: string;
  /** Placeholder hint for the API-key field. */
  keyPlaceholder?: string;
  /** Provider key page (shown below the key field). */
  keyUrl?: string;
}

const PROVIDERS: ProviderMeta[] = [
  {
    id: "anthropic",
    name: "Anthropic (Claude)",
    tagline: "Best for coding and reasoning",
    icon: Sparkles,
    auth: "oauth",
    oauthId: "anthropic",
    defaultModel: "claude-sonnet-4-6",
  },
  {
    id: "openai-codex",
    name: "OpenAI Codex",
    tagline: "Log in with your ChatGPT account",
    icon: Cloud,
    auth: "oauth",
    oauthId: "openai-codex",
    defaultModel: "gpt-5.4",
  },
  {
    id: "openai",
    name: "OpenAI",
    tagline: "GPT-4o, o3 via API key",
    icon: Cloud,
    auth: "apikey",
    envVar: "OPENAI_API_KEY",
    defaultModel: "gpt-4o",
    keyPlaceholder: "sk-…",
    keyUrl: "https://platform.openai.com/api-keys",
  },
  {
    id: "google",
    name: "Google",
    tagline: "Gemini 2.5 Pro/Flash",
    icon: Globe,
    auth: "apikey",
    envVar: "GOOGLE_API_KEY",
    defaultModel: "gemini-2.5-flash",
    keyPlaceholder: "AIza…",
    keyUrl: "https://aistudio.google.com/app/apikey",
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    tagline: "Access 200+ models with one key",
    icon: Network,
    auth: "apikey",
    envVar: "OPENROUTER_API_KEY",
    defaultModel: "anthropic/claude-sonnet-4-6",
    keyPlaceholder: "sk-or-…",
    keyUrl: "https://openrouter.ai/keys",
  },
  {
    id: "ollama",
    name: "Ollama",
    tagline: "Run models locally, no API key needed",
    icon: Server,
    auth: "ollama",
    defaultModel: "llama3.3",
  },
  {
    id: "custom",
    name: "Other / Custom",
    tagline: "Any OpenAI-compatible endpoint",
    icon: Cpu,
    auth: "apikey",
    envVar: "OPENAI_API_KEY",
    defaultModel: "",
    keyPlaceholder: "sk-… (optional)",
  },
];

function maskKey(key: string): string {
  if (!key) return "";
  if (key.length <= 8) return "•".repeat(key.length);
  return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

/** Merge the chosen provider + default model into the saved config. */
async function persistModelConfig(
  provider: ProviderId,
  defaultModel: string,
  extra: Record<string, unknown> = {},
) {
  const current = (await api.getConfig()) as Record<string, unknown>;
  const model = { ...((current.model as Record<string, unknown>) ?? {}) };
  model.provider = provider;
  if (defaultModel) model.model = defaultModel;
  Object.assign(model, extra);
  await api.saveConfig({ ...current, model });
  if (defaultModel) {
    try {
      await api.setSmartModel(defaultModel);
    } catch {
      // setSmartModel is best-effort; config already holds the model
    }
  }
}

function StepDots({ step }: { step: number }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {[1, 2, 3, 4, 5, 6].map((n) => (
        <span
          key={n}
          className={`h-2 w-2 rounded-full transition-colors ${
            n === step
              ? "bg-primary"
              : n < step
              ? "bg-primary/40"
              : "bg-border"
          }`}
          aria-hidden="true"
        />
      ))}
    </div>
  );
}

/** Inline OAuth panel — same logic as OAuthLoginModal, no modal chrome. */
function InlineOAuth({
  oauthId,
  providerName,
  onSuccess,
  onError,
}: {
  oauthId: string;
  providerName: string;
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  type Phase =
    | "starting"
    | "awaiting_user"
    | "submitting"
    | "polling"
    | "approved"
    | "error";
  const [phase, setPhase] = useState<Phase>("starting");
  const [start, setStart] = useState<OAuthStartResponse | null>(null);
  const [pkceCode, setPkceCode] = useState("");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [codeCopied, setCodeCopied] = useState(false);
  const isMounted = useRef(true);
  const pollTimer = useRef<number | null>(null);
  const verificationOpened = useRef(false);

  // Open the provider verification page once we actually have a user code.
  const openVerificationOnce = (url: string) => {
    if (verificationOpened.current) return;
    verificationOpened.current = true;
    void openExternal(url);
  };

  const begin = () => {
    setErrorMsg(null);
    setPkceCode("");
    setPhase("starting");
    verificationOpened.current = false;
    api
      .startOAuthLogin(oauthId)
      .then((resp) => {
        if (!isMounted.current) return;
        setStart(resp);
        setPhase(resp.flow === "device_code" ? "polling" : "awaiting_user");
        if (resp.flow === "pkce") {
          void openExternal(resp.auth_url);
        } else if (resp.user_code) {
          // Code already available (OpenAI responded fast).
          openVerificationOnce(resp.verification_url);
        }
        // device_code with no user_code yet: stay in "polling"; the poll loop
        // will surface the code once OpenAI's slow call returns.
      })
      .catch((e) => {
        if (!isMounted.current) return;
        setPhase("error");
        setErrorMsg(`Failed to start login: ${e}`);
      });
  };

  useEffect(() => {
    isMounted.current = true;
    begin();
    return () => {
      isMounted.current = false;
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Device-code: poll every 2s
  useEffect(() => {
    if (!start || start.flow !== "device_code" || phase !== "polling") return;
    const sid = start.session_id;
    pollTimer.current = window.setInterval(async () => {
      try {
        const resp = await api.pollOAuthSession(oauthId, sid);
        if (!isMounted.current) return;
        // Surface the user code the moment the slow device-auth call returns.
        if (resp.user_code) {
          setStart((prev) =>
            prev && prev.flow === "device_code" && !prev.user_code
              ? {
                  ...prev,
                  user_code: resp.user_code as string,
                  verification_url:
                    resp.verification_url || prev.verification_url,
                }
              : prev,
          );
          openVerificationOnce(resp.verification_url || start.verification_url);
        }
        if (resp.status === "approved") {
          setPhase("approved");
          if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
          window.setTimeout(() => isMounted.current && onSuccess(), 800);
        } else if (resp.status !== "pending") {
          setPhase("error");
          setErrorMsg(resp.error_message || `Login ${resp.status}`);
          if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
        }
      } catch (e) {
        if (!isMounted.current) return;
        setPhase("error");
        setErrorMsg(`Polling failed: ${e}`);
        if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
      }
    }, 2000);
    return () => {
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current);
    };
  }, [start, phase, oauthId, onSuccess]);

  const handleSubmitPkceCode = async () => {
    if (!start || start.flow !== "pkce") return;
    if (!pkceCode.trim()) return;
    setPhase("submitting");
    setErrorMsg(null);
    try {
      const resp = await api.submitOAuthCode(oauthId, start.session_id, pkceCode.trim());
      if (!isMounted.current) return;
      if (resp.ok && resp.status === "approved") {
        setPhase("approved");
        window.setTimeout(() => isMounted.current && onSuccess(), 800);
      } else {
        setPhase("error");
        setErrorMsg(resp.message || "Token exchange failed");
      }
    } catch (e) {
      if (!isMounted.current) return;
      setPhase("error");
      setErrorMsg(`Submit failed: ${e}`);
    }
  };

  const copyUserCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code);
      setCodeCopied(true);
      window.setTimeout(() => isMounted.current && setCodeCopied(false), 1500);
    } catch {
      onError("Clipboard write failed");
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {phase === "starting" && (
        <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Initiating login…
        </div>
      )}

      {start?.flow === "pkce" && phase === "awaiting_user" && (
        <>
          <ol className="list-inside list-decimal space-y-2 text-sm text-muted-foreground">
            <li>A browser tab opened to authorize {providerName}.</li>
            <li>Approve access, then copy the code shown.</li>
            <li>Paste it below and continue.</li>
          </ol>
          <div className="flex flex-col gap-2">
            <Input
              type="password"
              value={pkceCode}
              onChange={(e) => setPkceCode(e.target.value)}
              placeholder="Paste authorization code"
              onKeyDown={(e) => e.key === "Enter" && handleSubmitPkceCode()}
              autoFocus
            />
            <div className="flex items-center justify-between gap-2">
              <a
                href={(start as Extract<OAuthStartResponse, { flow: "pkce" }>).auth_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" />
                Re-open authorization page
              </a>
              <Button onClick={handleSubmitPkceCode} disabled={!pkceCode.trim()} size="sm">
                Submit code
              </Button>
            </div>
          </div>
        </>
      )}

      {phase === "submitting" && (
        <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Exchanging code…
        </div>
      )}

      {start?.flow === "device_code" &&
        phase === "polling" &&
        (() => {
          const dc = start as Extract<OAuthStartResponse, { flow: "device_code" }>;
          if (!dc.user_code) {
            // Code not back yet — OpenAI's device-auth endpoint can take a
            // minute or more. Keep the user informed instead of failing.
            return (
              <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Requesting a sign-in code from OpenAI… this can take up to a
                minute.
              </div>
            );
          }
          return (
            <>
              <p className="text-sm text-muted-foreground">
                Enter this code on the page that just opened:
              </p>
              <div className="flex items-center justify-between gap-2 border border-border bg-secondary/30 p-4">
                <code className="font-mono text-2xl tracking-widest text-foreground">
                  {dc.user_code}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => copyUserCode(dc.user_code as string)}
                >
                  {codeCopied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                </Button>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void openExternal(dc.verification_url)}
                className="w-full gap-2"
              >
                <ExternalLink className="h-3 w-3" />
                Open sign-in page
              </Button>
              <div className="flex items-center gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Waiting for authorization…
              </div>
            </>
          );
        })()}

      {phase === "approved" && (
        <div className="flex items-center gap-3 py-6 text-sm text-success">
          <Check className="h-5 w-5" />
          Connected!
        </div>
      )}

      {phase === "error" && (
        <>
          <div className="border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {errorMsg || "Login failed"}
          </div>
          <div className="flex justify-end">
            <Button size="sm" onClick={begin}>
              Retry
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

export function OnboardingWizard({ onComplete }: Props) {
  const [step, setStep] = useState(1);
  const [provider, setProvider] = useState<ProviderMeta | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("http://localhost:11434");
  const [customModel, setCustomModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedSummary, setSavedSummary] = useState<string>("");
  const [agentName, setAgentName] = useState("");
  const [skillsMode, setSkillsMode] = useState<"recommended" | "minimal" | "none">("recommended");

  const chooseProvider = (p: ProviderMeta) => {
    setProvider(p);
    setApiKey("");
    setCustomModel("");
    setBaseUrl("http://localhost:11434");
    setError(null);
    setStep(3);
  };

  const goBackToProviders = () => {
    setProvider(null);
    setError(null);
    setStep(2);
  };

  const finish = (summary: string) => {
    setSavedSummary(summary);
    setStep(4);
  };

  const handleNameContinue = async () => {
    setSaving(true);
    setError(null);
    try {
      const name = agentName.trim();
      if (name) {
        const current = (await api.getConfig()) as Record<string, unknown>;
        const agent = { ...((current.agent as Record<string, unknown>) ?? {}) };
        agent.name = name;
        await api.saveConfig({ ...current, agent });
      }
      setStep(5);
    } catch (e) {
      setError(`Could not save: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleSkillsContinue = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.setupOnboardingSkills(skillsMode);
      setStep(6);
    } catch (e) {
      setError(`Could not set up skills: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleApiKeyContinue = async () => {
    if (!provider) return;
    const isCustom = provider.id === "custom";
    if (!isCustom && !apiKey.trim()) {
      setError("Please paste your API key.");
      return;
    }
    if (isCustom && !customModel.trim()) {
      setError("Please enter a model name.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (apiKey.trim() && provider.envVar) {
        await api.setEnvVar(provider.envVar, apiKey.trim());
      }
      const modelName = isCustom ? customModel.trim() : provider.defaultModel;
      const extra: Record<string, unknown> = {};
      if (isCustom && baseUrl.trim()) extra.base_url = baseUrl.trim();
      await persistModelConfig(provider.id, modelName, extra);
      finish(
        apiKey.trim()
          ? `${provider.name} · key ${maskKey(apiKey.trim())}`
          : `${provider.name} · ${modelName}`,
      );
    } catch (e) {
      setError(`Could not save: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleOllamaContinue = async () => {
    if (!provider) return;
    if (!baseUrl.trim()) {
      setError("Please enter the Ollama base URL.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await persistModelConfig(provider.id, provider.defaultModel, {
        base_url: baseUrl.trim(),
      });
      finish(`${provider.name} · ${baseUrl.trim()}`);
    } catch (e) {
      setError(`Could not save: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const handleOAuthSuccess = async () => {
    if (!provider) return;
    try {
      await persistModelConfig(provider.id, provider.defaultModel);
    } catch {
      // Config save is best-effort; auth credentials are already stored.
    }
    finish(`${provider.name} · signed in`);
  };

  const openSpark = () => {
    const key =
      typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
        ? "spark-desktop-onboarding-complete"
        : "spark-onboarding-complete";
    localStorage.setItem(key, "true");
    localStorage.setItem("spark-onboarding-complete", "true");
    onComplete();
  };

  return (
    <div className="fixed inset-0 z-[200] flex flex-col items-center overflow-y-auto bg-background text-foreground">
      <div className="noise-overlay" />
      <div className="warm-glow" />
      <div
        className="relative z-2 my-auto w-full max-w-lg px-5 py-10"
        key={step}
        style={{ animation: "fade-in 200ms ease-out" }}
      >
        <div className="mb-8">
          <StepDots step={step} />
        </div>

        <div className="border border-border bg-card/90 p-7 shadow-2xl sm:p-9">
          {/* ── Step 1 — Welcome ── */}
          {step === 1 && (
            <div className="flex flex-col items-center gap-5 text-center">
              <img
                src="/icon_small-dark.png"
                alt=""
                aria-hidden="true"
                className="h-16 w-16 object-contain"
                draggable={false}
              />
              <h1 className="text-2xl font-semibold tracking-tight">
                Let's get Spark set up
              </h1>
              <p className="max-w-sm text-sm leading-6 text-muted-foreground">
                Spark is your local AI agent — it chats, runs tools, manages tasks, and
                automates your workflows. First, connect the AI provider you'd like it to use.
              </p>
              <Button className="mt-2 w-full" size="lg" onClick={() => setStep(2)}>
                Get started
              </Button>
            </div>
          )}

          {/* ── Step 2 — Choose provider ── */}
          {step === 2 && (
            <div className="flex flex-col gap-5">
              <div className="text-center">
                <h1 className="text-xl font-semibold tracking-tight">
                  Which AI provider do you use?
                </h1>
              </div>
              <div className="flex flex-col gap-2">
                {PROVIDERS.map((p) => {
                  const Icon = p.icon;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => chooseProvider(p)}
                      className="group flex items-center gap-4 border border-border bg-background/40 p-4 text-left transition hover:border-primary/50 hover:bg-foreground/5"
                    >
                      <span className="grid h-10 w-10 shrink-0 place-items-center border border-border bg-secondary/40 text-primary">
                        <Icon className="h-5 w-5" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium text-foreground">{p.name}</span>
                        <span className="block text-xs text-muted-foreground">{p.tagline}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* ── Step 3 — Authenticate ── */}
          {step === 3 && provider && (
            <div className="flex flex-col gap-5">
              <button
                type="button"
                onClick={goBackToProviders}
                className="inline-flex items-center gap-1 self-start text-xs text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="h-3 w-3" />
                Back
              </button>

              {/* 3b — OAuth */}
              {provider.auth === "oauth" && provider.oauthId && (
                <>
                  <h1 className="text-xl font-semibold tracking-tight">
                    Log in with your {provider.id === "openai-codex" ? "ChatGPT" : "Claude"} account
                  </h1>
                  <InlineOAuth
                    oauthId={provider.oauthId}
                    providerName={provider.name}
                    onSuccess={handleOAuthSuccess}
                    onError={(m) => setError(m)}
                  />
                </>
              )}

              {/* 3a — API key */}
              {provider.auth === "apikey" && (
                <>
                  <h1 className="text-xl font-semibold tracking-tight">
                    {provider.id === "custom"
                      ? "Connect a custom endpoint"
                      : `Paste your ${provider.name} API key`}
                  </h1>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <KeyRound className="h-4 w-4 shrink-0" />
                    Stored locally in your .env — never sent anywhere else.
                  </div>
                  <div className="flex flex-col gap-2">
                    <Input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder={provider.keyPlaceholder ?? "sk-…"}
                      onKeyDown={(e) => e.key === "Enter" && handleApiKeyContinue()}
                      autoFocus
                    />
                    {provider.keyUrl && (
                      <a
                        href={provider.keyUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="h-3 w-3" />
                        Get a {provider.name} API key
                      </a>
                    )}
                  </div>
                  {provider.id === "custom" && (
                    <div className="flex flex-col gap-3">
                      <div className="flex flex-col gap-1">
                        <label className="text-xs uppercase tracking-wider text-muted-foreground">
                          Base URL
                        </label>
                        <Input
                          value={baseUrl}
                          onChange={(e) => setBaseUrl(e.target.value)}
                          placeholder="https://your-endpoint/v1"
                        />
                      </div>
                      <div className="flex flex-col gap-1">
                        <label className="text-xs uppercase tracking-wider text-muted-foreground">
                          Model name
                        </label>
                        <Input
                          value={customModel}
                          onChange={(e) => setCustomModel(e.target.value)}
                          placeholder="model-id"
                        />
                      </div>
                    </div>
                  )}
                  {error && <p className="text-xs text-destructive">{error}</p>}
                  <Button onClick={handleApiKeyContinue} disabled={saving}>
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
                  </Button>
                </>
              )}

              {/* 3c — Ollama */}
              {provider.auth === "ollama" && (
                <>
                  <h1 className="text-xl font-semibold tracking-tight">
                    Ollama runs locally — no key required
                  </h1>
                  <p className="text-sm text-muted-foreground">
                    Point Spark at your running Ollama server.
                  </p>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs uppercase tracking-wider text-muted-foreground">
                      Base URL
                    </label>
                    <Input
                      value={baseUrl}
                      onChange={(e) => setBaseUrl(e.target.value)}
                      placeholder="http://localhost:11434"
                      onKeyDown={(e) => e.key === "Enter" && handleOllamaContinue()}
                      autoFocus
                    />
                  </div>
                  {error && <p className="text-xs text-destructive">{error}</p>}
                  <Button onClick={handleOllamaContinue} disabled={saving}>
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
                  </Button>
                </>
              )}
            </div>
          )}

          {/* ── Step 4 — Name your agent ── */}
          {step === 4 && (
            <div className="flex flex-col gap-5">
              <div className="text-center">
                <h1 className="text-xl font-semibold tracking-tight">Name your agent</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  Give your agent a name. You can change it anytime in Settings.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Input
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="Spark"
                  onKeyDown={(e) => e.key === "Enter" && handleNameContinue()}
                  autoFocus
                />
              </div>
              {error && <p className="text-xs text-destructive">{error}</p>}
              <Button onClick={handleNameContinue} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
              </Button>
            </div>
          )}

          {/* ── Step 5 — Skills setup ── */}
          {step === 5 && (
            <div className="flex flex-col gap-5">
              <div className="text-center">
                <h1 className="text-xl font-semibold tracking-tight">How should skills be set up?</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  Skills give your agent specialized abilities. You can add or remove them later.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                {(
                  [
                    {
                      id: "recommended" as const,
                      title: "Base Included Skills",
                      badge: "Recommended",
                      desc: "Comes bundled with the Spark recommended skills.",
                    },
                    {
                      id: "minimal" as const,
                      title: "Minimal Included Skills",
                      desc: "Comes bundled with only a few top Spark skills.",
                    },
                    {
                      id: "none" as const,
                      title: "No skills, a blank slate",
                      desc: "Add and configure your own skills. Spark will also make skills as you use the platform.",
                    },
                  ]
                ).map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setSkillsMode(opt.id)}
                    className={`group flex items-start gap-3 border p-4 text-left transition ${
                      skillsMode === opt.id
                        ? "border-primary/70 bg-foreground/5"
                        : "border-border bg-background/40 hover:border-primary/40 hover:bg-foreground/5"
                    }`}
                  >
                    <span
                      className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border ${
                        skillsMode === opt.id ? "border-primary" : "border-border"
                      }`}
                    >
                      {skillsMode === opt.id && <span className="h-2 w-2 rounded-full bg-primary" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground">{opt.title}</span>
                        {opt.badge && (
                          <span className="rounded-sm border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-primary">
                            {opt.badge}
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{opt.desc}</span>
                    </span>
                  </button>
                ))}
              </div>
              {error && <p className="text-xs text-destructive">{error}</p>}
              <Button onClick={handleSkillsContinue} disabled={saving}>
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
              </Button>
            </div>
          )}

          {/* ── Step 6 — Done ── */}
          {step === 6 && (
            <div className="flex flex-col items-center gap-5 text-center">
              <span className="grid h-14 w-14 place-items-center rounded-full border border-success/40 bg-success/10 text-success">
                <Check className="h-7 w-7" />
              </span>
              <h1 className="text-2xl font-semibold tracking-tight">You're all set</h1>
              <p className="max-w-sm text-sm leading-6 text-muted-foreground">
                Saved: <span className="text-foreground">{savedSummary}</span>
                <br />
                You can change providers and models anytime in Settings.
              </p>
              <Button className="mt-2 w-full" size="lg" onClick={openSpark}>
                Open Spark
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default OnboardingWizard;
