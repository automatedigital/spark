/** Response and payload types for the Spark web API.
 *
 * Split out of api.ts, which was 3,052 lines. api.ts re-exports everything
 * here, so `import { X } from "./api"` keeps working at every call site.
 */

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  spark_home: string;
  latest_config_version: number;
  release_date: string;
  server_instance_id?: string;
  version: string;
  commit?: string | null;
  repository_url?: string | null;
  update_available?: boolean;
  commits_behind?: number | null;
  desktop?: boolean;
  desktop_version?: string | null;
  desktop_platform?: "macos" | "windows" | "linux" | null;
  mac_update_available?: boolean;
  mac_latest_version?: string | null;
  dashboard_auth?: {
    token_file: string;
    require_auth_nonlocal: boolean;
  };
  dashboard_features?: {
    subagents_sidebar?: boolean;
  };
  streaming_health?: {
    checkpoint_writes: number;
    checkpoint_write_errors: number;
    checkpoint_write_seconds_avg: number;
    checkpoint_write_seconds_max: number;
    turn_lock_wait_seconds_avg: number;
    turn_lock_wait_seconds_max: number;
    turn_lock_wait_samples: number;
    event_drops: number;
    event_drop_keys: number;
    loop_lag_seconds: number;
    loop_lag_seconds_max: number;
    executor_submitted: number;
    executor_completed: number;
    executor_running: number;
    executor_queued: number;
    executor_queue_wait_seconds_avg: number;
    executor_queue_wait_seconds_max: number;
    agent_cache_size: number;
    agent_cache_evictions: number;
    warm_session_deduped: number;
    fanout_latency_seconds_avg: number;
    fanout_latency_seconds_max: number;
    fanout_latency_samples: number;
  };
}

export interface DashboardAuthInfo {
  require_auth_nonlocal: boolean;
  token_file: string;
  hint: string;
}

export interface KanbanTaskRow {
  id: string;
  title: string;
  body?: string | null;
  status: string;
  assignee?: string | null;
  tenant?: string | null;
  priority?: number;
  in_triage?: number;
  board_slug?: string;
  workspace_path?: string | null;
  updated_at?: number;
  result?: string | null;
  [key: string]: unknown;
}

export interface KanbanTaskCreate {
  title: string;
  body?: string;
  board?: string;
  assignee?: string | null;
  tenant?: string | null;
  priority?: number;
  parents?: string[];
  idempotency_key?: string | null;
  workspace_kind?: string;
  workspace_path?: string | null;
  skills?: string[];
  owner_profile?: string | null;
  owner_platform?: string | null;
  owner_channel?: string | null;
  owner_thread_id?: string | null;
  creator_session_key?: string | null;
  creator_session_source?: Record<string, unknown>;
  notify_on_changes?: boolean;
  wake_on_changes?: boolean;
  triage?: boolean;
  max_runtime_seconds?: number;
}

export interface KanbanTaskPatch {
  status?: string | null;
  title?: string | null;
  body?: string | null;
  assignee?: string | null;
  priority?: number | null;
  tenant?: string | null;
  result?: string | null;
  in_triage?: boolean | null;
  workspace_path?: string | null;
  actor?: string | null;
  origin_session_key?: string | null;
  origin_kind?: string | null;
  internal_event?: boolean;
}

export interface KanbanBulkPatchFields {
  status?: string | null;
  assignee?: string | null;
  priority?: number | null;
}

export interface KanbanBulkPatchResponse {
  ok: boolean;
  errors: Record<string, string>;
}

export interface KanbanDispatchResponse {
  ok?: boolean;
  claimed?: number;
  task_ids?: string[];
  dry_run?: boolean;
  ready?: string[];
  blocked_by_assignee?: string[];
}

export interface KanbanBoardResponse {
  board_slug: string;
  columns: Record<string, KanbanTaskRow[]>;
  assignees: string[];
  tenants: string[];
  boards: Array<Record<string, unknown>>;
}

export interface KanbanTaskDetail extends KanbanTaskRow {
  parents: string[];
  children: string[];
  comments: Array<{ id: number; author?: string | null; body: string; created_at: number }>;
  events: Array<{
    id: number;
    kind: string;
    payload_json?: string | null;
    created_at: number;
    run_id?: number | null;
  }>;
  runs: Array<{
    id: number;
    outcome: string;
    profile?: string | null;
    started_at: number;
    ended_at?: number | null;
    summary?: string | null;
    error?: string | null;
  }>;
  worker_context?: string;
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
  kanban_status: string | null;
  estimated_cost_usd: number | null;
}

