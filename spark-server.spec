# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Spark desktop sidecar binary (`spark-server`).

Freezes the FastAPI web server (`spark dashboard`) into a self-contained
--onedir bundle that Tauri spawns as a sidecar.

Build:
    pyinstaller spark-server.spec --noconfirm

Output:
    dist/spark-server/spark-server   (binary + _internal/ support dir)
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = Path(os.getcwd()).resolve()
SRC = REPO_ROOT / "src"
ENTRY = REPO_ROOT / "scripts" / "sidecar_entry.py"
WEB_DIST = SRC / "spark_cli" / "web_dist"

# All first-party packages live under src/ and are imported bare
# (e.g. `from core...`, `from spark_cli...`). Put src/ on pathex so the
# Analysis picks them up, and recursively collect each package so dynamically
# imported submodules (tool modules discovered at runtime, gateway platforms,
# plugins, etc.) are not dropped by static analysis.
_FIRST_PARTY = [
    "core",
    "agent",
    "spark_cli",
    "tools",
    "gateway",
    "cron",
    "acp_adapter",
    "plugins",
]

hiddenimports = []
for _pkg in _FIRST_PARTY:
    hiddenimports += collect_submodules(_pkg, on_error="ignore")

# Runtime deps that are imported lazily / via strings and can be missed.
hiddenimports += collect_submodules("uvicorn", on_error="ignore")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "anyio",
]

# Bundle the pre-built frontend so the server can serve the SPA as a fallback.
datas = []
if WEB_DIST.is_dir():
    datas.append((str(WEB_DIST), "spark_cli/web_dist"))

# Trim large, unused optional backends to keep the bundle small.
excludes = [
    "torch",
    "modal",
    "wandb",
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "tinker",
    "atroposlib",
    "matplotlib",
    "tensorflow",
    # Qt is not a Spark dependency — it gets vacuumed in from the surrounding
    # (anaconda) environment. Its frameworks contain versioned symlinks that
    # break Tauri's resource bundler, and add ~hundreds of MB. Exclude it.
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "PyQtWebEngine",
    "qtpy",
    "qtconsole",
    "qtawesome",
    "IPython",
    "jupyter",
    "notebook",
    "spyder",
]


a = Analysis(
    [str(ENTRY)],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# --onedir: fast cold start (no per-launch unpack) and clean process kill
# (no bootloader re-exec child that escapes the parent kill). The resulting
# dist/spark-server/ directory is shipped as a Tauri bundle *resource* (not an
# externalBin sidecar, which requires a single file) and spawned from Rust.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="spark-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="spark-server",
)
