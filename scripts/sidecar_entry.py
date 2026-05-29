#!/usr/bin/env python3
"""PyInstaller sidecar entrypoint for the Spark desktop app.

Starts the FastAPI web server (the same one behind ``spark dashboard``) bound
to loopback, with no browser auto-open. Tauri spawns this frozen binary as a
sidecar and points its window at http://127.0.0.1:<port>.

Usage:
    spark-server [port]      # default port 9119
"""

import os
import sys
import threading
import time
from pathlib import Path

# When running from source (not frozen), the project uses a ``src/`` layout where
# packages are imported bare (``from core...``, ``from spark_cli...``). Make sure
# ``src/`` is importable in that case. When frozen, PyInstaller bundles the
# packages at the top level so this is a no-op.
if not getattr(sys, "frozen", False):
    _SRC = Path(__file__).resolve().parent.parent / "src"
    if _SRC.is_dir() and str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))


def _watch_parent(initial_ppid: int) -> None:
    """Exit when our parent (the Tauri desktop shell) dies.

    The Rust side kills us on a clean app quit, but a SIGKILL/crash of the GUI
    bypasses that path and would leave this server orphaned on the port. This
    watchdog guarantees teardown regardless of how the parent exits: when the
    parent dies the process is reparented (ppid becomes 1), so we exit.
    """
    while True:
        time.sleep(2)
        ppid = os.getppid()
        if ppid == 1 or ppid != initial_ppid:
            os._exit(0)


def main() -> None:
    # Only arm the watchdog under the desktop sidecar (frozen + a real parent).
    if getattr(sys, "frozen", False):
        initial_ppid = os.getppid()
        if initial_ppid > 1:
            threading.Thread(
                target=_watch_parent, args=(initial_ppid,), daemon=True
            ).start()

    port = 9119
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port {sys.argv[1]!r}; using {port}", file=sys.stderr)

    # Never auto-open a browser from inside the desktop sidecar.
    os.environ.setdefault("SPARK_NO_BROWSER", "1")

    from spark_cli.web_server import start_server

    start_server(host="127.0.0.1", port=port, open_browser=False)


if __name__ == "__main__":
    main()
