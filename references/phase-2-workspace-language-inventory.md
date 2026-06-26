# Phase 2 Workspace Language Inventory

Collected: 2026-06-25

Source of truth: `PLAN.md` Phase 2 and `CONTEXT.md` glossary.

## Scan

Command used for the inventory:

```bash
rg -l -i "\bworkspace\b|\bworkspaces\b" \
  --glob '!node_modules/**' \
  --glob '!graphify-out/**' \
  --glob '!src/spark_cli/web/src-tauri/target/**' \
  --glob '!src/spark_cli/web/src-tauri/resources/**' \
  --glob '!src/spark_cli/web/dist/**' \
  --glob '!src/spark_cli/web/build/**' \
  --glob '!src/spark_cli/web_dist/**' \
  --glob '!references/phase-2-workspace-language-inventory.md' \
  --glob '!dist/**' \
  --glob '!build/**' \
  --glob '!venv/**' \
  --glob '!.venv/**' \
  --glob '!.git/**'
```

Pre-cleanup count: 174 matching files. Post-cleanup count: 169 matching files,
excluding this generated inventory note. Use the same command with `rg -n` for
line-level detail.

## Classification Summary

| Category | Count | Disposition |
| --- | ---: | --- |
| Public compatibility route | 3 | Keep `/api/workspace/...` and route-client names until an explicit deprecation window exists. |
| Internal implementation name | 52 | Leave for later service/module rename work; many are storage paths, source ids, event topics, or backend concepts. |
| Frontend implementation or UI copy | 18 | Changed obvious visible copy only; left component names, props, event topics, comments, tests, and API paths. |
| Docs/skills | 45 | Mostly non-product uses: platform workspaces, container `/workspace`, Honcho workspace id, Notion/Slack workspaces, skill work areas. |
| Tests | 39 | Preserve until compatibility and renamed canonical APIs are both covered deliberately. |
| Migration/OpenClaw legacy | 4 | Preserve legacy import terminology and paths. |
| Unrelated Google Workspace | 5 | Preserve. |
| Tests/environments | 3 | Container/sandbox workspace terminology; preserve. |

## Low-Risk Copy Updated

These visible strings were changed from Workspace/workspace toward Project, Chat, or Files:

- `src/spark_cli/web/src/i18n/en.ts`
- `src/spark_cli/web/src/components/CommandPalette.tsx`
- `src/spark_cli/web/src/components/KeyboardShortcutsModal.tsx`
- `src/spark_cli/web/src/components/SettingsPanel.tsx`
- `src/spark_cli/web/src/components/chat/FeedbackForm.tsx`
- `src/spark_cli/web/src/components/sidebar/SidebarSessions.tsx`
- `src/spark_cli/web/src/components/workspace/WorkspacePreviewPanel.tsx`
- `src/spark_cli/web/src/components/workspace/WorkspaceTerminalPanel.tsx`
- `src/spark_cli/web/src/pages/ChatPage.tsx`
- `src/spark_cli/web/src/pages/FilesPage.tsx`
- `src/spark_cli/web/src/pages/KanbanPage.tsx`

## Preserved On Purpose

- Google Workspace: connectors, skills, tests, and docs keep the official product name.
- `/api/workspace/...`: public compatibility route text and client methods stay as-is.
- `workspace:` session source ids, `workspace.files.changed`, `workspace.preview.ready`, and `$SPARK_HOME/workspace`: internal implementation names for a later migration slice.
- OpenClaw migration: legacy `workspace/` paths and flags stay accurate to the source product.
- Slack, Notion, Honcho, W&B, Daytona, Docker, Modal, and editor workspaces: unrelated product/platform terms.

## Primary File Buckets

### Public Compatibility Route

- `src/spark_cli/artifacts_routes.py`
- `src/spark_cli/web/src/lib/api.ts`
- `src/spark_cli/workspace_routes.py`

### Frontend Implementation Or UI Copy

