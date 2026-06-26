"""Gateway slash-command dispatch helpers."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_HANDLER_BY_COMMAND = {
    "new": "_handle_reset_command",
    "help": "_handle_help_command",
    "commands": "_handle_commands_command",
    "profile": "_handle_profile_command",
    "status": "_handle_status_command",
    "restart": "_handle_restart_command",
    "stop": "_handle_stop_command",
    "reasoning": "_handle_reasoning_command",
    "fast": "_handle_fast_command",
    "verbose": "_handle_verbose_command",
    "yolo": "_handle_yolo_command",
    "model": "_handle_model_command",
    "provider": "_handle_provider_command",
    "personality": "_handle_personality_command",
    "retry": "_handle_retry_command",
    "undo": "_handle_undo_command",
    "sethome": "_handle_set_home_command",
    "compress": "_handle_compress_command",
    "usage": "_handle_usage_command",
    "insights": "_handle_insights_command",
    "kanban": "_handle_kanban_command",
    "reload-mcp": "_handle_reload_mcp_command",
    "approve": "_handle_approve_command",
    "deny": "_handle_deny_command",
    "update": "_handle_update_command",
    "debug": "_handle_debug_command",
    "feedback": "_handle_feedback_command",
    "title": "_handle_title_command",
    "resume": "_handle_resume_command",
    "branch": "_handle_branch_command",
    "rollback": "_handle_rollback_command",
    "background": "_handle_background_command",
    "btw": "_handle_btw_command",
    "voice": "_handle_voice_command",
    "dream": "_handle_dream_command",
    "learnings": "_handle_learnings_command",
    "goal": "_handle_goal_command",
    "history": "_handle_history_command",
    "memory": "_handle_memory_gateway_command",
    "sessions": "_handle_sessions_gateway_command",
    "config": "_handle_config_command",
    "tools": "_handle_tools_gateway_command",
    "toolsets": "_handle_toolsets_command",
    "skills": "_handle_skills_gateway_command",
    "cron": "_handle_cron_gateway_command",
    "plugins": "_handle_plugins_command",
    "files": "_handle_files_gateway_command",
    "save": "_handle_save_command",
}


def is_known_gateway_command(command: str | None) -> bool:
    """Return True when a slash command is known to the gateway registry."""
    if not command:
        return False
    from spark_cli.commands import GATEWAY_KNOWN_COMMANDS

    return command.replace("_", "-") in GATEWAY_KNOWN_COMMANDS


async def dispatch_gateway_command(
    runner: Any,
    event: Any,
    source: Any,
    quick_key: str,
) -> tuple[bool, str | None]:
    """Dispatch a built-in gateway slash command.

    Returns ``(handled, response)``. ``handled=False`` means the caller should
    continue normal message processing, which is how agent-backed commands like
    ``/plan`` enter the regular agent loop after rewriting ``event.text``.
    """
    command = event.get_command()

    from spark_cli.commands import GATEWAY_KNOWN_COMMANDS, resolve_command

    if command and command in GATEWAY_KNOWN_COMMANDS:
        await runner.hooks.emit(f"command:{command}", {
            "platform": source.platform.value if source.platform else "",
            "user_id": source.user_id,
            "command": command,
            "args": event.get_command_args().strip(),
        })

    command_def = resolve_command(command) if command else None
    canonical = command_def.name if command_def else command

    if canonical == "plan":
        try:
            from agent.skill_commands import build_plan_path, build_skill_invocation_message

            user_instruction = event.get_command_args().strip()
            plan_path = build_plan_path(user_instruction)
            event.text = build_skill_invocation_message(
                "/plan",
                user_instruction,
                task_id=quick_key,
                runtime_note=(
                    "Save the markdown plan with write_file to this exact relative path "
                    f"inside the active workspace/backend cwd: {plan_path}"
                ),
            )
            if not event.text:
                return True, "Failed to load the bundled /plan skill."
            return False, None
        except Exception as exc:
            logger.exception("Failed to prepare /plan command")
            return True, f"Failed to enter plan mode: {exc}"

    if canonical == "reset-skills":
        return True, await _handle_reset_skills_command(event)

    handler_name = _HANDLER_BY_COMMAND.get(canonical or "")
    if handler_name:
        handler = getattr(runner, handler_name)
        return True, await handler(event)

    return False, None


async def _handle_reset_skills_command(event: Any) -> str:
    args_text = event.get_command_args().strip().lower()
    if args_text != "confirm":
        return (
            "⚠️ This will remove all hub-installed and custom skills, "
            "restoring Spark's bundled defaults.\n"
            "Send `/reset-skills confirm` to proceed."
        )
    try:
        from tools.skills_sync import reset_skills

        result = reset_skills()
        lines = ["Skills reset complete."]
        if result["removed"]:
            lines.append(f"− Removed: {', '.join(result['removed'])}")
        else:
            lines.append("(no custom or hub-installed skills to remove)")
        if result["restored"]:
            lines.append(f"✓ Restored: {', '.join(result['restored'])} bundled skills")
        if result["errors"]:
            lines.extend(f"! {error}" for error in result["errors"])
        return "\n".join(lines)
    except Exception as exc:
        logger.exception("reset-skills failed")
        return f"Reset failed: {exc}"
