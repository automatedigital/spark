"""FastAPI routes for the mac API.

Extracted from web_server.py, which declared these directly on the app.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
import time
import urllib
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException

from spark_cli.web_runtime import _desktop_app_version, _is_desktop_app, _run_blocking

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mac", tags=["mac"])


GITHUB_REPO = "automatedigital/spark"


_mac_update_cache: dict[str, Any] = {"checked_at": 0.0, "result": None}


MAC_APP_BUNDLE_ID = "studio.fromtheroot.spark"


MAC_APP_INSTALL_PATH = Path("/Applications/Spark.app")


def _parse_version(tag: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def _fetch_latest_mac_release(timeout: float = 8.0) -> dict | None:
    """Query GitHub Releases for the latest tag and its .dmg asset."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "spark-desktop"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    download_url = None
    for asset in data.get("assets", []) or []:
        if str(asset.get("name", "")).lower().endswith(".dmg"):
            download_url = asset.get("browser_download_url")
            break
    return {
        "tag": data.get("tag_name") or data.get("name") or "",
        "download_url": download_url,
        "release_url": data.get("html_url"),
        # Markdown release notes, shown as the changelog in the update modal (§3.3).
        "release_notes": (data.get("body") or "").strip() or None,
        "release_name": data.get("name") or None,
        "published_at": data.get("published_at"),
    }


def _shell_quote(value: str | Path) -> str:
    import shlex

    return shlex.quote(str(value))


def _check_mac_update(force: bool = False) -> dict:
    """Compare the running app version against the latest GitHub release."""
    current = _desktop_app_version()
    result = {
        "update_available": False,
        "latest_version": None,
        "current_version": current,
        "download_url": None,
        "release_url": None,
        "release_notes": None,
        "release_name": None,
        "published_at": None,
    }
    now = time.time()
    if (
        not force
        and _mac_update_cache["result"] is not None
        and (now - _mac_update_cache["checked_at"]) < 21600
    ):
        return cast("dict[Any, Any]", _mac_update_cache["result"])
    try:
        rel = _fetch_latest_mac_release()
    except Exception:
        return result
    if not rel:
        return result
    latest = rel.get("tag") or ""
    result["latest_version"] = latest.lstrip("v") or None
    result["download_url"] = rel.get("download_url")
    result["release_url"] = rel.get("release_url")
    result["release_notes"] = rel.get("release_notes")
    result["release_name"] = rel.get("release_name")
    result["published_at"] = rel.get("published_at")
    if current and result["latest_version"]:
        result["update_available"] = _parse_version(
            str(result["latest_version"])
        ) > _parse_version(current)
    _mac_update_cache.update(checked_at=now, result=result)
    return result


