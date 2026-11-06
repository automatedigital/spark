"""SP24 manual browser fixture: real SQLite and API, no inference.

Run with a synthetic SPARK_HOME and SPARK_E2E_ASSET_DIR pointing to a verified
external build. Seeds actual deterministic decisions into the optional SP15
outcome contract; this does not claim that the SP15 production writer is merged.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main():
    from agent.smart_model_routing import resolve_auto_route
    from core.spark_constants import get_spark_home
    from core.spark_state import SessionDB
    from spark_cli.config import save_config

    home = get_spark_home()
    if not os.environ.get("SPARK_HOME") or "sp24" not in str(home):
        raise RuntimeError("Use an explicitly synthetic SPARK_HOME containing sp24")
    endpoint = "http://127.0.0.1:1/v1"
    config = {"model": {"default": "fixture-primary", "provider": "custom:lab", "selection": "auto",
                        "base_url": endpoint, "api_mode": "chat_completions",
                        "auto": {"enabled": True, "roles": {
                            role: {"provider": "custom:lab", "model": role + "-fixture", "base_url": endpoint,
                                   "reasoning_effort": "", "fallback": []}
                            for role in ("lead", "balanced", "fast", "subagent")}}},
              "providers": {"lab": {"name": "Lab", "base_url": endpoint, "models": ["fixture-primary", "fast-fixture"]}}}
    if not (home / "config.yaml").exists():
        save_config(config)
    db = SessionDB()
    try:
        db.ensure_session("routing-fixture", source="web", model="fixture-primary")
        db.set_session_title("routing-fixture", "Routing fixture")
        for index, (prompt, context) in enumerate([
            ("hello", {}), ("explain this image", {"has_attachments": True}),
            ("delete all production data", {}), ("delete all production data", {"explicit_model": "fixture-primary"}),
        ]):
            route = resolve_auto_route(prompt, {"auto": config["model"]["auto"]},
                                       {"model": "fixture-primary", "provider": "custom:lab"}, context)
            if not db.get_web_turn_projection(f"routing-turn-{index}"):
                db.append_message("routing-fixture", "user", prompt)
                db.append_message("routing-fixture", "assistant", "Synthetic recorded answer; no model request.")
                decision = route.get("routing_decision")
                safe_decision = None
                if isinstance(decision, dict):
                    safe_decision = {key: decision[key][:500] for key in ("role", "desired_role", "reason")
                                     if isinstance(decision.get(key), str)}
                    for key in ("signals", "scores"):
                        safe_decision[key] = {str(k)[:80]: value for k, value in list(decision.get(key, {}).items())[:32]
                                              if isinstance(value, (bool, int)) and abs(value) < 1_000_000}
                db.upsert_web_turn_projection(f"routing-turn-{index}", "routing-fixture", {
                    "turn_id": f"routing-turn-{index}", "status": "completed", "started_at": index + 1,
                    "timing_summary": {"version": 1, "model": route["model"], "role": route["role"],
                                       "provider": route["runtime"]["provider"], "routing_reason": route["routing_reason"],
                                       **({"routing_decision": safe_decision} if safe_decision is not None else {})}})
        if not db.get_web_turn_projection("routing-legacy"):
            db.upsert_web_turn_projection("routing-legacy", "routing-fixture", {"status": "completed"})
    finally:
        db.close()

    from fastapi.staticfiles import StaticFiles

    import spark_cli.web_server as server

    server.WEB_DIST = Path(os.environ["SPARK_E2E_ASSET_DIR"])
    for route in server.app.routes:
        if getattr(route, "path", None) == "/assets":
            route.app = StaticFiles(directory=server.WEB_DIST / "assets")
    server.start_server(host="127.0.0.1", port=int(sys.argv[1]), open_browser=False)


if __name__ == "__main__":
    main()
