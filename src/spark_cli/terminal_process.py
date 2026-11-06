"""Bounded termination for a terminal's exclusively owned process group."""

import os
import signal
import subprocess
import sys
from typing import Any


def terminate_terminal_process(proc: subprocess.Popen[Any]) -> None:
    """Escalate an owned session leader and reap it before acknowledging Stop."""
    if proc.returncode is not None:
        return
    if sys.platform == "win32":
        if proc.poll() is not None:
            return
        # Interactive PTYs remain unsupported; command runs own only this process.
        proc.terminate()
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        return
    if proc.pid == os.getpgrp():
        raise RuntimeError("Terminal does not own its process group")
    try:
        group = os.getpgid(proc.pid)
    except ProcessLookupError:
        # Darwin hides exited leaders from getpgid even before waitpid. The
        # unreaped PID still fences the group created by start_new_session.
        group = proc.pid
    if group != proc.pid:
        raise RuntimeError("Terminal does not own its process group")
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        proc.wait(timeout=2)
        return
    # Do not reap the leader until escalation: retaining its PID prevents reuse
    # while killing any group members that outlive TERM (including the shell).
    import time

    time.sleep(0.5)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin may reject signalling a group containing only the exited
        # leader. Accept only independently confirmed leader exit.
        if proc.poll() is None:
            raise
    proc.wait(timeout=2)
