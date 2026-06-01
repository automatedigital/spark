"""Slash-command handler methods for SparkCLI (mixin).

Extracted from core/cli/__init__.py (Phase 3). A mixin carrying the /personality,
/cron, /dream, /learnings, /curator, /goal, /skills command handlers. Combined into
SparkCLI via inheritance; methods run with full access to SparkCLI state (self).
"""

from __future__ import annotations

import json

from core.cli.config_state import save_config_value
from core.cli.render import _ACCENT, _DIM, _RST, _cprint


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