export interface WebGitFileSnapshot {
  path?: string;
  status?: string;
  adds?: number | null;
  dels?: number | null;
}

export interface WebChangedFile {
  path: string;
  status: string;
  before?: WebGitFileSnapshot | null;
  after?: WebGitFileSnapshot | null;
  additions?: number | null;
  deletions?: number | null;
}

export interface WebChangedFiles {
  is_repo: boolean;
  branch: string | null;
  files: WebChangedFile[];
  count: number;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

export type WebPlanStepStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface WebPlanStep {
  id: string;
  content: string;
  status: WebPlanStepStatus;
}

export interface WebPlan {
  revision: number;
  steps: WebPlanStep[];
  status: "empty" | "active" | "completed" | string;
  markdown: string | null;
  updated_at?: number;
}

export interface WebTurnOutcome {
  turn_id: string;
  session_id: string;
  user_message_id: number | string | null;
  assistant_message_id: number | string | null;
  status: "running" | "completed" | "failed" | "interrupted" | string;
  started_at: number | null;
  ended_at: number | null;
  workspace_slug: string | null;
  changed_files: WebChangedFiles | null;
  plan: WebPlan | null;
}

export interface WebTurnOutcomesResponse {
  session_id: string;
  resolved_session_id: string;
  latest_session_id: string;
  migrated_from?: string;
  count: number;
  outcomes: WebTurnOutcome[];
}

export interface WebPlanResponse {
  session_id: string;
  turn_id: string | null;
  plan: WebPlan | null;
}

export type WebPendingActionKind = "approval" | "requested_input";

export interface WebPendingAction {
  action_id: string;
  session_id: string;
  turn_id: string;
  kind: WebPendingActionKind | string;
  payload: {
    command?: string;
    description?: string;
    question?: string;
    prompt?: string;
    choices?: string[] | null;
    [key: string]: unknown;
  };
  status: "pending" | "resolved" | string;
  response?: unknown;
  created_at: number;
  resolved_at?: number | null;
}

export interface WebPendingActionsResponse {
  session_id: string;
  actions: WebPendingAction[];
}

export interface WebPendingActionSubmitResponse {
  ok: boolean;
  session_id: string;
  action: WebPendingAction;
  idempotent: boolean;
}

export interface WebApprovalSubmitResponse {
  ok: boolean;
  session_id: string;
  resolved: number;
  action_ids?: string[];
  action?: WebPendingAction;
  idempotent?: boolean;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  id?: string;
  message_index?: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  result_preview?: string | null;
  result_chars?: number | null;
  result_truncated?: boolean | null;
  has_full_result?: boolean | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
  reasoning?: string | null;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
  total?: number;
  has_earlier?: boolean;
  page_start_index?: number | null;
  page_end_index?: number | null;
  next_before_id?: string | number | null;
  /**
   * Set when the requested session was a parent of a compression-driven
   * lineage; identifies the originally-requested ID. The returned messages
   * come from the leaf (`session_id`) so the agent's current state is shown.
   */
  migrated_from?: string;
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
  };
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr: string; display: string };
  schedule_display: string;
  enabled: boolean;
  state: string;
  deliver?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  use_count: number;
  view_count: number;
  patch_count: number;
  skill_state: string;
  skill_id?: string;
  provenance?: "bundled" | "spark_created" | "hub_installed" | "local" | "external";
  provenance_detail?: { label: string; source: string };
  trust_level?: string;
  source?: string;
  invocation_type?: "user" | "model" | "both";
  index_token_cost?: number;
  supporting_file_count?: number;
  eval_status?: string;
  eval_date?: string | null;
  overlap_warnings?: string[];
  duplicate_warnings?: string[];
  modified?: boolean;
  removed?: boolean;
  location?: string;
  capabilities?: {
    editable: boolean;
    deletable: boolean;
    restorable: boolean;
    removal_mode: "tombstone" | "delete" | "hub_uninstall" | "detach";
  };
}

export interface SkillSupportingFile {
  path: string;
  size: number;
  file_type: string;
}

export interface SkillDetail extends SkillInfo {
  content: string;
  supporting_files: SkillSupportingFile[];
  future_context?: string;
}

