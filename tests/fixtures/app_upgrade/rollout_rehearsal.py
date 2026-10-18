"""Disposable old-source migration/backup/restore evidence; never use real state.

Run from the repository root with an activated venv:
    python tests/fixtures/app_upgrade/rollout_rehearsal.py --output /tmp/new-rehearsal
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

OLD_REF = "0ed3654b"


def load_old(repo: Path, output: Path, module: str):
    data = subprocess.check_output(["git", "show", f"{OLD_REF}:src/core/{module}.py"], cwd=repo)
    target = output / f"legacy_{module}.py"
    target.write_bytes(data)
    spec = importlib.util.spec_from_file_location(f"rehearsal_{module}", target)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def rows(path: Path, query: str):
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        return conn.execute(query).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[3]
    root = output / "original"
    profile = root / "profiles" / "rehearsal-lab"
    profile.mkdir(parents=True)
    # Set before importing any application state helpers. No HOME/CODEX_HOME changes.
    os.environ["SPARK_HOME"] = str(profile)
    from core.spark_state import SessionDB
    from spark_cli.backup import run_backup, run_import
    from spark_cli.sidebar_metadata import SidebarMetadata

    old = load_old(repo, output, "spark_state")
    old_kanban = load_old(repo, output, "kanban_db")
    assert old.SCHEMA_VERSION == 12
    files = {
        root / "config.yaml": "_config_version: 28\ndelegation:\n  async_enabled: false\n",
        profile / "config.yaml": "_config_version: 28\ndelegation:\n  async_enabled: false\n",
        profile / "skills" / "example.md": "Synthetic retained skill\n",
        profile / "drafts" / "example.txt": "Synthetic file draft; not browser storage\n",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    legacy = old.SessionDB(profile / "state.db")
    legacy.create_session("legacy-parent", "web")
    legacy.append_message("legacy-parent", "user", "Pre-upgrade WAL transcript")
    legacy.create_subagent_run({"id": "legacy-child", "parent_session_id": "legacy-parent", "status": "completed"})
    task = old_kanban.create_task(title="Pre-upgrade task", owner_profile="rehearsal-lab")
    assert rows(profile / "state.db", "SELECT version FROM schema_version") == [(12,)]
    assert (profile / "state.db-wal").stat().st_size > 0
    before = output / "before.zip"
    # Live WAL connection remains open while production SQLite backup runs.
    run_backup(argparse.Namespace(output=str(before)))
    legacy.close()
    upgraded = SessionDB(profile / "state.db")
    assert upgraded.get_messages("legacy-parent")[0]["content"] == "Pre-upgrade WAL transcript"
    assert upgraded.get_subagent_run("legacy-child")["status"] == "completed"
    assert rows(profile / "state.db", "SELECT version FROM schema_version") == [(15,)]
    from core import kanban_db
    assert kanban_db.get_task(task["id"])["title"] == "Pre-upgrade task"
    SidebarMetadata(upgraded).patch("legacy-parent", 0, {"pinned": True})
    upgraded.accept_runtime_command("legacy-parent", "subagent.dispatch", "post-backup", {}, {"handle": "synthetic"}, {})
    upgraded.append_message("legacy-parent", "user", "Post-backup work")
    for path, content in files.items():
        assert path.read_text() == content
    upgraded.close()
    # Idempotent second open, then datastore-only old-code read/write compatibility.
    reopened = SessionDB(profile / "state.db")
    assert len(reopened.get_messages("legacy-parent")) == 2
    reopened.close()
    legacy = old.SessionDB(profile / "state.db")
    assert len(legacy.get_messages("legacy-parent")) == 2
    legacy.append_message("legacy-parent", "assistant", "Old datastore writer on additive schema")
    legacy.close()
    assert rows(profile / "state.db", "SELECT version FROM schema_version") == [(15,)]
    after = output / "after.zip"
    run_backup(argparse.Namespace(output=str(after)))
    restored = {}
    for name, archive, expected_count, expected_version in (
        ("rollback", before, 1, 12), ("current", after, 3, 15),
    ):
        destination = output / name
        os.environ["SPARK_HOME"] = str(destination / "profiles" / "rehearsal-lab")
        # Only redirect profile alias filesystem output; import/extraction and DBs are real.
        with patch("spark_cli.profiles._get_wrapper_dir", return_value=destination / "aliases"):
            run_import(argparse.Namespace(zipfile=str(archive), force=True))
        restored_profile = destination / "profiles" / "rehearsal-lab"
        dbpath = restored_profile / "state.db"
        assert rows(dbpath, "SELECT version FROM schema_version") == [(expected_version,)]
        assert len(rows(dbpath, "SELECT content FROM messages")) == expected_count
        assert rows(restored_profile / "kanban.db", "SELECT title FROM tasks") == [("Pre-upgrade task",)]
        for path, content in files.items():
            assert (destination / path.relative_to(root)).read_text() == content
        assert (destination / "aliases" / "rehearsal-lab").is_file()
        restored[name] = {"schema_version": expected_version, "message_count": expected_count, "integrity": "ok"}
        if name == "rollback":
            assert not rows(dbpath, "SELECT name FROM sqlite_master WHERE name IN ('runtime_command_receipts','sidebar_thread_metadata')")
            rollback = old.SessionDB(dbpath)
            assert rollback.get_messages("legacy-parent")[0]["content"] == "Pre-upgrade WAL transcript"
            rollback.close()
    archives = {}
    for archive in (before, after):
        with zipfile.ZipFile(archive) as zf:
            assert not any(n.endswith((".db-wal", ".db-shm", ".db-journal")) for n in zf.namelist())
            archives[archive.name] = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "members": zf.namelist()}
    result = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "old_source_commit": subprocess.check_output(["git", "rev-parse", OLD_REF], cwd=repo, text=True).strip(),
        "output": str(output), "restored": restored, "archives": archives,
        "checks": ["real schema12 creation", "live WAL consistent backup", "12→15 additive migration", "repeat open", "legacy child/task/files preserved", "old datastore writer on schema15", "production backup/import in disposable profiles", "old backup restored and read by old datastore"],
        "rollback_loss": ["Post-backup user message", "Old datastore writer message", "Post-backup command receipt", "Post-backup sidebar pin"],
        "limits": ["Datastore compatibility only; not full old-app/runtime compatibility", "Synthetic skill/file draft, not browser IndexedDB or localStorage", "Alias output redirected to disposable directory", "No real user state, providers, workers or external sends", "No installed desktop/Windows/staging/production acceptance"],
    }
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