- `src/spark_cli/web/src/components/Markdown.test.ts`
- `src/spark_cli/web/src/components/Markdown.tsx`
- `src/spark_cli/web/src/components/SettingsPanel.tsx`
- `src/spark_cli/web/src/components/chat/AtFileMenu.tsx`
- `src/spark_cli/web/src/components/sidebar/SidebarSessions.tsx`
- `src/spark_cli/web/src/components/workspace/FileTreePane.tsx`
- `src/spark_cli/web/src/components/workspace/WorkspaceChangesPanel.tsx`
- `src/spark_cli/web/src/hooks/useEventBus.ts`
- `src/spark_cli/web/src/i18n/en.ts`
- `src/spark_cli/web/src/i18n/types.ts`
- `src/spark_cli/web/src/lib/fileCategory.ts`
- `src/spark_cli/web/src/lib/sessionStore.tsx`
- `src/spark_cli/web/src/lib/theme.tsx`
- `src/spark_cli/web/src/pages/CanvasPage.tsx`
- `src/spark_cli/web/src/pages/ChatPage.tsx`
- `src/spark_cli/web/src/pages/ConnectorsPage.tsx`
- `src/spark_cli/web/src/pages/FilesPage.tsx`
- `src/spark_cli/web/src/pages/KanbanPage.tsx`

### Internal Implementation Name

- `src/agent/context_references.py`
- `src/agent/memory_provider.py`
- `src/agent/prompt_builder.py`
- `src/agent/skill_commands.py`
- `src/core/cli/commands_mixin.py`
- `src/core/dream.py`
- `src/core/run_agent/__init__.py`
- `src/core/spark_constants.py`
- `src/core/spark_state.py`
- `src/core/toolsets.py`
- `src/gateway/display_config.py`
- `src/gateway/platforms/ADDING_A_PLATFORM.md`
- `src/gateway/platforms/slack.py`
- `src/gateway/run.py`
- `src/gateway/session.py`
- `src/plugins/memory/honcho/README.md`
- `src/plugins/memory/honcho/cli.py`
- `src/plugins/memory/honcho/client.py`
- `src/plugins/memory/supermemory/README.md`
- `src/spark_cli/PREVIEW_BROWSER_SECURITY.md`
- `src/spark_cli/canvas_routes.py`
- `src/spark_cli/commands.py`
- `src/spark_cli/config.py`
- `src/spark_cli/connectors_routes.py`
- `src/spark_cli/default_soul.py`
- `src/spark_cli/doctor.py`
- `src/spark_cli/gateway.py`
- `src/spark_cli/main.py`
- `src/spark_cli/preview_agent_browser.py`
- `src/spark_cli/preview_browser.py`
- `src/spark_cli/profiles.py`
- `src/spark_cli/project_templates.py`
- `src/spark_cli/secret_store.py`
- `src/spark_cli/setup.py`
- `src/spark_cli/tips.py`
- `src/spark_cli/web/package-lock.json`
- `src/spark_cli/web/src-tauri/src/lib.rs`
- `src/spark_cli/web_server.py`
- `src/spark_cli/workflow_nodes.py`
- `src/tools/browser_action_log.py`
- `src/tools/browser_takeover.py`
- `src/tools/browser_tool.py`
- `src/tools/connectors/__init__.py`
- `src/tools/connectors/generic.py`
- `src/tools/connectors/google.py`
- `src/tools/connectors_tool.py`
- `src/tools/delegate_tool.py`
- `src/tools/environments/base.py`
- `src/tools/environments/docker.py`
- `src/tools/file_operations.py`
- `src/tools/preview_tool.py`
- `src/tools/terminal_tool.py`

### Docs/Skills

