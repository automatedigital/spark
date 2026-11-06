"""Synthetic, real-persistence acceptance server, without runtime/provider startup."""
import os
import sqlite3
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from spark_cli.memory_routes import register_memory_routes

home = Path(os.environ["SPARK_HOME"])
(home / "memories").mkdir(parents=True)
(home / "memories/MEMORY.md").write_text("Original project fact")
(home / "memories/USER.md").write_text("Prefers concise answers")
reviews = home / "workspace/wiki/dreams"
reviews.mkdir(parents=True)
(reviews / "2026-11-06-explicit.md").write_text("# Real explicit review fixture\nHuman review required. <script>window.memoryXss=1</script>")
with sqlite3.connect(home / "memory_store.db") as db:
    db.execute("CREATE TABLE facts(fact_id INTEGER PRIMARY KEY, content TEXT, category TEXT, created_at TEXT)")
    db.executemany("INSERT INTO facts VALUES (?, ?, ?, ?)", [(i, f"Local fact {i} telescope <script>window.memoryXss=1</script>", "project", "2026-11-06") for i in range(1, 46)])
app = FastAPI()
register_memory_routes(app)
app.mount("/", StaticFiles(directory=os.environ["SP21_BUILT"], html=True), name="fixture")
uvicorn.run(app, host="127.0.0.1", port=int(os.environ["SP21_PORT"]), log_level="warning")
