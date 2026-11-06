"""Isolated browser ledger with real SQLite and no execution/delivery calls."""
from cron.history import History
from core.spark_constants import get_spark_home
from schedule_preview_fixture import app  # noqa: F401

history = History()
if not history.page()["attempts"]:
    home = get_spark_home()
    output = home / "cron/output/abcdef123456/2026-11-06_12-00-00.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("# SP18 safe saved result\nBrowser fixture")
    for index in range(25):
        attempt = history.accept({"id": "abcdef123456", "next_run_at": str(index)})
        history.start(attempt)
        history.executed(attempt, "success", output=output if index == 24 else None)
        if index == 23:
            # Crash after execution, before confirmed delivery.
            history.reconcile()
        else:
            history.finish(attempt, "error" if index == 24 else "silent", "fixture offline" if index == 24 else None)