- `CONTEXT.md`
- `PLAN.md`
- `docs/building/creating-skills.md`
- `docs/building/editor-extension-internals.md`
- `docs/building/environments.md`
- `docs/chat-platforms/slack.md`
- `docs/chat-platforms/telegram.md`
- `docs/cli-config.yaml.example`
- `docs/cli/commands-reference.md`
- `docs/cli/profiles.md`
- `docs/cli/slash-commands.md`
- `docs/configuration.md`
- `docs/guides/automate-with-cron.md`
- `docs/guides/deploy-to-a-slack-team.md`
- `docs/guides/use-mcp.md`
- `docs/integrations/acp.md`
- `docs/integrations/index.md`
- `docs/memory/honcho-spec.md`
- `docs/memory/providers.md`
- `docs/reference/environment-variables.md`
- `docs/sessions.md`
- `docs/skills/catalog.md`
- `docs/skills/index.md`
- `docs/skills/optional-catalog.md`
- `docs/tools/context-references.md`
- `docs/tools/index.md`
- `skills/autonomous-ai-agents/claude-code/SKILL.md`
- `skills/autonomous-ai-agents/codex/SKILL.md`
- `skills/creative/hyperframes/references/beat-direction.md`
- `skills/creative/impeccable/reference/craft.md`
- `skills/creative/impeccable/reference/polish.md`
- `skills/creative/popular-web-designs/templates/notion.md`
- `skills/creative/remotion-best-practices/SKILL.md`
- `skills/creative/website-to-hyperframes/references/step-4-storyboard.md`
- `skills/mlops/cloud/modal/references/advanced-usage.md`
- `skills/mlops/evaluation/weights-and-biases/SKILL.md`
- `skills/mlops/training/axolotl/references/other.md`
- `skills/mlops/training/unsloth/references/llms-full.md`
- `skills/mlops/training/unsloth/references/llms-txt.md`
- `skills/note-taking/obsidian/SKILL.md`
- `skills/productivity/notion/SKILL.md`
- `skills/research/llm-wiki/SKILL.md`
- `skills/research/research-paper-writing/SKILL.md`
- `skills/research/research-paper-writing/references/experiment-patterns.md`
- `skills/software-development/plan/SKILL.md`

### Tests

- `tests/agent/test_context_references.py`
- `tests/agent/test_skill_commands.py`
- `tests/cli/test_cli_plan_command.py`
- `tests/core/test_context_items.py`
- `tests/gateway/test_config_cwd_bridge.py`
- `tests/gateway/test_plan_command.py`
- `tests/gateway/test_session_routing.py`
- `tests/gateway/test_slack.py`
- `tests/gateway/test_slack_mention.py`
- `tests/honcho_plugin/test_async_memory.py`
- `tests/honcho_plugin/test_client.py`
- `tests/run_agent/test_run_agent.py`
- `tests/skills/test_google_oauth_setup.py`
- `tests/skills/test_google_workspace_api.py`
- `tests/spark_cli/test_artifacts_routes.py`
- `tests/spark_cli/test_briefs_manifests.py`
- `tests/spark_cli/test_canvas_routes.py`
- `tests/spark_cli/test_claw.py`
- `tests/spark_cli/test_config.py`
- `tests/spark_cli/test_preview_browser_backend.py`
- `tests/spark_cli/test_preview_browser_stream.py`
- `tests/spark_cli/test_preview_port_detection.py`
- `tests/spark_cli/test_profiles.py`
- `tests/spark_cli/test_summaries.py`
- `tests/spark_cli/test_tool_outputs.py`
- `tests/spark_cli/test_web_server.py`
- `tests/spark_cli/test_web_server_events.py`
- `tests/spark_cli/test_workflow_engine.py`
- `tests/spark_cli/test_workspace_file_ops.py`
- `tests/spark_cli/test_workspace_git.py`
- `tests/test_honcho_client_config.py`
- `tests/test_preview_chrome.py`
- `tests/test_preview_collab.py`
- `tests/test_preview_devloop.py`
- `tests/test_project_templates.py`
- `tests/tools/test_daytona_environment.py`
- `tests/tools/test_docker_environment.py`
- `tests/tools/test_file_write_safety.py`
- `tests/tools/test_modal_sandbox_fixes.py`

### Migration/OpenClaw Legacy

- `docs/guides/migrate-from-openclaw.md`
- `docs/migration/openclaw.md`
- `src/spark_cli/claw.py`
- `tests/skills/test_openclaw_migration.py`

### Unrelated Google Workspace

- `skills/productivity/google-workspace/SKILL.md`
- `skills/productivity/google-workspace/scripts/google_api.py`
- `skills/productivity/google-workspace/scripts/setup.py`
- `src/spark_cli/google_connector.py`
- `src/tools/google_tools.py`

### Tests/Environments

- `environments/README.md`
- `environments/spark_swe_env/spark_swe_env.py`
- `environments/tool_context.py`