def _build_mac_update_installer_script(
    *,
    dmg_path: Path,
    work_dir: Path,
    log_path: Path,
    install_path: Path = MAC_APP_INSTALL_PATH,
    bundle_id: str = MAC_APP_BUNDLE_ID,
    expected_version: str = "",
) -> str:
    """Build a detached macOS installer script for the downloaded Spark DMG."""

    staged_app = work_dir / "Spark.app"
    mount_dir = work_dir / "mount"
    script_path = work_dir / "install-spark-update.zsh"
    tmp_install_path = install_path.with_name(f"{install_path.name}.tmp")
    backup_path = install_path.with_name(f"{install_path.name}.previous")
    privileged_install_cmd = f"{_shell_quote(script_path)} --install-only".replace("\\", "\\\\").replace('"', '\\"')

    return f"""#!/bin/zsh
set -euo pipefail

DMG={_shell_quote(dmg_path)}
WORK_DIR={_shell_quote(work_dir)}
MOUNT_DIR={_shell_quote(mount_dir)}
STAGED_APP={_shell_quote(staged_app)}
INSTALL_PATH={_shell_quote(install_path)}
LOG_PATH={_shell_quote(log_path)}
BUNDLE_ID={_shell_quote(bundle_id)}
EXPECTED_VERSION={_shell_quote(expected_version)}
TMP_INSTALL_PATH={_shell_quote(tmp_install_path)}
BACKUP_PATH={_shell_quote(backup_path)}

log() {{
  /bin/mkdir -p "$(/usr/bin/dirname "$LOG_PATH")"
  /bin/echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_PATH"
}}

cleanup() {{
  if /sbin/mount | /usr/bin/grep -q "on $MOUNT_DIR "; then
    /usr/bin/hdiutil detach "$MOUNT_DIR" -quiet || true
  fi
}}
trap cleanup EXIT

perform_install() {{
  /bin/rm -rf "$TMP_INSTALL_PATH"
  /usr/bin/ditto "$STAGED_APP" "$TMP_INSTALL_PATH"
  /bin/rm -rf "$BACKUP_PATH"

  if [ -d "$INSTALL_PATH" ]; then
    /bin/mv "$INSTALL_PATH" "$BACKUP_PATH"
  fi

  if ! /bin/mv "$TMP_INSTALL_PATH" "$INSTALL_PATH"; then
    log "Replacement move failed; restoring previous app"
    if [ -d "$BACKUP_PATH" ] && [ ! -d "$INSTALL_PATH" ]; then
      /bin/mv "$BACKUP_PATH" "$INSTALL_PATH" || true
    fi
    return 1
  fi

  /bin/rm -rf "$BACKUP_PATH"
}}

if [ "${{1:-}}" = "--install-only" ]; then
  perform_install >> "$LOG_PATH" 2>&1
  exit $?
fi

log "Starting Spark desktop update install"
EXPECTED_VERSION="${{EXPECTED_VERSION#desktop-v}}"
EXPECTED_VERSION="${{EXPECTED_VERSION#v}}"
/bin/mkdir -p "$MOUNT_DIR"
/usr/bin/hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT_DIR" "$DMG" >> "$LOG_PATH" 2>&1

SOURCE_APP="$(/usr/bin/find "$MOUNT_DIR" -maxdepth 2 -type d -name 'Spark.app' -print -quit)"
if [ -z "$SOURCE_APP" ]; then
  log "No Spark.app found in release DMG"
  exit 2
fi

FOUND_BUNDLE_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$SOURCE_APP/Contents/Info.plist" 2>/dev/null || true)"
if [ "$FOUND_BUNDLE_ID" != "$BUNDLE_ID" ]; then
  log "Unexpected bundle id: $FOUND_BUNDLE_ID"
  exit 3
fi

SOURCE_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$SOURCE_APP/Contents/Info.plist" 2>/dev/null || true)"
if [ -n "$EXPECTED_VERSION" ] && [ "$SOURCE_VERSION" != "$EXPECTED_VERSION" ]; then
  log "Unexpected DMG version: $SOURCE_VERSION (expected $EXPECTED_VERSION)"
  exit 4
fi

/bin/rm -rf "$STAGED_APP"
/usr/bin/ditto "$SOURCE_APP" "$STAGED_APP" >> "$LOG_PATH" 2>&1
cleanup

/usr/bin/osascript -e 'tell application id "{bundle_id}" to quit' >> "$LOG_PATH" 2>&1 || true
APP_PROCESS_PATTERN="$INSTALL_PATH/Contents/MacOS/spark"
for _ in {{1..30}}; do
  if ! /usr/bin/pgrep -f "$APP_PROCESS_PATTERN" >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
if /usr/bin/pgrep -f "$APP_PROCESS_PATTERN" >/dev/null 2>&1; then
  log "Spark process did not exit; refusing to replace the running app"
  exit 5
fi

log "Installing Spark.app into Applications"
if ! perform_install >> "$LOG_PATH" 2>&1; then
  log "Direct install failed; requesting administrator privileges"
  /usr/bin/osascript -e "do shell script \\"{privileged_install_cmd}\\" with administrator privileges" >> "$LOG_PATH" 2>&1
fi

INSTALLED_VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$INSTALL_PATH/Contents/Info.plist" 2>/dev/null || true)"
if [ -n "$EXPECTED_VERSION" ] && [ "$INSTALLED_VERSION" != "$EXPECTED_VERSION" ]; then
  log "Install verification failed: $INSTALLED_VERSION (expected $EXPECTED_VERSION)"
  exit 6
fi
log "Verified installed Spark.app version $INSTALLED_VERSION"

/usr/bin/xattr -cr "$INSTALL_PATH" >> "$LOG_PATH" 2>&1 || true
/usr/bin/open "$INSTALL_PATH" >> "$LOG_PATH" 2>&1 || true
log "Spark desktop update install finished"
"""


@router.get("/update/check")
async def check_mac_update():
    """Check whether a newer macOS desktop app release is available."""
    if not _is_desktop_app() or sys.platform != "darwin":
        return {
            "update_available": False,
            "latest_version": None,
            "current_version": None,
            "download_url": None,
            "release_url": None,
        }
    return await _run_blocking(_check_mac_update, True)


@router.post("/update/run")
async def run_mac_update():
    """Download the latest macOS DMG and start a detached automatic installer."""
    if not _is_desktop_app() or sys.platform != "darwin":
        raise HTTPException(status_code=400, detail="Not running as the macOS desktop app")
    info = await _run_blocking(_check_mac_update, True)
    download_url = info.get("download_url")
    if not download_url:
        raise HTTPException(status_code=400, detail="No downloadable macOS release found")

    work_dir = Path(tempfile.mkdtemp(prefix="spark-mac-update-"))
    dest = work_dir / f"Spark-{info.get('latest_version') or 'latest'}.dmg"
    script_path = work_dir / "install-spark-update.zsh"
    log_path = work_dir / "install.log"

    def _download_and_start_installer() -> None:
        urllib.request.urlretrieve(download_url, dest)
        script_path.write_text(
            _build_mac_update_installer_script(
                dmg_path=dest,
                work_dir=work_dir,
                log_path=log_path,
                expected_version=info.get("latest_version") or "",
            )
        )
        script_path.chmod(0o700)
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                ["/bin/zsh", str(script_path)],
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

    try:
        await _run_blocking(_download_and_start_installer)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start macOS update installer: {exc}") from exc
    return {
        "ok": True,
        "path": str(dest),
        "installer_script": str(script_path),
        "log_path": str(log_path),
        "latest_version": info.get("latest_version"),
        "status": "installing",
    }


def register_mac_routes(app) -> None:
    app.include_router(router)
