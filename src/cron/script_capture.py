"""Bounded subprocess capture for cron scripts."""

import asyncio
import locale
import os
import signal
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path

SCRIPT_STREAM_LIMIT = 64 * 1024


class _ScriptCapture(asyncio.SubprocessProtocol):
    def __init__(self) -> None:
        self.done = asyncio.get_running_loop().create_future()
        self.buffers: dict[int, bytearray | None] = {1: bytearray(), 2: bytearray()}
        self.pipe_error: Exception | None = None

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        buffer = self.buffers[fd]
        if buffer is None:
            return
        if len(buffer) + len(data) > SCRIPT_STREAM_LIMIT:
            # A partial stream can contain unfinished credential syntax, such
            # as a private key block with no ending delimiter.
            self.buffers[fd] = None
        else:
            buffer.extend(data)

    def pipe_connection_lost(self, fd: int, exc: Exception | None) -> None:
        if exc is not None:
            self.pipe_error = exc

    def connection_lost(self, exc: Exception | None) -> None:
        self.done.set_result(None)


async def _capture(
    command: list[str], cwd: Path, timeout: int
) -> tuple[int, bytearray | None, bytearray | None]:
    loop = asyncio.get_running_loop()
    transport, capture = await loop.subprocess_exec(
        _ScriptCapture,
        *command,
        stdin=None,
        cwd=cwd,
        start_new_session=os.name == "posix",
    )
    try:
        # Completion covers both process exit and EOF on both pipes.
        await asyncio.wait_for(asyncio.shield(capture.done), timeout)
    except TimeoutError as exc:
        raise subprocess.TimeoutExpired(command, timeout) from exc
    finally:
        if not capture.done.done() and os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(transport.get_pid(), signal.SIGKILL)
        # Close the pipe readers even if a descendant still holds a writer.
        transport.close()
        await capture.done

    if capture.pipe_error is not None:
        raise capture.pipe_error
    returncode = transport.get_returncode()
    assert returncode is not None
    return returncode, capture.buffers[1], capture.buffers[2]


def capture_script(
    command: list[str], cwd: Path, timeout: int
) -> tuple[int, bytearray | None, bytearray | None]:
    """Drain both streams concurrently. None denotes a discarded oversized stream."""

    def run() -> tuple[int, bytearray | None, bytearray | None]:
        return asyncio.run(_capture(command, cwd, timeout))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return run()

    # Keep the synchronous entry point usable from a thread that owns a loop.
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(run).result()


def decode_script_stream(buffer: bytearray) -> str:
    """Match subprocess text mode's default encoding and newline handling."""
    text = buffer.decode(locale.getpreferredencoding(False))
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()
