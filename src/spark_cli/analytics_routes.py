"""FastAPI routes for token/cost and skill usage analytics.

Extracted from web_server.py. Handlers open the session database lazily.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/usage")
async def get_usage_analytics(days: int = 30):
    from core.spark_state import SessionDB

    db = SessionDB()
    try:
        cutoff = time.time() - (days * 86400)
        cur = db._conn.execute(
            """
            SELECT date(started_at, 'unixepoch') as day,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read_tokens,
                   SUM(reasoning_tokens) as reasoning_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as actual_cost,
                   COUNT(*) as sessions
            FROM sessions WHERE started_at > ?
            GROUP BY day ORDER BY day
        """,
            (cutoff,),
        )
        daily = [dict(r) for r in cur.fetchall()]

        cur2 = db._conn.execute(
            """
            SELECT model,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   COALESCE(SUM(estimated_cost_usd), 0) as estimated_cost,
                   COUNT(*) as sessions
            FROM sessions WHERE started_at > ? AND model IS NOT NULL
            GROUP BY model ORDER BY SUM(input_tokens) + SUM(output_tokens) DESC
        """,
            (cutoff,),
        )
        by_model = [dict(r) for r in cur2.fetchall()]

        cur3 = db._conn.execute(
            """
            SELECT SUM(input_tokens) as total_input,
                   SUM(output_tokens) as total_output,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(reasoning_tokens) as total_reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0) as total_estimated_cost,
                   COALESCE(SUM(actual_cost_usd), 0) as total_actual_cost,
                   COUNT(*) as total_sessions
            FROM sessions WHERE started_at > ?
        """,
            (cutoff,),
        )
        totals = dict(cur3.fetchone())

        return {
            "daily": daily,
            "by_model": by_model,
            "totals": totals,
            "period_days": days,
        }
    finally:
        db.close()


@router.get("/skills")
async def get_skills_analytics(limit: int = 20):
    try:
        from tools.skill_usage import lifecycle_counts, top_skills
        return {
            "top_skills": top_skills(limit=limit),
            "lifecycle_counts": lifecycle_counts(),
        }
    except Exception as e:
        return {"top_skills": [], "lifecycle_counts": {"active": 0, "stale": 0, "archived": 0}, "error": str(e)}


def register_analytics_routes(app) -> None:
    app.include_router(router)
