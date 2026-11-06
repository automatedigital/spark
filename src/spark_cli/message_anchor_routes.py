"""Profile-local, authenticated search-anchor reads."""
from fastapi import APIRouter, HTTPException, Query

from core.spark_state import SessionDB
from spark_cli.message_anchor import read_message_window

router = APIRouter(prefix="/api/sessions", tags=["history"])


@router.get("/{session_id}/message-window/{message_id}")
def get_message_window(
    session_id: str, message_id: int, limit: int = Query(50, ge=2, le=200),
    before_id: int | None = Query(None, ge=1), after_id: int | None = Query(None, ge=1),
):
    from spark_cli.web_server import _message_for_history_response

    db = SessionDB()
    try:
        result = read_message_window(
            db, session_id, message_id, limit=limit, before_id=before_id, after_id=after_id,
        )
        result["messages"] = [_message_for_history_response(m) for m in result["messages"]]
        return result
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    finally:
        db.close()
