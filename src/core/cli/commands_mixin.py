"""Slash-command handler methods for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). A mixin carrying the /personality,
/cron, /dream, /learnings, /curator, /goal, /skills command handlers. Combined into
SparkCLI via inheritance; methods run with full access to SparkCLI state (self).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime

from rich import box as rich_box
from rich.panel import Panel

from agent.skill_commands import build_plan_path, build_skill_invocation_message
from core.cli import ChatConsole  # defined before this import; no cycle
from core.cli.config_state import _spark_home, save_config_value
from core.cli.parsing import _get_chrome_debug_candidates, _parse_reasoning_config
from core.cli.render import _ACCENT, _DIM, _RST, _accent_hex, _cprint, _rich_text_from_ansi
from core.run_agent import AIAgent
from core.spark_constants import display_spark_home
from cron import get_job


class _CommandHandlersMixin:
    def _handle_personality_command(self, cmd: str):
        """Handle the /personality command to set predefined personalities."""
        parts = cmd.split(maxsplit=1)

        if len(parts) > 1:
            # Set personality
            personality_name = parts[1].strip().lower()

            if personality_name in ("none", "default", "neutral"):
                self.system_prompt = ""
                self.agent = None  # Force re-init
                if save_config_value("agent.system_prompt", ""):
                    print("Personality cleared (saved to config)")
                else:
                    print("Personality cleared (session only)")
                print("  No personality overlay - using base agent behavior.")
            elif personality_name in self.personalities:
                self.system_prompt = self._resolve_personality_prompt(
                    self.personalities[personality_name]
                )
                self.agent = None  # Force re-init
                if save_config_value("agent.system_prompt", self.system_prompt):
                    print(f"Personality set to '{personality_name}' (saved to config)")
                else:
                    print(f"Personality set to '{personality_name}' (session only)")
                print(
                    f'  "{self.system_prompt[:60]}{"..." if len(self.system_prompt) > 60 else ""}"'
                )
            else:
                print(f"(._.) Unknown personality: {personality_name}")
                print(f"  Available: none, {', '.join(self.personalities.keys())}")
        else:
            # Show available personalities
            print()
            print("+" + "-" * 50 + "+")
            print("|" + " " * 12 + "(^o^)/ Personalities" + " " * 15 + "|")
            print("+" + "-" * 50 + "+")
            print()
            print(f"  {'none':<12} - (no personality overlay)")
            for name, prompt in self.personalities.items():
                if isinstance(prompt, dict):
                    preview = (
                        prompt.get("description")
                        or prompt.get("system_prompt", "")[:50]
                    )
                else:
                    preview = str(prompt)[:50]
                print(f"  {name:<12} - {preview}")
            print()
            print("  Usage: /personality <name>")
            print()

    def _handle_cron_command(self, cmd: str):
        """Handle the /cron command to manage scheduled tasks."""
        import shlex

        from tools.cronjob_tools import cronjob as cronjob_tool

        def _cron_api(**kwargs):
            return json.loads(cronjob_tool(**kwargs))

        def _normalize_skills(values):
            normalized = []
            for value in values:
                text = str(value or "").strip()
                if text and text not in normalized:
                    normalized.append(text)
            return normalized

        def _parse_flags(tokens):
            opts = {
                "name": None,
                "deliver": None,
                "repeat": None,
                "skills": [],
                "add_skills": [],
                "remove_skills": [],
                "clear_skills": False,
                "all": False,
                "prompt": None,
                "schedule": None,
                "positionals": [],
            }
            i = 0
            while i < len(tokens):
                token = tokens[i]
                if token == "--name" and i + 1 < len(tokens):
                    opts["name"] = tokens[i + 1]
                    i += 2
                elif token == "--deliver" and i + 1 < len(tokens):
                    opts["deliver"] = tokens[i + 1]
                    i += 2
                elif token == "--repeat" and i + 1 < len(tokens):
                    try:
                        opts["repeat"] = int(tokens[i + 1])
                    except ValueError:
                        print("(._.) --repeat must be an integer")
                        return None
                    i += 2
                elif token == "--skill" and i + 1 < len(tokens):
                    opts["skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--add-skill" and i + 1 < len(tokens):
                    opts["add_skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--remove-skill" and i + 1 < len(tokens):
                    opts["remove_skills"].append(tokens[i + 1])
                    i += 2
                elif token == "--clear-skills":
                    opts["clear_skills"] = True
                    i += 1
                elif token == "--all":
                    opts["all"] = True
                    i += 1
                elif token == "--prompt" and i + 1 < len(tokens):
                    opts["prompt"] = tokens[i + 1]
                    i += 2
                elif token == "--schedule" and i + 1 < len(tokens):
                    opts["schedule"] = tokens[i + 1]
                    i += 2
                else:
                    opts["positionals"].append(token)
                    i += 1
            return opts

        tokens = shlex.split(cmd)

        if len(tokens) == 1:
            print()
            print("+" + "-" * 68 + "+")
            print("|" + " " * 24 + "Scheduled Tasks" + " " * 25 + "|")
            print("+" + "-" * 68 + "+")
            print()
            print("  Commands:")
            print("    /cron list")
            print(
                '    /cron add "every 2h" "Check server status" [--skill blogwatcher]'
            )
            print('    /cron edit <job_id> --schedule "every 4h" --prompt "New task"')
            print("    /cron edit <job_id> --skill blogwatcher --skill find-nearby")
            print("    /cron edit <job_id> --remove-skill blogwatcher")
            print("    /cron edit <job_id> --clear-skills")
            print("    /cron pause <job_id>")
            print("    /cron resume <job_id>")
            print("    /cron run <job_id>")
            print("    /cron remove <job_id>")
            print()
            result = _cron_api(action="list")
            jobs = result.get("jobs", []) if result.get("success") else []
            if jobs:
                print("  Current Jobs:")
                print("  " + "-" * 63)
                for job in jobs:
                    repeat_str = job.get("repeat", "?")
                    print(
                        f"    {job['job_id'][:12]:<12} | {job['schedule']:<15} | {repeat_str:<8}"
                    )
                    if job.get("skills"):
                        print(f"      Skills: {', '.join(job['skills'])}")
                    print(f"      {job.get('prompt_preview', '')}")
                    if job.get("next_run_at"):
                        print(f"      Next: {job['next_run_at']}")
                    print()
            else:
                print("  No scheduled jobs. Use '/cron add' to create one.")
            print()
            return

        subcommand = tokens[1].lower()
        opts = _parse_flags(tokens[2:])
        if opts is None:
            return

        if subcommand == "list":
            result = _cron_api(action="list", include_disabled=opts["all"])
            jobs = result.get("jobs", []) if result.get("success") else []
            if not jobs:
                print("(._.) No scheduled jobs.")
                return

            print()
            print("Scheduled Jobs:")
            print("-" * 80)
            for job in jobs:
                print(f"  ID: {job['job_id']}")
                print(f"  Name: {job['name']}")
                print(f"  State: {job.get('state', '?')}")
                print(f"  Schedule: {job['schedule']} ({job.get('repeat', '?')})")
                print(f"  Next run: {job.get('next_run_at', 'N/A')}")
                if job.get("skills"):
                    print(f"  Skills: {', '.join(job['skills'])}")
                print(f"  Prompt: {job.get('prompt_preview', '')}")
                if job.get("last_run_at"):
                    print(
                        f"  Last run: {job['last_run_at']} ({job.get('last_status', '?')})"
                    )
                print()
            return

        if subcommand in {"add", "create"}:
            positionals = opts["positionals"]
            if not positionals:
                print("(._.) Usage: /cron add <schedule> <prompt>")
                return
            schedule = opts["schedule"] or positionals[0]
            prompt = opts["prompt"] or " ".join(positionals[1:])
            skills = _normalize_skills(opts["skills"])
            if not prompt and not skills:
                print("(._.) Please provide a prompt or at least one skill")
                return
            result = _cron_api(
                action="create",
                schedule=schedule,
                prompt=prompt or None,
                name=opts["name"],
                deliver=opts["deliver"],
                repeat=opts["repeat"],
                skills=skills or None,
            )
            if result.get("success"):
                print(f"Created job: {result['job_id']}")
                print(f"  Schedule: {result['schedule']}")
                if result.get("skills"):
                    print(f"  Skills: {', '.join(result['skills'])}")
                print(f"  Next run: {result['next_run_at']}")
            else:
                print(f"Failed to create job: {result.get('error')}")
            return

        if subcommand == "edit":
            positionals = opts["positionals"]
            if not positionals:
                print(
                    "(._.) Usage: /cron edit <job_id> [--schedule ...] [--prompt ...] [--skill ...]"
                )
                return
            job_id = positionals[0]
            existing = get_job(job_id)
            if not existing:
                print(f"(._.) Job not found: {job_id}")
                return

            final_skills = None
            replacement_skills = _normalize_skills(opts["skills"])
            add_skills = _normalize_skills(opts["add_skills"])
            remove_skills = set(_normalize_skills(opts["remove_skills"]))
            existing_skills = list(
                existing.get("skills")
                or ([] if not existing.get("skill") else [existing.get("skill")])
            )
            if opts["clear_skills"]:
                final_skills = []
            elif replacement_skills:
                final_skills = replacement_skills
            elif add_skills or remove_skills:
                final_skills = [
                    skill for skill in existing_skills if skill not in remove_skills
                ]
                for skill in add_skills:
                    if skill not in final_skills:
                        final_skills.append(skill)

            result = _cron_api(
                action="update",
                job_id=job_id,
                schedule=opts["schedule"],
                prompt=opts["prompt"],
                name=opts["name"],
                deliver=opts["deliver"],
                repeat=opts["repeat"],
                skills=final_skills,
            )
            if result.get("success"):
                job = result["job"]
                print(f"Updated job: {job['job_id']}")
                print(f"  Schedule: {job['schedule']}")
                if job.get("skills"):
                    print(f"  Skills: {', '.join(job['skills'])}")
                else:
                    print("  Skills: none")
            else:
                print(f"Failed to update job: {result.get('error')}")
            return

        if subcommand in {"pause", "resume", "run", "remove", "rm", "delete"}:
            positionals = opts["positionals"]
            if not positionals:
                print(f"(._.) Usage: /cron {subcommand} <job_id>")
                return
            job_id = positionals[0]
            action = (
                "remove" if subcommand in {"remove", "rm", "delete"} else subcommand
            )
            result = _cron_api(
                action=action,
                job_id=job_id,
                reason="paused from /cron" if action == "pause" else None,
            )
            if not result.get("success"):
                print(f"Failed to {action} job: {result.get('error')}")
                return
            if action == "pause":
                print(f"Paused job: {result['job']['name']} ({job_id})")
            elif action == "resume":
                print(f"Resumed job: {result['job']['name']} ({job_id})")
                print(f"  Next run: {result['job'].get('next_run_at')}")
            elif action == "run":
                print(f"Triggered job: {result['job']['name']} ({job_id})")
                print("  It will run on the next scheduler tick.")
            else:
                removed = result.get("removed_job", {})
                print(f"Removed job: {removed.get('name', job_id)} ({job_id})")
            return

        print(f"(._.) Unknown cron command: {subcommand}")
        print("  Available: list, add, edit, pause, resume, run, remove")

    def _handle_dream_command(self, cmd: str):
        """Handle /dream — reflective consolidation pass over sessions + memory."""
        import shlex

        from core import dream as dream_mod

        tokens = shlex.split(cmd)
        sub = tokens[1].lower() if len(tokens) > 1 else ""

        def _format_ts(ts):
            if not ts:
                return "never"
            try:
                from datetime import datetime
                return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return str(ts)

        def _show_status():
            state = dream_mod.get_state()
            sched = dream_mod.get_schedule()
            print()
            print("+" + "-" * 60 + "+")
            print("|" + " " * 22 + "Dream Status" + " " * 26 + "|")
            print("+" + "-" * 60 + "+")
            print(f"  Last run:   {_format_ts(state.get('last_run_at'))}")
            print(f"  Total runs: {state.get('total_runs', 0)}")
            sched_state = "daily at {:02d}:00".format(int(sched.get("hour", 3))) \
                if sched.get("enabled") else "disabled"
            print(f"  Schedule:   {sched_state}")
            wiki = dream_mod._resolve_wiki_path() / "dreams"
            print(f"  Wiki:       {wiki}")
            print()

        def _run_pass():
            print()
            print("Dreaming — reading sessions and consolidating memory...")
            print("  This may take a minute or two.")
            result = dream_mod.run_dream()
            print()
            if result.error:
                print(f"(._.) Dream failed: {result.error}")
                return
            print(f"  Sessions scanned:     {result.sessions_scanned}")
            print(f"  Facts inspected:      {result.facts_scanned}")
            print(f"  Insights added:       {result.insights_added}")
            print(f"  Consolidations:       {result.consolidations_applied}")
            print(f"  Stale flagged:        {result.stale_queued}")
            if result.wiki_entry:
                print(f"  Wiki entry written:   {result.wiki_entry}")
            print()

        def _first_run_choice() -> int:
            try:
                from spark_cli.setup import prompt_choice
            except ImportError:
                print("(._.) Interactive prompts unavailable. Use /dream now or /dream schedule.")
                return -1
            print()
            print("This is your first dream. Spark can reflect on past sessions")
            print("and consolidate memory into your llm-wiki. How would you like")
            print("to use it?")
            print()
            return prompt_choice(
                "Choose how to run /dream",
                ["Run once now", "Run now + schedule daily", "Schedule daily only", "Cancel"],
                default=0,
            )

        if sub in ("", "now"):
            state = dream_mod.get_state()
            if not state.get("first_run_completed") and sub != "now":
                choice = _first_run_choice()
                if choice == 0:
                    _run_pass()
                elif choice == 1:
                    dream_mod.configure_schedule(True)
                    print("  Scheduled: daily.")
                    _run_pass()
                elif choice == 2:
                    dream_mod.configure_schedule(True)
                    print("  Scheduled: daily. Run /dream now to trigger one immediately.")
                else:
                    print("  Cancelled.")
                return
            _run_pass()
            return

        if sub == "schedule":
            sched = dream_mod.configure_schedule(True)
            print(
                f"  Daily dreams scheduled (hour={sched['hour']:02d}). "
                "Run /dream unschedule to disable."
            )
            return

        if sub == "unschedule":
            dream_mod.configure_schedule(False)
            print("  Daily dreams disabled.")
            return

        if sub == "status":
            _show_status()
            return

        if sub == "review":
            import json as _json
            path = dream_mod._pending_removals_path()
            if not path.exists():
                print("  No facts queued for removal.")
                return
            try:
                items = _json.loads(path.read_text())
            except (OSError, _json.JSONDecodeError):
                items = []
            if not items:
                print("  No facts queued for removal.")
                return
            print(f"  {len(items)} fact(s) flagged stale by past dreams:")
            for it in items:
                print(f"    [{it.get('fact_id')}] {it.get('reason', '')} ({it.get('queued_at', '')})")
            print()
            print("  Use /memory to inspect or remove these facts.")
            return

        print(f"(._.) Unknown dream command: {sub}")
        print("  Available: now, schedule, unschedule, status, review")

    def _handle_learnings_command(self, cmd: str):
        """Handle /learnings — review recent Dream syntheses and confirm removals."""
        from datetime import datetime

        from core import dream as dream_mod

        recent = dream_mod.list_recent_dreams(limit=5)
        pending = dream_mod.get_pending_removals()

        print()
        print("+" + "-" * 60 + "+")
        print("|" + " " * 22 + "Learnings" + " " * 29 + "|")
        print("+" + "-" * 60 + "+")

        if not recent and not pending:
            print("  Nothing yet. Run /dream to reflect on past sessions.")
            print()
            return

        if recent:
            print("\n  Recent dreams:")
            for d in recent:
                try:
                    when = datetime.fromtimestamp(d["modified"]).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    when = ""
                print(f"    • {d['title']}  ({when})")
                print(f"      {d['path']}")

        if not pending:
            print("\n  No memory removals awaiting review.")
            print()
            return

        print(f"\n  {len(pending)} fact(s) flagged stale by Dream — confirm removal?")
        for it in pending:
            fid = it.get("fact_id")
            reason = it.get("reason", "")
            print(f"\n    [fact {fid}] {reason}")
            try:
                choice = input("      (k)eep / (r)emove / (s)kip all  [k]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n  Review cancelled.")
                break
            if choice in ("s", "skip"):
                print("  Stopping review — remaining items stay queued.")
                break
            if choice in ("r", "remove"):
                if dream_mod.resolve_removal(fid, confirm=True):
                    print(f"      ✓ Removed fact {fid}.")
                else:
                    print(f"      (._.) Could not resolve fact {fid}.")
            else:
                dream_mod.resolve_removal(fid, confirm=False)
                print(f"      ✓ Kept fact {fid} (dequeued).")
        print()

    def _handle_curator_command(self, cmd: str):
        """Handle /curator — background skill maintenance."""
        import shlex
        tokens = shlex.split(cmd)
        sub = tokens[1].lower() if len(tokens) > 1 else "status"

        try:
            from agent import curator as curator_mod
        except Exception as e:
            print(f"(._.) curator module not available: {e}")
            return

        if sub == "status":
            state = curator_mod.load_state()
            enabled = curator_mod.is_enabled()
            paused = state.get("paused", False)
            last_run = state.get("last_run_at") or "never"
            last_summary = state.get("last_run_summary") or "(none)"
            run_count = state.get("run_count", 0)
            interval_h = curator_mod.get_interval_hours()
            print(f"  Curator: {'PAUSED' if paused else 'active' if enabled else 'disabled'}")
            print(f"  Interval: every {interval_h}h")
            print(f"  Last run: {last_run}  (run #{run_count})")
            print(f"  Last summary: {last_summary}")
        elif sub == "pause":
            curator_mod.set_paused(True)
            print("  Curator paused. Resume with /curator resume")
        elif sub == "resume":
            curator_mod.set_paused(False)
            print("  Curator resumed.")
        elif sub == "run":
            dry = "--dry-run" in tokens
            print("  Starting curator review" + (" (dry-run)" if dry else "") + "…")

            def _on_summary(msg: str):
                self.console.print(f"  {msg}")

            curator_mod.run_curator_review(
                on_summary=_on_summary,
                synchronous=False,
                dry_run=dry,
            )
            print("  Curator running in background. Check /curator status for results.")
        else:
            print(f"(._.) Unknown curator command: {sub}")
            print("  Available: status, pause, resume, run [--dry-run]")

    def _handle_goal_command(self, cmd: str):
        """Handle /goal — durable cross-session objective tracking via Kanban board."""
        import re as _re
        import shlex

        from core import goal as goal_mod

        tokens = shlex.split(cmd)
        sub = tokens[1].lower() if len(tokens) > 1 else ""
        rest = " ".join(tokens[1:]).strip() if len(tokens) > 1 else ""

        _SUBCOMMANDS = {"status", "pause", "resume", "clear", "done", "history"}

        def _invalidate():
            if hasattr(self, "agent") and hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        def _show_status():
            goal = goal_mod.get_active_goal()
            print()
            print("+" + "-" * 60 + "+")
            print("|" + " " * 23 + "Goal Status" + " " * 26 + "|")
            print("+" + "-" * 60 + "+")
            if goal is None:
                print("  No active goal. Set one with: /goal <objective>")
                print("  Manage goals in the Dashboard → Tasks (board: goals)")
            else:
                state = "PAUSED" if goal.get("paused") else "ACTIVE"
                print(f"  State:     {state}")
                print(f"  Objective: {goal.get('text', '')}")
                if goal.get("stopping_condition"):
                    print(f"  Done when: {goal['stopping_condition']}")
                print(f"  Task ID:   {goal.get('id', '')}  (goals board in Dashboard)")
                print(f"  Set at:    {goal.get('set_at', 'unknown')}")
            print()

        if sub in ("", "status"):
            _show_status()
            return

        if sub == "pause":
            goal = goal_mod.pause_goal()
            if goal is None:
                print("  No active goal to pause.")
            else:
                print(f"  Goal paused: {goal.get('text', '')}")
                _invalidate()
            return

        if sub == "resume":
            goal = goal_mod.resume_goal()
            if goal is None:
                print("  No paused goal to resume.")
            else:
                print(f"  Goal resumed: {goal.get('text', '')}")
                _invalidate()
            return

        if sub == "done":
            goal = goal_mod.done_goal()
            if goal is None:
                print("  No active goal to mark done.")
            else:
                print(f"  Goal done: {goal.get('text', '')}")
                _invalidate()
            return

        if sub == "clear":
            goal = goal_mod.clear_goal()
            if goal is None:
                print("  No active goal to clear.")
            else:
                print(f"  Goal cleared: {goal.get('text', '')}")
                _invalidate()
            return

        if sub == "history":
            history = goal_mod.get_history()
            if not history:
                print("  No past goals yet.")
                return
            print()
            print(f"  Past goals ({len(history)} total, most recent first):")
            for i, g in enumerate(history[:10], 1):
                status = g.get("status", "?")
                text = g.get("text", "")
                tid = g.get("id", "")
                set_at = g.get("set_at", "")
                print(f"  {i:2}. [{status}] {text}")
                if tid:
                    print(f"       id: {tid}  set: {set_at}")
            if len(history) > 10:
                print(f"  ... and {len(history) - 10} more (view in Dashboard → Tasks, board: goals).")
            print()
            return

        # Any non-subcommand text sets a new goal objective.
        # Optional stopping condition after " -- " or "when:" / "done when:"
        sep_match = _re.search(r"\s+(?:--|when:|done when:)\s+", rest, _re.IGNORECASE)
        if sep_match:
            objective = rest[:sep_match.start()].strip()
            stopping = rest[sep_match.end():].strip()
        else:
            objective = rest
            stopping = ""

        if not objective:
            print("  Usage: /goal <objective>")
            print("  Optional stopping condition: /goal <objective> -- <done when>")
            print("  Subcommands: status, pause, resume, done, clear, history")
            _show_status()
            return

        goal = goal_mod.set_goal(objective, stopping_condition=stopping)
        print()
        print(f"  Goal set: {goal['text']}")
        if goal.get("stopping_condition"):
            print(f"  Done when: {goal['stopping_condition']}")
        print(f"  Task ID:  {goal.get('id', '')}  — visible in Dashboard → Tasks (board: goals)")
        print("  Spark will pursue this goal across every session until you /goal done or /goal clear.")
        print()
        _invalidate()

    def _handle_skills_command(self, cmd: str):
        """Handle /skills slash command - delegates to spark_cli.skills_hub."""
        from spark_cli.skills_hub import handle_skills_slash

        handle_skills_slash(cmd, ChatConsole())

    def _handle_connectors_command(self, cmd: str):
        """Handle /connectors, /connect <id>, /disconnect <id>.

        Lists external-platform connectors and their status, or starts/tears down
        a connection. `connect` runs the platform CLI's interactive browser login
        inline (the TUI has a real TTY).
        """
        from tools.connectors import get_connector, list_connectors

        parts = cmd.strip().split()
        word = parts[0].lstrip("/").lower() if parts else "connectors"
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        # /connect <id> and /disconnect <id> map to actions; /connectors lists.
        if word in ("connect", "disconnect"):
            action, target = word, arg
        else:
            # /connectors [connect|disconnect|status <id>] | [<id>]
            if arg in ("connect", "disconnect", "status"):
                action = arg
                target = parts[2].strip().lower() if len(parts) > 2 else ""
            elif arg:
                action, target = "status", arg
            else:
                action, target = "list", ""

        if action == "list":
            cons = list_connectors()
            if not cons:
                _cprint("  No connectors available.")
                return
            _cprint(f"{_ACCENT}  Connectors{_RST}")
            for c in cons:
                st = c.status()
                mark = "✓" if st.connected else "·"
                acct = f" ({st.account})" if st.account else ""
                _cprint(f"  {mark} {c.id:<10} {st.state.value}{acct}{_DIM} — {c.name}{_RST}")
            _cprint(f"{_DIM}  /connect <id> to sign in · /disconnect <id> to revoke{_RST}")
            return

        if not target:
            _cprint(f"  Usage: /{word} <connector-id>  (e.g. /connect google)")
            return
        c = get_connector(target)
        if c is None:
            known = ", ".join(x.id for x in list_connectors()) or "(none)"
            _cprint(f"  Unknown connector '{target}'. Known: {known}")
            return

        if action == "status":
            st = c.status()
            acct = f" — {st.account}" if st.account else ""
            _cprint(f"  {c.name}: {st.state.value}{acct}")
            _cprint(f"{_DIM}  {st.detail}{_RST}")
            return

        if action == "disconnect":
            st = c.disconnect()
            _cprint(f"  {st.detail}")
            return

        # connect
        st = c.status()
        if st.connected:
            _cprint(f"  Already connected to {c.name}" + (f" ({st.account})." if st.account else "."))
            return
        _cprint(f"  Opening browser to sign in to {c.name}…")
        result = c.connect(interactive=True)
        if result.connected:
            acct = f" as {result.account}" if result.account else ""
            _cprint(f"  ✓ Connected to {c.name}{acct}.")
        else:
            _cprint(f"  Did not complete: {result.detail}")

    def _handle_reset_skills_command(self):
        """Handle /reset-skills — remove hub-installed/custom skills, restore bundled."""
        _cprint(
            f"{_ACCENT}This will remove all hub-installed and custom skills "
            f"and restore Spark's bundled defaults.{_RST}"
        )
        _cprint(f"{_DIM}Your bundled skills will be reset to their factory state.{_RST}")
        try:
            confirm = input("Continue? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            _cprint("Cancelled.")
            return
        if confirm != "y":
            _cprint("Cancelled.")
            return
        try:
            from tools.skills_sync import reset_skills
            _cprint("Resetting skills...")
            result = reset_skills()
            if result["removed"]:
                _cprint(f"  − Removed {len(result['removed'])}: {', '.join(result['removed'])}")
            else:
                _cprint("  (no custom or hub-installed skills to remove)")
            if result["restored"]:
                _cprint(f"  ✓ Restored {len(result['restored'])} bundled skills")
            if result["errors"]:
                for err in result["errors"]:
                    _cprint(f"  ! {err}")
            _cprint("Skills reset complete.")
        except Exception as e:
            _cprint(f"Reset failed: {e}")

    def _handle_btw_command(self, cmd: str):
        """Handle /btw <question> - ephemeral side question using session context.

        Snapshots the current conversation history, spawns a no-tools agent in
        a background thread, and prints the answer without persisting anything
        to the main session.
        """
        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            _cprint("  Usage: /btw <question>")
            _cprint("  Example: /btw what module owns session title sanitization?")
            _cprint("  Answers using session context. No tools, not persisted.")
            return

        question = parts[1].strip()
        task_id = f"btw_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"

        if not self._ensure_runtime_credentials():
            _cprint("  (>_<) Cannot start /btw: no valid credentials.")
            return

        turn_route = self._resolve_turn_agent_config(question)
        history_snapshot = list(self.conversation_history)

        preview = question[:60] + ("..." if len(question) > 60 else "")
        _cprint(f'  💬 /btw: "{preview}"')

        def run_btw():
            try:
                btw_agent = AIAgent(
                    model=turn_route["model"],
                    api_key=turn_route["runtime"].get("api_key"),
                    base_url=turn_route["runtime"].get("base_url"),
                    provider=turn_route["runtime"].get("provider"),
                    api_mode=turn_route["runtime"].get("api_mode"),
                    acp_command=turn_route["runtime"].get("command"),
                    acp_args=turn_route["runtime"].get("args"),
                    max_iterations=8,
                    enabled_toolsets=[],
                    quiet_mode=True,
                    verbose_logging=False,
                    session_id=task_id,
                    platform="cli",
                    reasoning_config=self.reasoning_config,
                    service_tier=self.service_tier,
                    request_overrides=turn_route.get("request_overrides"),
                    providers_allowed=self._providers_only,
                    providers_ignored=self._providers_ignore,
                    providers_order=self._providers_order,
                    provider_sort=self._provider_sort,
                    provider_require_parameters=self._provider_require_params,
                    provider_data_collection=self._provider_data_collection,
                    fallback_model=self._fallback_model,
                    session_db=None,
                    skip_memory=True,
                    skip_context_files=True,
                    persist_session=False,
                )

                btw_prompt = (
                    "[Ephemeral /btw side question. Answer using the conversation "
                    "context. No tools available. Be direct and concise.]\n\n"
                    + question
                )
                result = btw_agent.run_conversation(
                    user_message=btw_prompt,
                    conversation_history=history_snapshot,
                    task_id=task_id,
                )

                response = (result.get("final_response") or "") if result else ""
                if not response and result and result.get("error"):
                    response = f"Error: {result['error']}"

                # TUI refresh before printing
                if self._app:
                    self._app.invalidate()
                    time.sleep(0.05)
                print()

                if response:
                    try:
                        from spark_cli.skin_engine import get_active_skin

                        _skin = get_active_skin()
                        _resp_color = _skin.get_color("response_border", "#4F6D4A")
                    except Exception:
                        _resp_color = "#4F6D4A"

                    ChatConsole().print(
                        Panel(
                            _rich_text_from_ansi(response),
                            title=f"[{_resp_color} bold]S /btw[/]",
                            title_align="left",
                            border_style=_resp_color,
                            box=rich_box.HORIZONTALS,
                            padding=(1, 2),
                        )
                    )
                else:
                    _cprint("  💬 /btw: (no response)")

                if self.bell_on_complete:
                    sys.stdout.write("\a")
                    sys.stdout.flush()

            except Exception as e:
                if self._app:
                    self._app.invalidate()
                    time.sleep(0.05)
                print()
                _cprint(f"  ❌ /btw failed: {e}")
            finally:
                if self._app:
                    self._invalidate(min_interval=0)

        thread = threading.Thread(target=run_btw, daemon=True, name=f"btw-{task_id}")
        thread.start()

    @staticmethod
    def _try_launch_chrome_debug(port: int, system: str) -> bool:
        """Try to launch Chrome/Chromium with remote debugging enabled.

        Uses a dedicated user-data-dir so the debug instance doesn't conflict
        with an already-running Chrome using the default profile.

        Returns True if a launch command was executed (doesn't guarantee success).
        """
        import subprocess as _sp

        candidates = _get_chrome_debug_candidates(system)

        if not candidates:
            return False

        # Dedicated profile dir so debug Chrome won't collide with normal Chrome
        data_dir = str(_spark_home / "chrome-debug")
        os.makedirs(data_dir, exist_ok=True)

        chrome = candidates[0]
        try:
            _sp.Popen(
                [
                    chrome,
                    f"--remote-debugging-port={port}",
                    f"--user-data-dir={data_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
                start_new_session=True,  # detach from terminal
            )
            return True
        except Exception:
            return False

    def _handle_computer_use_command(self, cmd_original: str) -> None:
        """Enable computer_use for CLI, refresh the tool list, optionally queue a task.

        Mirrors /tools enable computer_use + agent refresh without resetting the
        session. Optionally accepts trailing text as the desktop task (queued like
        /plan).
        """
        import platform

        if platform.system() != "Darwin":
            _cprint("  computer_use is only available on macOS.")
            return

        parts = cmd_original.split(None, 1)
        user_tail = parts[1].strip() if len(parts) > 1 else ""

        from core.model_tools import get_tool_definitions
        from spark_cli.config import load_config
        from spark_cli.tools_config import (
            _get_platform_tools,
            enable_computer_use_cli_toolset,
        )

        enable_computer_use_cli_toolset()
        self.enabled_toolsets = _get_platform_tools(load_config(), "cli")

        _disabled = (
            self.agent.disabled_toolsets
            if self.agent is not None
            else None
        )
        try:
            _defs = get_tool_definitions(
                enabled_toolsets=self.enabled_toolsets,
                disabled_toolsets=_disabled,
                quiet_mode=True,
            )
        except Exception as e:
            _cprint(f"  WARN  Could not resolve tools: {e}")
            _defs = []

        cu_resolves = any(
            t.get("function", {}).get("name") == "computer_use" for t in (_defs or [])
        )

        if self.agent is not None:
            self.agent.enabled_toolsets = self.enabled_toolsets
            try:
                self.agent.tools = _defs
                self.agent.valid_tool_names = (
                    {t["function"]["name"] for t in self.agent.tools}
                    if self.agent.tools
                    else set()
                )
            except Exception as e:
                _cprint(f"  WARN  Could not refresh tools: {e}")
            if hasattr(self.agent, "_invalidate_system_prompt"):
                self.agent._invalidate_system_prompt()

        def _infer_computer_use_app(text: str) -> str | None:
            import re

            known_apps = (
                "Notion",
                "Slack",
                "Finder",
                "Notes",
                "Safari",
                "Chrome",
                "Cursor",
                "Terminal",
                "Calendar",
                "Mail",
            )
            lowered = text.lower()
            for app_name in known_apps:
                if app_name.lower() in lowered:
                    return app_name
            match = re.search(r"\bopen\s+([A-Z][A-Za-z0-9 ._-]{1,40})", text)
            if match:
                return match.group(1).strip().strip(".")
            return None

        target_app = _infer_computer_use_app(user_tail)
        first_capture = (
            f" For this request, the target app appears to be {target_app!r}; "
            f"your first computer_use call MUST be action='capture' with app={target_app!r}. "
            "Never call action='capture' without app until a successful app capture has selected "
            "a pid/window_id."
            if target_app
            else " Your first computer_use call MUST be action='capture' with app=<native app name>. "
            "Never call action='capture' without app until a successful app capture has selected "
            "a pid/window_id."
        )
        sys_msg_force = (
            "[SYSTEM: computer_use is in your tool list for this session. "
            "For the user's native macOS desktop / Notion.app / Slack.app / Finder "
            "(non-web) request, you MUST use computer_use: action=capture with "
            "app=<substring> first, then click/type/key using element indices from "
            "the capture. Do NOT use browser_open or browser_* for logged-in desktop "
            "workflows. Do NOT drive the GUI via terminal (osascript, screencapture, "
            "OCR, or coordinate clicks on screenshots). If computer_use returns an "
            "error, report that error to the user and stop; do not fall back to shell, "
            f"browser, filesystem search, or local app database inspection.{first_capture}]"
        )
        sys_msg_soft = (
            "[Note: /computer-use was run but the computer_use tool is not available "
            "in this session (the cua-driver binary is missing or not discoverable). "
            "Install cua-driver using the command shown in the CLI diagnostics — then "
            "run /computer-use again. For this message only, use whatever tools you "
            "have to help the user; do not refuse the task because computer_use is missing.]"
        )

        if cu_resolves:
            body = sys_msg_force
        elif user_tail:
            body = sys_msg_soft
        else:
            body = ""

        if user_tail:
            if hasattr(self, "_pending_input"):
                if body:
                    self.conversation_history.append({"role": "user", "content": body})
                self._pending_input.put(user_tail)
                if cu_resolves:
                    _cprint("  Computer-use mode — task queued for the agent.")
                else:
                    _cprint(
                        "  Task queued without computer_use — diagnostics below."
                    )
            else:
                _cprint("  Computer-use enabled but input queue is unavailable.")
        elif cu_resolves:
            self.conversation_history.append({"role": "user", "content": body})
            if self.agent is not None:
                try:
                    self.agent._persist_session(
                        self.conversation_history,
                        self.conversation_history,
                    )
                except Exception:
                    pass
            _cprint(
                "  Computer-use enabled. Describe the desktop task in your next message."
            )
        else:
            _cprint(
                "  computer_use is not available until cua-driver can be found "
                "(see diagnostics below)."
            )

        if not cu_resolves:
            try:
                from tools.computer_use.cua_backend import cua_driver_resolution_hint

                _hint = cua_driver_resolution_hint()
                if _hint:
                    _cprint(_hint)
            except Exception:
                pass

    def _handle_browser_command(self, cmd: str):
        """Handle /browser connect|disconnect|status - manage live Chrome CDP connection."""
        import platform as _plat

        parts = cmd.strip().split(None, 1)
        sub = parts[1].lower().strip() if len(parts) > 1 else "status"

        _DEFAULT_CDP = "http://localhost:9222"
        current = os.environ.get("BROWSER_CDP_URL", "").strip()

        if sub.startswith("connect"):
            # Optionally accept a custom CDP URL: /browser connect ws://host:port
            connect_parts = cmd.strip().split(
                None, 2
            )  # ["/browser", "connect", "ws://..."]
            cdp_url = (
                connect_parts[2].strip() if len(connect_parts) > 2 else _DEFAULT_CDP
            )

            # Clear any existing browser sessions so the next tool call uses the new backend
            try:
                from tools.browser_tool import cleanup_all_browsers

                cleanup_all_browsers()
            except Exception:
                pass

            print()

            # Extract port for connectivity checks
            _port = 9222
            try:
                _port = int(cdp_url.rsplit(":", 1)[-1].split("/")[0])
            except (ValueError, IndexError):
                pass

            # Check if Chrome is already listening on the debug port
            import socket

            _already_open = False
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(("127.0.0.1", _port))
                s.close()
                _already_open = True
            except (TimeoutError, OSError):
                pass

            if _already_open:
                print(f"   OK: Chrome is already listening on port {_port}")
            elif cdp_url == _DEFAULT_CDP:
                # Try to auto-launch Chrome with remote debugging
                print(
                    "   Chrome isn't running with remote debugging - attempting to launch..."
                )
                _launched = self._try_launch_chrome_debug(_port, _plat.system())
                if _launched:
                    # Wait for the port to come up
                    import time as _time

                    for _wait in range(10):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(1)
                            s.connect(("127.0.0.1", _port))
                            s.close()
                            _already_open = True
                            break
                        except (TimeoutError, OSError):
                            _time.sleep(0.5)
                    if _already_open:
                        print(f"   OK: Chrome launched and listening on port {_port}")
                    else:
                        print(
                            f"   WARN Chrome launched but port {_port} isn't responding yet"
                        )
                        print(
                            "     Try again in a few seconds - the debug instance may still be starting"
                        )
                else:
                    print("   WARN Could not auto-launch Chrome")
                    # Show manual instructions as fallback
                    _data_dir = str(_spark_home / "chrome-debug")
                    sys_name = _plat.system()
                    if sys_name == "Darwin":
                        chrome_cmd = (
                            'open -a "Google Chrome" --args'
                            f" --remote-debugging-port=9222"
                            f' --user-data-dir="{_data_dir}"'
                            " --no-first-run --no-default-browser-check"
                        )
                    elif sys_name == "Windows":
                        chrome_cmd = (
                            f"chrome.exe --remote-debugging-port=9222"
                            f' --user-data-dir="{_data_dir}"'
                            f" --no-first-run --no-default-browser-check"
                        )
                    else:
                        chrome_cmd = (
                            f"google-chrome --remote-debugging-port=9222"
                            f' --user-data-dir="{_data_dir}"'
                            f" --no-first-run --no-default-browser-check"
                        )
                    print("     Launch Chrome manually:")
                    print(f"     {chrome_cmd}")
            else:
                print(f"   WARN Port {_port} is not reachable at {cdp_url}")

            os.environ["BROWSER_CDP_URL"] = cdp_url
            print()
            print("🌐 Browser connected to live Chrome via CDP")
            print(f"   Endpoint: {cdp_url}")
            print()

            # Inject context message so the model knows
            if hasattr(self, "_pending_input"):
                self._pending_input.put(
                    "[System note: The user has connected your browser tools to their live Chrome browser "
                    "via Chrome DevTools Protocol. Your browser_navigate, browser_snapshot, browser_click, "
                    "and other browser tools now control their real browser - including any pages they have "
                    "open, logged-in sessions, and cookies. They likely opened specific sites or logged into "
                    "services before connecting. Please await their instruction before attempting to operate "
                    "the browser. When you do act, be mindful that your actions affect their real browser - "
                    "don't close tabs or navigate away from pages without asking.]"
                )

        elif sub == "disconnect":
            if current:
                os.environ.pop("BROWSER_CDP_URL", None)
                try:
                    from tools.browser_tool import cleanup_all_browsers

                    cleanup_all_browsers()
                except Exception:
                    pass
                print()
                print("🌐 Browser disconnected from live Chrome")
                print(
                    "   Browser tools reverted to default mode (local headless or cloud provider)"
                )
                print()

                if hasattr(self, "_pending_input"):
                    self._pending_input.put(
                        "[System note: The user has disconnected the browser tools from their live Chrome. "
                        "Browser tools are back to default mode (headless local browser or cloud provider).]"
                    )
            else:
                print()
                print(
                    "Browser is not connected to live Chrome (already using default mode)"
                )
                print()

        elif sub == "status":
            print()
            if current:
                print("🌐 Browser: connected to live Chrome via CDP")
                print(f"   Endpoint: {current}")

                _port = 9222
                try:
                    _port = int(current.rsplit(":", 1)[-1].split("/")[0])
                except (ValueError, IndexError):
                    pass
                try:
                    import socket

                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1)
                    s.connect(("127.0.0.1", _port))
                    s.close()
                    print("   Status: OK: reachable")
                except (OSError, Exception):
                    print("   Status: WARN not reachable (Chrome may not be running)")
            else:
                try:
                    from tools.browser_tool import _get_cloud_provider

                    provider = _get_cloud_provider()
                except Exception:
                    provider = None

                if provider is not None:
                    print(f"🌐 Browser: {provider.provider_name()} (cloud)")
                else:
                    print("🌐 Browser: local headless Chromium (agent-browser)")
            print()
            print("   /browser connect      - connect to your live Chrome")
            print("   /browser disconnect   - revert to default")
            print()

        else:
            print()
            print("Usage: /browser connect|disconnect|status")
            print()
            print("   connect      Connect browser tools to your live Chrome session")
            print("   disconnect   Revert to default browser backend")
            print("   status       Show current browser mode")
            print()

    def _handle_skin_command(self, cmd: str):
        """Handle /skin [name] - show or change the display skin."""
        try:
            from spark_cli.skin_engine import (
                get_active_skin_name,
                list_skins,
                set_active_skin,
            )
        except ImportError:
            print("Skin engine not available.")
            return

        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            # Show current skin and list available
            current = get_active_skin_name()
            skins = list_skins()
            print(f"\n  Current skin: {current}")
            print("  Available skins:")
            for s in skins:
                marker = " ●" if s["name"] == current else "  "
                source = f" ({s['source']})" if s["source"] == "user" else ""
                print(f"   {marker} {s['name']}{source} - {s['description']}")
            print("\n  Usage: /skin <name>")
            print(
                f"  Custom skins: drop a YAML file in {display_spark_home()}/skins/\n"
            )
            return

        new_skin = parts[1].strip().lower()
        available = {s["name"] for s in list_skins()}
        if new_skin not in available:
            print(f"  Unknown skin: {new_skin}")
            print(f"  Available: {', '.join(sorted(available))}")
            return

        set_active_skin(new_skin)
        _ACCENT.reset()  # Re-resolve ANSI color for the new skin
        _DIM.reset()  # Re-resolve dim/secondary ANSI color for the new skin
        if save_config_value("display.skin", new_skin):
            print(f"  Skin set to: {new_skin} (saved)")
        else:
            print(f"  Skin set to: {new_skin}")
        print("  Note: banner colors will update on next session start.")
        if self._apply_tui_skin_style():
            print("  Prompt + TUI colors updated.")

    def _toggle_verbose(self):
        """Cycle tool progress mode: off → new → all → verbose → off."""
        cycle = ["off", "new", "all", "verbose"]
        try:
            idx = cycle.index(self.tool_progress_mode)
        except ValueError:
            idx = 2  # default to "all"
        self.tool_progress_mode = cycle[(idx + 1) % len(cycle)]
        self.verbose = self.tool_progress_mode == "verbose"

        if self.agent:
            self.agent.verbose_logging = self.verbose
            self.agent.quiet_mode = not self.verbose
            self.agent.reasoning_callback = self._current_reasoning_callback()

        # Use raw ANSI codes via _cprint so the output is routed through
        # prompt_toolkit's renderer.  self.console.print() with Rich markup
        # writes directly to stdout which patch_stdout's StdoutProxy mangles
        # into garbled sequences like '?[33mTool progress: NEW?[0m' (#2262).
        from spark_cli.colors import Colors as _Colors

        labels = {
            "off": f"{_Colors.DIM}Tool progress: OFF{_Colors.RESET} - silent mode, just the final response.",
            "new": f"{_Colors.YELLOW}Tool progress: NEW{_Colors.RESET} - show each new tool (skip repeats).",
            "all": f"{_Colors.GREEN}Tool progress: ALL{_Colors.RESET} - show every tool call.",
            "verbose": f"{_Colors.BOLD}{_Colors.GREEN}Tool progress: VERBOSE{_Colors.RESET} - full args, results, think blocks, and debug logs.",
        }
        _cprint(labels.get(self.tool_progress_mode, ""))

    def _toggle_yolo(self):
        """Toggle YOLO mode - skip all dangerous command approval prompts."""
        import os

        current = bool(os.environ.get("SPARK_YOLO_MODE"))
        if current:
            os.environ.pop("SPARK_YOLO_MODE", None)
            self.console.print(
                "  WARN YOLO mode [bold red]OFF[/] - dangerous commands will require approval."
            )
        else:
            os.environ["SPARK_YOLO_MODE"] = "1"
            self.console.print(
                "  ⚡ YOLO mode [bold green]ON[/] - all commands auto-approved. Use with caution."
            )

    def _handle_reasoning_command(self, cmd: str):
        """Handle /reasoning - manage effort level and display toggle.

        Usage:
            /reasoning              Show current effort level and display state
            /reasoning <level>      Set reasoning effort (none, minimal, low, medium, high, xhigh)
            /reasoning show|on      Show model thinking/reasoning in output
            /reasoning hide|off     Hide model thinking/reasoning from output
        """
        parts = cmd.strip().split(maxsplit=1)

        if len(parts) < 2:
            # Show current state
            rc = self.reasoning_config
            if rc is None:
                level = "medium (default)"
            elif rc.get("enabled") is False:
                level = "none (disabled)"
            else:
                level = rc.get("effort", "medium")
            display_state = "on ✓" if self.show_reasoning else "off"
            _cprint(f"  {_ACCENT}Reasoning effort:  {level}{_RST}")
            _cprint(f"  {_ACCENT}Reasoning display: {display_state}{_RST}")
            _cprint(
                f"  {_DIM}Usage: /reasoning <none|minimal|low|medium|high|xhigh|show|hide>{_RST}"
            )
            return

        arg = parts[1].strip().lower()

        # Display toggle
        if arg in ("show", "on"):
            self.show_reasoning = True
            if self.agent:
                self.agent.reasoning_callback = self._current_reasoning_callback()
            save_config_value("display.show_reasoning", True)
            _cprint(f"  {_ACCENT}OK: Reasoning display: ON (saved){_RST}")
            _cprint(
                f"  {_DIM}  Model thinking will be shown during and after each response.{_RST}"
            )
            return
        if arg in ("hide", "off"):
            self.show_reasoning = False
            if self.agent:
                self.agent.reasoning_callback = self._current_reasoning_callback()
            save_config_value("display.show_reasoning", False)
            _cprint(f"  {_ACCENT}OK: Reasoning display: OFF (saved){_RST}")
            return

        # Effort level change
        parsed = _parse_reasoning_config(arg)
        if parsed is None:
            _cprint(f"  {_DIM}(._.) Unknown argument: {arg}{_RST}")
            _cprint(
                f"  {_DIM}Valid levels: none, minimal, low, medium, high, xhigh{_RST}"
            )
            _cprint(f"  {_DIM}Display:      show, hide{_RST}")
            return

        self.reasoning_config = parsed
        self.agent = None  # Force agent re-init with new reasoning config

        if save_config_value("agent.reasoning_effort", arg):
            _cprint(
                f"  {_ACCENT}OK: Reasoning effort set to '{arg}' (saved to config){_RST}"
            )
        else:
            _cprint(
                f"  {_ACCENT}OK: Reasoning effort set to '{arg}' (session only){_RST}"
            )

    def _handle_backend_command(self, cmd: str):
        """Handle /backend - show or set the command-execution backend."""
        from spark_cli.config import load_config

        valid = ("local", "docker", "ssh", "singularity", "modal", "daytona")
        parts = cmd.strip().split(maxsplit=1)
        current = (load_config().get("terminal", {}) or {}).get("backend", "local")
        if len(parts) < 2:
            _cprint(f"  {_ACCENT}Execution backend: {current}{_RST}")
            _cprint(f"  {_DIM}Usage: /backend <{'|'.join(valid)}>{_RST}")
            return
        arg = parts[1].strip().lower()
        if arg not in valid:
            _cprint(f"  {_DIM}(._.) Unknown backend: {arg}. Choose: {', '.join(valid)}{_RST}")
            return
        if save_config_value("terminal.backend", arg):
            _cprint(f"  {_ACCENT}OK: Execution backend set to '{arg}' (saved){_RST}")
            if arg != "local":
                _cprint(f"  {_DIM}Sandboxed backend — restart or new sessions use it.{_RST}")
        else:
            _cprint(f"  {_ACCENT}OK: Execution backend set to '{arg}' (session only){_RST}")

    def _handle_think_command(self, cmd: str):
        """Handle /think - quick reasoning-effort control.

        Usage: /think <off|low|med|high>  (off disables reasoning entirely).
        Maps to the same reasoning_config the agent reads; med→medium.
        """
        _LEVELS = {
            "off": "none",
            "none": "none",
            "low": "low",
            "med": "medium",
            "medium": "medium",
            "high": "high",
        }
        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2:
            rc = self.reasoning_config
            current = "medium (default)" if not rc else (
                "off" if rc.get("enabled") is False else rc.get("effort", "medium")
            )
            _cprint(f"  {_ACCENT}Thinking level: {current}{_RST}")
            _cprint(f"  {_DIM}Usage: /think <off|low|med|high>{_RST}")
            return

        arg = parts[1].strip().lower()
        level = _LEVELS.get(arg)
        if level is None:
            _cprint(f"  {_DIM}(._.) Unknown level: {arg}. Use off|low|med|high.{_RST}")
            return

        parsed = _parse_reasoning_config(level)
        self.reasoning_config = parsed
        self.agent = None  # Force agent re-init with new reasoning config
        shown = "off" if level == "none" else level
        if save_config_value("agent.reasoning_effort", level):
            _cprint(f"  {_ACCENT}OK: Thinking set to '{shown}' (saved){_RST}")
        else:
            _cprint(f"  {_ACCENT}OK: Thinking set to '{shown}' (session only){_RST}")

    def _handle_fast_command(self, cmd: str):
        """Handle /fast - toggle fast mode (OpenAI Priority Processing / Anthropic Fast Mode)."""
        if not self._fast_command_available():
            _cprint(
                "  (._.) /fast is only available for models that support fast mode (OpenAI Priority Processing or Anthropic Fast Mode)."
            )
            return

        # Determine the branding for the current model
        try:
            from spark_cli.models import _is_anthropic_fast_model

            agent = getattr(self, "agent", None)
            model = getattr(agent, "model", None) or getattr(self, "model", None)
            feature_name = (
                "Anthropic Fast Mode"
                if _is_anthropic_fast_model(model)
                else "Priority Processing"
            )
        except Exception:
            feature_name = "Fast mode"

        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or parts[1].strip().lower() == "status":
            status = "fast" if self.service_tier == "priority" else "normal"
            _cprint(f"  {_ACCENT}{feature_name}: {status}{_RST}")
            _cprint(f"  {_DIM}Usage: /fast [normal|fast|status]{_RST}")
            return

        arg = parts[1].strip().lower()

        if arg in {"fast", "on"}:
            self.service_tier = "priority"
            saved_value = "fast"
            label = "FAST"
        elif arg in {"normal", "off"}:
            self.service_tier = None
            saved_value = "normal"
            label = "NORMAL"
        else:
            _cprint(f"  {_DIM}(._.) Unknown argument: {arg}{_RST}")
            _cprint(f"  {_DIM}Usage: /fast [normal|fast|status]{_RST}")
            return

        self.agent = None  # Force agent re-init with new service-tier config
        if save_config_value("agent.service_tier", saved_value):
            _cprint(
                f"  {_ACCENT}OK: {feature_name} set to {label} (saved to config){_RST}"
            )
        else:
            _cprint(
                f"  {_ACCENT}OK: {feature_name} set to {label} (session only){_RST}"
            )

    def _on_reasoning(self, reasoning_text: str):
        """Callback for intermediate reasoning display during tool-call loops."""
        if not reasoning_text:
            return
        self._reasoning_preview_buf = (
            getattr(self, "_reasoning_preview_buf", "") + reasoning_text
        )
        self._flush_reasoning_preview(force=False)

    def _manual_compress(self, cmd_original: str = ""):
        """Manually trigger context compression on the current conversation.

        Accepts an optional focus topic: ``/compress <focus>`` guides the
        summariser to preserve information related to *focus* while being
        more aggressive about discarding everything else.  Inspired by
        Claude Code's ``/compact <focus>`` feature.
        """
        if not self.conversation_history or len(self.conversation_history) < 4:
            print(
                "(._.) Not enough conversation to compress (need at least 4 messages)."
            )
            return

        if not self.agent:
            print("(._.) No active agent -- send a message first.")
            return

        if not self.agent.compression_enabled:
            print("(._.) Compression is disabled in config.")
            return

        # Extract optional focus topic from the command (e.g. "/compress database schema")
        focus_topic = ""
        if cmd_original:
            parts = cmd_original.strip().split(None, 1)
            if len(parts) > 1:
                focus_topic = parts[1].strip()

        original_count = len(self.conversation_history)
        try:
            from agent.manual_compression_feedback import summarize_manual_compression
            from agent.model_metadata import estimate_messages_tokens_rough

            original_history = list(self.conversation_history)
            approx_tokens = estimate_messages_tokens_rough(original_history)
            if focus_topic:
                print(
                    f"🗜️  Compressing {original_count} messages (~{approx_tokens:,} tokens), "
                    f'focus: "{focus_topic}"...'
                )
            else:
                print(
                    f"🗜️  Compressing {original_count} messages (~{approx_tokens:,} tokens)..."
                )

            compressed, _ = self.agent._compress_context(
                original_history,
                self.agent._cached_system_prompt or "",
                approx_tokens=approx_tokens,
                focus_topic=focus_topic or None,
            )
            self.conversation_history = compressed
            new_tokens = estimate_messages_tokens_rough(self.conversation_history)
            summary = summarize_manual_compression(
                original_history,
                self.conversation_history,
                approx_tokens,
                new_tokens,
            )
            icon = "🗜️" if summary["noop"] else "✅"
            print(f"  {icon} {summary['headline']}")
            print(f"     {summary['token_line']}")
            if summary["note"]:
                print(f"     {summary['note']}")

        except Exception as e:
            print(f"  ❌ Compression failed: {e}")

    def _handle_feedback_command(self):
        """Handle /feedback — collect user feedback and POST to n8n webhook."""
        import httpx

        _cprint("\n  Submit Feedback\n")

        name = self._prompt_text_input("  Your name: ")
        if name is None:
            _cprint("  (cancelled)")
            return

        email = self._prompt_text_input("  Your email: ")
        if email is None:
            _cprint("  (cancelled)")
            return

        areas = ["Workspace", "Tasks", "Chat", "Cron", "Skills", "Settings"]
        area_idx = self._run_curses_picker("Webapp Area", areas)
        if area_idx is None:
            _cprint("  (cancelled)")
            return
        area = areas[area_idx]

        note = self._prompt_text_input("  Feedback: ")
        if note is None:
            _cprint("  (cancelled)")
            return

        payload = {"name": name, "email": email, "area": area, "note": note}

        try:
            resp = httpx.post(
                "https://n8n.automatedigital.ai/webhook/spark-feedback",
                json=payload,
                timeout=10,
            )
            resp.raise_for_status()
            _cprint("  ✓ Feedback submitted — thank you!\n")
        except Exception as exc:
            _cprint(f"  ✗ Failed to submit feedback: {exc}\n")

    def _handle_debug_command(self):
        """Handle /debug - upload debug report + logs and print paste URLs."""
        from types import SimpleNamespace

        from spark_cli.debug import run_debug_share

        args = SimpleNamespace(lines=200, expire=7, local=False)
        run_debug_share(args)

    def _handle_plan_command(self, cmd: str):
        """Handle /plan [request] - load the bundled plan skill."""
        parts = cmd.strip().split(maxsplit=1)
        user_instruction = parts[1].strip() if len(parts) > 1 else ""

        plan_path = build_plan_path(user_instruction)
        msg = build_skill_invocation_message(
            "/plan",
            user_instruction,
            task_id=self.session_id,
            runtime_note=(
                "Save the markdown plan with write_file to this exact relative path "
                f"inside the active workspace/backend cwd: {plan_path}"
            ),
        )

        if not msg:
            ChatConsole().print("[bold red]Failed to load the bundled /plan skill[/]")
            return

        _cprint(f"  📝 Plan mode queued via skill. Markdown plan target: {plan_path}")
        if hasattr(self, "_pending_input"):
            self._pending_input.put(msg)
        else:
            ChatConsole().print(
                "[bold red]Plan mode unavailable: input queue not initialized[/]"
            )

    def _handle_background_command(self, cmd: str):
        """Handle /background <prompt> - run a prompt in a separate background session.

        Spawns a new AIAgent in a background thread with its own session.
        When it completes, prints the result to the CLI without modifying
        the active session's conversation history.
        """
        parts = cmd.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            _cprint("  Usage: /background <prompt>")
            _cprint("  Example: /background Summarize the top HN stories today")
            _cprint(
                "  The task runs in a separate session and results display here when done."
            )
            return

        prompt = parts[1].strip()
        self._background_task_counter += 1
        task_num = self._background_task_counter
        task_id = f"bg_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"

        # Make sure we have valid credentials
        if not self._ensure_runtime_credentials():
            _cprint("  (>_<) Cannot start background task: no valid credentials.")
            return

        _cprint(
            f'  🔄 Background task #{task_num} started: "{prompt[:60]}{"..." if len(prompt) > 60 else ""}"'
        )
        _cprint(f"  Task ID: {task_id}")
        _cprint("  You can continue chatting - results will appear when done.\n")

        turn_route = self._resolve_turn_agent_config(prompt)

        def run_background():
            try:
                bg_agent = AIAgent(
                    model=turn_route["model"],
                    api_key=turn_route["runtime"].get("api_key"),
                    base_url=turn_route["runtime"].get("base_url"),
                    provider=turn_route["runtime"].get("provider"),
                    api_mode=turn_route["runtime"].get("api_mode"),
                    acp_command=turn_route["runtime"].get("command"),
                    acp_args=turn_route["runtime"].get("args"),
                    max_iterations=self.max_turns,
                    enabled_toolsets=self.enabled_toolsets,
                    quiet_mode=True,
                    verbose_logging=False,
                    session_id=task_id,
                    platform="cli",
                    session_db=self._session_db,
                    reasoning_config=self.reasoning_config,
                    service_tier=self.service_tier,
                    request_overrides=turn_route.get("request_overrides"),
                    providers_allowed=self._providers_only,
                    providers_ignored=self._providers_ignore,
                    providers_order=self._providers_order,
                    provider_sort=self._provider_sort,
                    provider_require_parameters=self._provider_require_params,
                    provider_data_collection=self._provider_data_collection,
                    fallback_model=self._fallback_model,
                )
                # Silence raw spinner; route thinking through TUI widget when no foreground agent is active.
                bg_agent._print_fn = lambda *_a, **_kw: None

                def _bg_thinking(text: str) -> None:
                    # Concurrent bg tasks may race on _spinner_text; acceptable for best-effort UI.
                    if not self._agent_running:
                        self._spinner_text = text
                        if self._app:
                            self._app.invalidate()

                bg_agent.thinking_callback = _bg_thinking

                result = bg_agent.run_conversation(
                    user_message=prompt,
                    task_id=task_id,
                )

                response = result.get("final_response", "") if result else ""
                if not response and result and result.get("error"):
                    response = f"Error: {result['error']}"

                # Display result in the CLI (thread-safe via patch_stdout).
                # Force a TUI refresh first so spinner/status bar don't overlap
                # with the output (fixes #2718).
                if self._app:
                    self._app.invalidate()
                    import time as _tmod

                    _tmod.sleep(0.05)  # brief pause for refresh
                print()
                ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
                _cprint(f"  ✅ Background task #{task_num} complete")
                _cprint(f'  Prompt: "{prompt[:60]}{"..." if len(prompt) > 60 else ""}"')
                ChatConsole().print(f"[{_accent_hex()}]{'─' * 40}[/]")
                if response:
                    try:
                        from spark_cli.skin_engine import get_active_skin

                        _skin = get_active_skin()
                        label = _skin.get_branding("response_label", "S Spark")
                        _resp_color = _skin.get_color("response_border", "#555555")
                        _resp_text = _skin.get_color("banner_text", "#FFF8DC")
                    except Exception:
                        label = "S Spark"
                        _resp_color = "#555555"
                        _resp_text = "#FFF8DC"

                    _chat_console = ChatConsole()
                    _chat_console.print(
                        Panel(
                            _rich_text_from_ansi(response),
                            title=f"[{_resp_color} bold]{label} (background #{task_num})[/]",
                            title_align="left",
                            border_style=_resp_color,
                            style=_resp_text,
                            box=rich_box.HORIZONTALS,
                            padding=(1, 2),
                        )
                    )
                else:
                    _cprint("  (No response generated)")

                # Play bell if enabled
                if self.bell_on_complete:
                    sys.stdout.write("\a")
                    sys.stdout.flush()

            except Exception as e:
                # Same TUI refresh pattern as success path (#2718)
                if self._app:
                    self._app.invalidate()
                    import time as _tmod

                    _tmod.sleep(0.05)
                print()
                _cprint(f"  ❌ Background task #{task_num} failed: {e}")
            finally:
                self._background_tasks.pop(task_id, None)
                # Clear spinner only if no foreground agent owns it
                if not self._agent_running:
                    self._spinner_text = ""
                if self._app:
                    self._invalidate(min_interval=0)

        thread = threading.Thread(
            target=run_background, daemon=True, name=f"bg-task-{task_id}"
        )
        self._background_tasks[task_id] = thread
        thread.start()

