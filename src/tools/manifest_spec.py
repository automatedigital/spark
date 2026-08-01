"""Source list and declarative availability rules for built-in tools."""

BUILTIN_TOOL_MODULES = (
    "tools.web_tools",
    "tools.terminal_tool",
    "tools.file_tools",
    "tools.artifact_tool",
    "tools.vision_tools",
    "tools.mixture_of_agents_tool",
    "tools.image_generation_tool",
    "tools.skills_tool",
    "tools.skill_manager_tool",
    "tools.browser_tool",
    "tools.preview_tool",
    "tools.canvas_tool",
    "tools.cronjob_tools",
    "tools.rl_training_tool",
    "tools.tts_tool",
    "tools.todo_tool",
    "tools.memory_tool",
    "tools.session_search_tool",
    "tools.clarify_tool",
    "tools.code_execution_tool",
    "tools.delegate_tool",
    "tools.process_registry",
    "tools.send_message_tool",
    "tools.kanban_tool",
    "tools.homeassistant_tool",
    "tools.computer_use.tool",
    "tools.google_tools",
    "tools.connectors_tool",
)

MODULE_EXTRAS = {
    "tools.browser_tool": "browser",
    "tools.computer_use.tool": "computer-use",
    "tools.google_tools": "google",
    "tools.image_generation_tool": "image",
    "tools.mixture_of_agents_tool": "openrouter",
    "tools.rl_training_tool": "rl",
    "tools.tts_tool": "voice",
    "tools.vision_tools": "vision",
    "tools.web_tools": "web",
}

# SDK roots that must remain optional at module-import time. The generator
# blocks these in isolated subprocesses and requires an identical schema set.
OPTIONAL_GUARD_ROOTS = {
    "tools.browser_tool": ("browser_use", "playwright"),
    "tools.image_generation_tool": ("fal_client",),
    "tools.tts_tool": ("edge_tts", "elevenlabs"),
    "tools.web_tools": ("firecrawl",),
}

CHECK_SPECS = {
    "tools.browser_tool:check_browser_active": "browser_active",
    "tools.browser_tool:check_browser_requirements": "browser_requirements",
    "tools.cronjob_tools:check_cronjob_requirements": "cron",
    "tools.google_tools:_check_gmail_read_connected": "gmail",
    "tools.google_tools:_check_google_oauth_connected": "google_oauth",
    "tools.homeassistant_tool:_check_ha_available": "homeassistant",
    "tools.image_generation_tool:check_image_generation_requirements": "image_generation",
    "tools.send_message_tool:_check_send_message": "gateway",
    "tools.tts_tool:check_tts_requirements": "tts",
    "tools.web_tools:check_web_api_key": "env_any",
    "tools.mixture_of_agents_tool:check_moa_requirements": "env_any",
    "tools.rl_training_tool:check_rl_api_keys": "env_all",
}


def check_spec(check_path: str | None, requires_env: list[str]) -> str:
    if check_path in CHECK_SPECS:
        return CHECK_SPECS[check_path]
    if requires_env:
        return "env_all"
    return "always"
