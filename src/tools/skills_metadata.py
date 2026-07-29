"""Canonical skill provenance, identity, and capability resolution.

The web UI must never round-trip a filesystem path.  This module is the small,
dependency-light boundary shared by the CLI-facing skill discovery code and
the web management API.  Paths are resolved from the active Spark profile and
configured external roots on every call, so profile isolation and stale
metadata cannot leak across requests.
"""

from __future__ import annotations

import hashlib
import logging
from enum import Enum
from pathlib import Path
from typing import Any

from core.spark_constants import get_skills_dir

logger = logging.getLogger(__name__)


class SkillProvenance(str, Enum):
    BUNDLED = "bundled"
    SPARK_CREATED = "spark_created"
    HUB_INSTALLED = "hub_installed"
    LOCAL = "local"
    EXTERNAL = "external"


CAPABILITY_MATRIX: dict[str, dict[str, Any]] = {
    SkillProvenance.BUNDLED.value: {
        "editable": True,
        "deletable": True,
        "restorable": True,
        "removal_mode": "tombstone",
    },
    SkillProvenance.SPARK_CREATED.value: {
        "editable": True,
        "deletable": True,
        "restorable": False,
        "removal_mode": "delete",
    },
    SkillProvenance.HUB_INSTALLED.value: {
        "editable": True,
        "deletable": True,
        "restorable": False,
        "removal_mode": "hub_uninstall",
    },
    SkillProvenance.LOCAL.value: {
        "editable": True,
        "deletable": True,
        "restorable": False,
        "removal_mode": "delete",
    },
    SkillProvenance.EXTERNAL.value: {
        "editable": False,
        "deletable": False,
        "restorable": False,
        "removal_mode": "detach",
    },
}

_HIDDEN_DIRS = frozenset({".git", ".github", ".hub"})
_MAX_DESCRIPTION = 1024


def _external_dirs() -> list[Path]:
    try:
        from agent.skill_utils import get_external_skills_dirs

        return get_external_skills_dirs()
    except Exception:
        return []


def _roots() -> list[tuple[str, Path]]:
    """Return local profile root followed by validated external roots."""
    local = get_skills_dir().resolve()
    result: list[tuple[str, Path]] = [("local", local)]
    seen = {local}
    for root in _external_dirs():
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        result.append(("external", resolved))
    return result