export interface SkillUsageEntry {
  name: string;
  state: string;
  created_by: string | null;
  activity_count: number;
  use_count: number;
  view_count: number;
  patch_count: number;
  last_activity_at: string | null;
}

export interface SkillLifecycleCounts {
  active: number;
  stale: number;
  archived: number;
}

export interface SkillsAnalyticsResponse {
  top_skills: SkillUsageEntry[];
  lifecycle_counts: SkillLifecycleCounts;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  title: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

export interface ConversationModelEntry {
  id: string;
  hint: string;
}

export interface ConversationModelsResponse {
  models: ConversationModelEntry[];
}

export interface AdminActionMeta {
  id: string;
  label: string;
  description: string;
  risk: "low" | "medium" | "high" | string;
  requires_confirmation: boolean;
  long_running: boolean;
  args_schema: Record<string, unknown>;
  available: boolean;
  unavailable_reason?: string | null;
}

export interface AdminActionsResponse {
  ok: boolean;
  actions: AdminActionMeta[];
}

export interface AdminRunStartResponse {
  run_id: string;
  status: "queued" | "running" | "done" | "failed";
}

export interface AdminRunOutputLine {
  stream: string;
  text: string;
  ts: number;
}

export interface AdminRun {
  run_id: string;
  action_id: string;
  args: Record<string, unknown>;
  status: "queued" | "running" | "done" | "failed";
  started_at?: number | null;
  finished_at?: number | null;
  exit_code?: number | null;
  output_tail: AdminRunOutputLine[];
  error?: string | null;
}

export interface GatewayAdminStatus {
  ok: boolean;
  running: boolean;
  pid: number | null;
  runtime: Record<string, unknown>;
  platforms: Record<string, unknown>;
  configured_platforms: Array<{ id: string; configured: boolean }>;
  service_system: string;
  last_error?: string | null;
  state?: string | null;
}

export interface ProfileInfo {
  name: string;
  path: string;
  is_default: boolean;
  is_active: boolean;
  gateway_running: boolean;
  model?: string | null;
  provider?: string | null;
  has_env: boolean;
  skill_count: number;
  alias_path?: string | null;
}

export interface ProfilesResponse {
  ok: boolean;
  active: string;
  profiles: ProfileInfo[];
}

export interface ProfileCreateRequest {
  name: string;
  clone_from?: string | null;
  clone_config?: boolean;
  clone_all?: boolean;
  no_alias?: boolean;
}

export interface PluginInfo {
  id: string;
  name: string;
  path: string;
  description?: string | null;
  version?: string | null;
  enabled: boolean;
}

export interface PluginsResponse {
  ok: boolean;
  plugins: PluginInfo[];
}

export interface McpServersResponse {
  ok: boolean;
  servers: Record<string, Record<string, unknown>>;
}

export interface McpServerCreate {
  name: string;
  url?: string | null;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
}

export interface DiagnosticsSummary {
  ok: boolean;
  spark_home: string;
  config_path: string;
  env_path: string;
  config_version?: number | null;
  platform: string;
  python: string;
  missing_required_env: string[];
  gateway_running: boolean;
  dashboard_auth: { token_file: string; configured: boolean };
  actions: AdminActionMeta[];
}

export interface ConversationDiagnosticsResponse {
  ok: boolean;
  session_id: string;
  resolved_session_id: string;
  active_turn_session_id: string | null;
  turn: {
    active: boolean;
    state?: string | null;
    phase?: string | null;
    status?: string | null;
    interrupt_requested: boolean;
    idle_for_seconds?: number | null;
    stale_after_seconds?: number | null;
    stream_revision?: number | null;
    stream_text_chars?: number | null;
  };
  timing_breakdown: Record<string, number>;
  message_count: number;
  notes: string[];
}

/** Payload shapes for /api/events chat.* topics */
export interface ChatTokenData {
  t: string;
}

export interface ChatToolStartData {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ChatToolEndData {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result: string;
}

export interface ChatReasoningData {
  text: string;
}

export interface ChatStatusData {
  kind: string;
  message: string;
}

export interface ChatApprovalRequestedData {
  approval: {
    command?: string;
    description?: string;
    pattern_key?: string;
    pattern_keys?: string[];
  };
}

export type SubagentStatus =
  | "queued"
  | "starting"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "stale"
  | string;

export interface SubagentEvent {
  id?: string;
  run_id?: string;
  subagent_id?: string;
  type?: string;
  kind?: string;
  role?: string;
  text?: string | null;
  content?: string | null;
  message?: string | null;
  status?: SubagentStatus;
  tool_name?: string | null;
  tool_call_id?: string | null;
  ts?: number;
  timestamp?: number;
  created_at?: number;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SubagentRun {
  id: string;
  run_id?: string;
  subagent_id?: string;
  parent_session_id?: string | null;
  conversation_id?: string | null;
  child_session_id?: string | null;
  name?: string | null;
  task?: string | null;
  goal?: string | null;
  context?: string | null;
  status: SubagentStatus;
  summary?: string | null;
  error?: string | null;
  model?: string | null;
  started_at?: number | null;
  updated_at?: number | null;
  ended_at?: number | null;
  elapsed_seconds?: number | null;
  duration_seconds?: number | null;
  events?: SubagentEvent[];
  transcript?: SubagentEvent[];
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface ConversationSubagentsResponse {
  session_id: string;
  subagents: SubagentRun[];
}

export interface ConversationSubagentResponse {
  session_id: string;
  subagent: SubagentRun;
}

export interface ConversationSubagentMessagesResponse {
  session_id: string;
  requested_session_id?: string;
  subagent_id: string;
  child_session_id?: string | null;
  messages: SessionMessage[];
  total: number;
  limit: number;
  offset?: number;
  include_tool_results?: boolean;
}

export interface ConversationSubagentInterruptResponse {
  ok: boolean;
  session_id: string;
  subagent_id: string;
  child_session_id?: string | null;
  status: SubagentStatus;
}

export type ChatSubagentEventData = Partial<SubagentRun> & {
  id?: string;
  run_id?: string;
  subagent_id?: string;
  event?: SubagentEvent;
  events?: SubagentEvent[];
  transcript?: SubagentEvent[];
};

export interface SessionsChangedData {
  action: "created" | "updated" | "deleted";
  session_id: string;
  session?: SessionInfo;
}

export interface ReasoningEffortResponse {
  effort: string;
  supported: boolean;
}

export interface ModelStatusResponse {
  smart_model: string;
  smart_provider: string;
  fast_model: string;
  fast_provider: string;
  multi_model_enabled: boolean;
  reasoning_effort: string;
  reasoning_supported: boolean;
  auto_enabled: boolean;
  selection: "auto" | "pinned";
  auto_roles: Record<string, {
    provider: string;
    model: string;
    reasoning_effort: string;
    fallback: string[];
  }>;
  catalog_source: string;
  catalog_warning: string;
}

export interface ModelSuggestionsResponse {
  smart: string[];
  fast: string[];
  smart_provider: string;
  fast_provider: string;
}

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      // null while OpenAI's (often-slow) device-auth call is still in flight;
      // the UI then polls until the code arrives.
      status?: "starting" | "polling";
      user_code: string | null;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
  // Populated once the device-auth call returns (may lag the /start response).
  user_code?: string | null;
  verification_url?: string | null;
}

export interface WorkspaceProject {
  slug: string;
  name: string;
  path: string;
  mtime: number;
  file_count: number;
}

export interface WorkspaceProjectsResponse {
  projects: WorkspaceProject[];
}

export interface ProjectTemplate {
  id: string;
  label: string;
  description: string;
  project_type: ProjectType;
  recommended: boolean;
  available: boolean;
  package_managers: PackageManager[];
  default_package_manager: PackageManager | null;
  supported_options: string[];
  recommended_skills: string[];
}

export type ProjectType =
  | "blank"
  | "static_website"
  | "web_application"
  | "design_project"
  | "productivity_workspace"
  | "video_project";

export type PackageManager = "pnpm" | "npm" | "yarn" | "bun";

export interface ProjectTypeGroup {
  id: ProjectType;
  label: string;
  starters: ProjectTemplate[];
}

export interface ProjectTemplatesResponse {
  project_types: ProjectTypeGroup[];
  templates: ProjectTemplate[];
}

export interface ProjectCreateRequest {
  name: string;
  source?: "new_folder" | "local_folder" | "git_url" | "github";
  path?: string;
  clone_url?: string;
  template?: string;
  project_type?: ProjectType;
  starter_stack?: string;
  package_manager?: PackageManager;
  init_git?: boolean;
  initial_commit?: boolean;
  ai_skills_mode?: "recommended" | "manual";
  selected_skills?: string[];
  dev_tools?: string[];
  integrations?: string[];
}

// ── Canvas types ──────────────────────────────────────────────────────────
export type CanvasScope = "global" | "project";

export interface CanvasViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface CanvasDoc {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: CanvasViewport;
  version: number;
  updatedAt?: string | null;
  revision?: string | null;
  expectedRevision?: string | null;
}

// React Flow node/edge shapes (loose — the canvas owns the concrete data types).
export interface CanvasNode {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
  width?: number | null;
  height?: number | null;
  [key: string]: unknown;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  [key: string]: unknown;
}

export interface CanvasSummary {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
  updatedAt: string;
  revision?: string | null;
  error?: string | null;
}

export interface CanvasListResponse {
  canvases: CanvasSummary[];
}

// ── Workflow engine types ─────────────────────────────────────────────────
export interface WorkflowNodeType {
  type: string;
  category: "trigger" | "action" | "control" | "agent" | "io" | "display";
  label: string;
  emoji?: string;
  tool?: string;
  toolset?: string;
  description?: string;
  schema?: { properties?: Record<string, JsonSchemaProp>; required?: string[] };
}

export interface JsonSchemaProp {
  type?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  [key: string]: unknown;
}

export interface WorkflowItem {
  json: Record<string, unknown>;
  binary?: Record<string, unknown>;
}

export interface WorkflowNodeResult {
  nodeId: string;
  status: "success" | "error" | "skipped";
  items: WorkflowItem[];
  error: string | null;
  durationMs: number;
}

export interface WorkflowRunResult {
  executionId: string;
  status: "success" | "error";
  error: string | null;
  nodes: WorkflowNodeResult[];
}

export interface WorkflowExecutionSummary {
  id: string;
  canvas_id: string;
  scope: string;
  slug: string | null;
  status: string;
  error: string | null;
  started_at: number;
  finished_at: number;
  trigger: string;
}

export interface WorkflowExecutionDetail extends WorkflowExecutionSummary {
  nodes: WorkflowNodeResult[];
}

export interface WorkflowTrigger {
  id: string;
  canvas_id: string;
  node_id: string;
  kind: string;
  enabled: boolean;
  secret?: string | null;
  schedule?: string | null;
  path?: string | null;
  next_run_at?: number | null;
  last_run_at?: number | null;
}

export interface FileListEntry {
  name: string;
  path: string;
  type: "file" | "dir";
}

export interface FileListResponse {
  path: string;
  entries: FileListEntry[];
}

export interface WorkspaceFileNode {
  name: string;
  path: string;
  type: "file" | "dir";
  size?: number;
  mtime?: number;
  mime?: string;
  children?: WorkspaceFileNode[];
}

export interface WorkspaceTreeResponse {
  slug: string;
  path: string;
  tree: WorkspaceFileNode[];
}

export interface SlashCommand {
  name: string;
  description: string;
  category: string;
  aliases?: string[];
  args_hint?: string | null;
}

export interface WorkspaceFileContent {
  path: string;
  content: string;
  mime: string;
  size: number;
}

export interface WorkspaceTerminalRunStart {
  run_id: string;
  status: "queued" | "running" | "done" | "failed" | "stopped";
  cwd: string;
}

export type WorkspaceTerminalEvent =
  | { type: "state"; status: string; cwd?: string }
  | { type: "output"; stream?: string; text: string }
  | { type: "done"; status: string; exit_code: number | null };

export interface WorkspacePreviewStatus {
  slug: string;
  status: "starting" | "running" | "stopped" | "failed";
  url: string | null;
  command: string | null;
  port: number | null;
  kind: string | null;
  error: string | null;
  started_at: number | null;
  updated_at: number | null;
}

export interface WorkspacePreviewLog {
  ts: number;
  type: "log";
  stream: string;
  text: string;
}

export interface WorkspaceGitFile {
  path: string;
  status: "added" | "deleted" | "modified";
  adds: number | null;
  dels: number | null;
}

export interface WorkspaceGitStatus {
  is_repo: boolean;
  branch: string | null;
  files: WorkspaceGitFile[];
  total_adds: number;
  total_dels: number;
}

export type WorkspacePreviewEvent =
  | ({ type: "state" } & WorkspacePreviewStatus)
  | WorkspacePreviewLog
  | { type: "refresh"; ts: number; reason?: string };

export interface MemoryTargetPayload {
  target: string;
  entries: string[];
  entry_count: number;
  chars: number;
  limit: number;
  percent: number;
}

export interface MemoryListResponse {
  targets: Record<string, MemoryTargetPayload>;
}

export interface StreamBrowserInput {
  type:
    | "click"
    | "rightclick"
    | "scroll"
    | "type"
    | "key"
    | "back"
    | "forward"
    | "upload"
    | "clipboard-write"
    | "clipboard-read"
    | "copy"
    | "paste";
  x?: number;
  y?: number;
  dx?: number;
  dy?: number;
  text?: string;
  key?: string;
  button?: "left" | "right" | "middle";
  files?: string[];
}

export interface StreamBrowserTab {
  id: string;
  title: string;
  url: string;
  active: boolean;
}

export interface StreamBrowserDownload {
  name: string;
  size: number;
  mtime: number;
}

export interface BrowserActionLogEntry {
  ts: number;
  action: string;
  status: string;
  task_id?: string | null;
  detail?: Record<string, unknown>;
}

export interface StreamBrowserConsoleEntry {
  seq: number;
  ts: number;
  kind: "console" | "network" | "exception";
  level: string;
  text: string;
  detail?: Record<string, unknown>;
}

export interface StreamBrowserPickedElement {
  selector?: string;
  tag?: string;
  role?: string;
  name?: string;
  text?: string;
  rect?: { x: number; y: number; width: number; height: number };
  url?: string;
}

export interface WorkspacePreviewSnapshot {
  slug: string;
  url: string | null;
  title: string;
  text: string;
  html_length: number;
}

export interface GoogleSetupInfo {
  redirect_uri: string;
  scopes: string[];
  configured: boolean;
  config_keys: { client_id: string; client_secret: string };
  console_url: string;
  client_type: string;
  error?: string;
}

export interface ArtifactInfo {
  id: string;
  name: string;
  type: "image" | "file" | "link";
  project_slug: string;
  project_name: string;
  path: string;
  url: string;
  size: number;
  mtime: number;
  mime: string;
}

export interface ArtifactsResponse {
  artifacts: ArtifactInfo[];
  counts: { all: number; images: number; files: number; links: number };
}

export interface MessagingField {
  key: string;
  label: string;
  description: string;
  type: "text" | "secret" | "bool" | "number" | string;
  placeholder: string;
  set: boolean;
  value: string;
}

export interface MessagingPlatform {
  id: string;
  name: string;
  description: string;
  help_text: string;
  setup_guide_url: string;
  enabled: boolean;
  configured: boolean;
  runtime: unknown;
  fields: {
    required: MessagingField[];
    recommended: MessagingField[];
    advanced: MessagingField[];
  };
  gateway_running?: boolean;
  saved?: string[];
  restart?: { ok: boolean; running: boolean; detail: string };
}

export interface MessagingPlatformsResponse {
  platforms: MessagingPlatform[];
  gateway_running: boolean;
}

export interface ConnectorStatus {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  transport?: "cli" | "mcp" | "skill" | string;
  scopes?: string[];
  skills?: string[];
  toolsets?: string[];
  capabilities?: string[];
  docs_url?: string;
  kind?: "mcp" | "oauth" | "cli" | "api_key" | string;
  api_key_url?: string;
  primary_env_var?: string;
  env_vars?: string[];
  setup_steps?: string[];
  connected: boolean;
  configured: boolean;
  state?: string;
  detail?: string;
  account?: string | null;
  status?: {
    state: string;
    detail?: string;
    account?: string | null;
    scopes?: string[];
    extra?: {
      installed?: boolean;
      env_vars?: string[];
      cli?: string | null;
      config_paths?: string[];
      setup_steps?: string[];
      auth_type?: "oauth" | "api_key" | "multi_env" | "cli" | string;
      auth_url?: string;
      api_key_url?: string;
      primary_env_var?: string;
      oauth_configured?: boolean;
      server_name?: string;
      server_url?: string;
      connect_state?: string;
      connect_error?: string;
      cli_sync?: {
        synced?: boolean;
        reason?: string;
        detail?: string;
        host?: string;
      };
      [key: string]: unknown;
    };
  };
  email?: string | null;
  name_display?: string | null;
  picture?: string | null;
  gmail_read?: { connected: boolean; email?: string | null };
  error?: string;
}

export interface CliToolInfo {
  id: string;
  name: string;
  cli: string;
  detected: boolean;
  path: string | null;
  install_hint: string;
}