def _parse_frontmatter(content: str) -> dict[str, Any]:
    try:
        from agent.skill_utils import parse_frontmatter

        parsed, _ = parse_frontmatter(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _manifest() -> dict[str, str]:
    try:
        manifest_path = get_skills_dir() / ".bundled_manifest"
        if not manifest_path.exists():
            return {}
        result: dict[str, str] = {}
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            name, separator, digest = line.partition(":")
            result[name.strip()] = digest.strip() if separator else ""
        return result
    except Exception:
        return {}


def _hub_entry(name: str, skill_dir: Path) -> dict[str, Any] | None:
    try:
        from tools.skills_hub import HubLockFile

        lock_path = get_skills_dir() / ".hub" / "lock.json"
        entry = HubLockFile(path=lock_path).get_installed(name)
        if not entry:
            return None
        install_path = str(entry.get("install_path") or "")
        if not install_path:
            return None
        expected = (get_skills_dir() / install_path).resolve()
        if expected == skill_dir.resolve():
            return entry
    except Exception:
        logger.debug("Unable to inspect Hub lock metadata", exc_info=True)
    return None


def _usage_entry(name: str) -> dict[str, Any] | None:
    try:
        from tools.skill_usage import get_skill_record

        record = get_skill_record(name)
        return record if isinstance(record, dict) else None
    except Exception:
        return None


def _dir_hash(directory: Path) -> str:
    try:
        from tools.skills_sync import _dir_hash as sync_hash

        return sync_hash(directory)
    except Exception:
        hasher = hashlib.md5()
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                hasher.update(str(path.relative_to(directory)).encode())
                hasher.update(path.read_bytes())
        return hasher.hexdigest()


def _bundled_root() -> Path:
    try:
        from tools.skills_sync import _get_bundled_dir

        return _get_bundled_dir().resolve()
    except Exception:
        return Path(__file__).resolve().parents[2] / "skills"


def _tombstones() -> set[str]:
    try:
        path = get_skills_dir() / ".bundled_tombstones"
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()


def _find_bundled_source(name: str) -> Path | None:
    bundled = _bundled_root()
    if not bundled.exists():
        return None
    for skill_md in bundled.rglob("SKILL.md"):
        if skill_md.parent.name != name:
            continue
        parsed = _parse_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace")[:100_000])
        if str(parsed.get("name") or skill_md.parent.name) == name:
            return skill_md.parent
    return None


def _display_location(root_kind: str, root: Path, skill_dir: Path, provenance: str) -> str:
    """Return a non-sensitive location label; never return the absolute path."""
    try:
        relative = skill_dir.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        relative = skill_dir.name
    if provenance == SkillProvenance.EXTERNAL.value:
        digest = hashlib.sha256(str(root).encode()).hexdigest()[:10]
        return f"external://{digest}/{relative}"
    if provenance == SkillProvenance.BUNDLED.value:
        return f"bundled://{relative}"
    return f"profile://skills/{relative}"


def _skill_id(root: Path, skill_dir: Path, provenance: str) -> str:
    # Hashing an absolute root avoids collisions between two external roots,
    # while keeping the value opaque and safe to place in a URL.
    payload = f"{provenance}\0{root.resolve()}\0{skill_dir.resolve()}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]


def _provenance(root_kind: str, root: Path, skill_dir: Path, name: str) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    if root_kind == "external":
        return SkillProvenance.EXTERNAL.value, None, None

    hub = _hub_entry(name, skill_dir)
    if hub is not None:
        return SkillProvenance.HUB_INSTALLED.value, hub, _usage_entry(name)

    # Bundled manifest entries have precedence over usage records.  A bundled
    # skill may be user-modified, but it remains bundled and sync-managed.
    manifest = _manifest()
    if name in manifest:
        bundled_source = _find_bundled_source(name)
        bundled_destination = None
        if bundled_source is not None:
            try:
                bundled_destination = (get_skills_dir() / bundled_source.relative_to(_bundled_root())).resolve()
            except ValueError:
                bundled_destination = None
        if bundled_destination == skill_dir.resolve() or name in _tombstones():
            return SkillProvenance.BUNDLED.value, None, _usage_entry(name)

    usage = _usage_entry(name)
    if usage and str(usage.get("created_by") or "").lower() in {
        "agent",
        "spark",
        "spark_created",
        "agent-created",
    }:
        return SkillProvenance.SPARK_CREATED.value, None, usage
    return SkillProvenance.LOCAL.value, None, usage


def resolve_skill(skill_dir: Path, *, root_kind: str | None = None) -> dict[str, Any] | None:
    """Resolve one already-discovered directory to the canonical API record."""
    try:
        skill_dir = skill_dir.resolve()
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return None
        roots = _roots()
        matched = None
        for kind, root in roots:
            try:
                skill_dir.relative_to(root)
            except ValueError:
                continue
            matched = (root_kind or kind, root)
            break
        if matched is None:
            return None
        kind, root = matched
        content = skill_md.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(content[:100_000])
        name = str(frontmatter.get("name") or skill_dir.name).strip()[:64]
        if not name:
            return None
        provenance, hub, usage = _provenance(kind, root, skill_dir, name)
        capabilities = dict(CAPABILITY_MATRIX[provenance])
        manifest = _manifest()
        modified = False
        if provenance == SkillProvenance.BUNDLED.value and manifest.get(name):
            modified = _dir_hash(skill_dir) != manifest[name]
        elif provenance == SkillProvenance.HUB_INSTALLED.value and hub:
            expected_hash = str(hub.get("content_hash") or "")
            try:
                from tools.skills_guard import content_hash

                actual_hash = content_hash(skill_dir)
            except Exception:
                actual_hash = _dir_hash(skill_dir)
            modified = bool(expected_hash and expected_hash != actual_hash)

        description = str(frontmatter.get("description") or "").strip()
        if len(description) > _MAX_DESCRIPTION:
            description = description[: _MAX_DESCRIPTION - 3] + "..."
        category = None
        try:
            relative = skill_dir.relative_to(root)
            if len(relative.parts) > 1:
                category = relative.parts[-2]
        except ValueError:
            pass

        detail = {
            "label": {
                SkillProvenance.BUNDLED.value: "Spark built-in",
                SkillProvenance.SPARK_CREATED.value: "Spark-created",
                SkillProvenance.HUB_INSTALLED.value: "Hub-installed",
                SkillProvenance.LOCAL.value: "Profile skill",
                SkillProvenance.EXTERNAL.value: "External / read-only",
            }[provenance],
            "source": str(hub.get("source") or "") if hub else provenance,
        }
        record = {
            "skill_id": _skill_id(root, skill_dir, provenance),
            "name": name,
            "description": description,
            "category": category,
            "provenance": provenance,
            "provenance_detail": detail,
            "trust_level": str((hub or {}).get("trust_level") or ("builtin" if provenance == "bundled" else "external" if provenance == "external" else "user")),
            "modified": modified,
            "location": _display_location(kind, root, skill_dir, provenance),
            "capabilities": capabilities,
            "enabled": True,
            "skill_state": str((usage or {}).get("state") or "active"),
            "use_count": int((usage or {}).get("use_count") or 0),
            "view_count": int((usage or {}).get("view_count") or 0),
            "patch_count": int((usage or {}).get("patch_count") or 0),
            # Internal-only values are removed by ``public_record``.
            "_path": skill_dir,
            "_root": root,
        }
        return record
    except (OSError, UnicodeError):
        return None


def iter_skill_records(*, include_duplicates: bool = True) -> list[dict[str, Any]]:
    """Discover skills across local and external roots using one resolver."""
    records: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for root_kind, root in _roots():
        if not root.exists():
            continue
        for skill_md in root.rglob("SKILL.md"):
            if any(part in _HIDDEN_DIRS for part in skill_md.parts):
                continue
            record = resolve_skill(skill_md.parent, root_kind=root_kind)
            if record is None:
                continue
            if not include_duplicates and record["name"] in seen_names:
                continue
            seen_names.add(record["name"])
            records.append(record)
    # Keep deliberately removed bundled entries addressable for restore.  The
    # destination is absent by design, but its opaque identity remains stable
    # and no content is returned until the user restores it.
    local_root = get_skills_dir().resolve()
    for name in sorted(_tombstones()):
        if name in seen_names:
            continue
        source = _find_bundled_source(name)
        if source is None:
            continue
        destination = local_root / source.relative_to(_bundled_root())
        try:
            frontmatter = _parse_frontmatter((source / "SKILL.md").read_text(encoding="utf-8")[:100_000])
        except (OSError, UnicodeError):
            continue
        description = str(frontmatter.get("description") or "").strip()[:_MAX_DESCRIPTION]
        relative = source.relative_to(_bundled_root())
        usage = _usage_entry(name) or {}
        record = {
            "skill_id": _skill_id(local_root, destination, SkillProvenance.BUNDLED.value),
            "name": name,
            "description": description,
            "category": relative.parts[-2] if len(relative.parts) > 1 else None,
            "provenance": SkillProvenance.BUNDLED.value,
            "provenance_detail": {"label": "Spark built-in", "source": "bundled"},
            "trust_level": "builtin",
            "modified": False,
            "location": _display_location("local", local_root, destination, SkillProvenance.BUNDLED.value),
            "capabilities": dict(CAPABILITY_MATRIX[SkillProvenance.BUNDLED.value]),
            "enabled": True,
            "skill_state": str(usage.get("state") or "active"),
            "use_count": int(usage.get("use_count") or 0),
            "view_count": int(usage.get("view_count") or 0),
            "patch_count": int(usage.get("patch_count") or 0),
            "removed": True,
            "_path": destination,
            "_root": local_root,
        }
        seen_names.add(name)
        records.append(record)
    records.sort(key=lambda row: (str(row.get("name") or "").lower(), row["skill_id"]))
    return records


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a record while stripping server-only filesystem handles."""
    return {key: value for key, value in record.items() if not key.startswith("_")}


def find_skill_by_id(skill_id: str) -> dict[str, Any] | None:
    if not isinstance(skill_id, str) or not skill_id or "/" in skill_id or "\\" in skill_id:
        return None
    matches = [r for r in iter_skill_records(include_duplicates=True) if r.get("skill_id") == skill_id]
    return matches[0] if len(matches) == 1 else None


def all_capabilities() -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in CAPABILITY_MATRIX.items()}
