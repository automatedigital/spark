"""Read-only discovery index; instruction bodies remain owned by skill detail.

The bounded in-memory cache is keyed by canonical root, stat identity and profile
sidecar revisions. Each request discovers paths/stats, so external replacement,
addition and deletion invalidate without watchers. Refresh discards parsed headers.
No skill setup, credential capture or installation runs here.
"""
from __future__ import annotations

import os
import shutil
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any

from core.spark_constants import get_spark_home

HEADER_LIMIT = 16_384
_CACHE_LIMIT = 4096
_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
_lock = RLock()


def read_header(path: Path) -> str:
    """Read at most 16 KiB, stopping at the frontmatter terminator.

    Unterminated/oversized headers are unknown, never parsed as a partial YAML
    declaration. A body is never read beyond the bounded first line probe.
    """
    with path.open("rb") as stream:
        first = stream.readline(HEADER_LIMIT + 1)
        if first.strip() != b"---":
            return ""
        lines = [first]
        remaining = HEADER_LIMIT - len(first)
        while remaining > 0:
            line = stream.readline(remaining + 1)
            if not line or len(line) > remaining:
                return ""
            lines.append(line)
            remaining -= len(line)
            if line.strip() == b"---":
                return b"".join(lines).decode("utf-8", errors="replace")
    return ""


def _revision(path: Path) -> tuple:
    try:
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    except OSError:
        return ()


def _requirements(frontmatter: dict[str, Any], credentials: dict[str, str]) -> tuple[list[dict], str]:
    from agent.skill_utils import extract_skill_conditions, skill_matches_platform
    from tools.skills_tool import _collect_prerequisite_values, _get_required_environment_variables

    env, commands = _collect_prerequisite_values(frontmatter)
    requirements: list[dict] = []
    for entry in _get_required_environment_variables(frontmatter, env):
        name = entry["name"]
        requirements.append({"kind": "credential", "name": name,
                             "optional": bool(entry.get("optional")),
                             "status": "present" if credentials.get(name) or os.environ.get(name) else "missing"})
    for command in commands:
        # Presence only: never execute a declared command or shell expression.
        simple = command.strip()
        present = bool(simple and not any(c.isspace() for c in simple) and shutil.which(simple))
        requirements.append({"kind": "command", "name": simple[:128], "optional": False,
                             "status": "present" if present else "missing"})
    for kind, names in extract_skill_conditions(frontmatter).items():
        if not kind.startswith("requires_"):
            continue
        if not isinstance(names, list):
            continue
        for name in names:
            requirements.append({"kind": kind, "name": str(name)[:128], "optional": False,
                                 "status": "unknown"})
    if not skill_matches_platform(frontmatter):
        return requirements, "unsupported"
    if any(r["status"] == "missing" and not r["optional"] for r in requirements):
        return requirements, "missing_requirements"
    if any(r["status"] == "unknown" for r in requirements):
        return requirements, "unknown"
    return requirements, "available"


def list_skill_index(*, refresh: bool = False, query: str = "", scope: str = "all") -> list[dict[str, Any]]:
    from spark_cli.config import load_config
    from spark_cli.skills_config import get_disabled_skills
    from tools.skills_metadata import (
        _HIDDEN_DIRS,
        _load_quality_artifacts,
        _parse_frontmatter,
        _roots,
        public_record,
        resolve_skill,
    )
    from tools.skills_tool import load_env

    roots = _roots()
    home = get_spark_home()
    sidecars = tuple(_revision(home / path) for path in (
        "skills/.usage.json", "skills/.bundled_manifest", "skills/.bundled_tombstones", "skills/.hub/lock.json",
    ))
    disabled = get_disabled_skills(load_config())
    credentials = load_env()
    records = []
    with _lock:
        if refresh:
            _cache.clear()
        artifacts = None
        for kind, root in roots:
            row_scope = "profile" if kind == "local" else "external"
            if scope not in ("all", row_scope):
                continue
            for path in root.rglob("SKILL.md"):
                if any(part in _HIDDEN_DIRS for part in path.relative_to(root).parts):
                    continue
                try:
                    # Match canonical resolver containment; never index an escaped link.
                    path.resolve().relative_to(root.resolve())
                except (ValueError, OSError):
                    continue
                key = (str(root), str(path), _revision(path), sidecars)
                cached = _cache.get(key)
                if cached is None:
                    if artifacts is None:
                        artifacts = _load_quality_artifacts()
                    row = resolve_skill(path.parent, root_kind=kind, artifacts=artifacts, metadata_only=True)
                    if row is None:
                        continue
                    # Quality/detail fields remain available on selection; discovery
                    # keeps only the row contract and explicit identity/source labels.
                    fields = {"skill_id", "name", "description", "category", "provenance",
                              "provenance_detail", "trust_level", "source", "location", "enabled",
                              "skill_state", "use_count", "view_count", "patch_count"}
                    summary = {key: value for key, value in public_record(row).items() if key in fields}
                    cached = {"row": summary, "header": _parse_frontmatter(read_header(path))}
                    _cache[key] = cached
                    while len(_cache) > _CACHE_LIMIT:
                        _cache.popitem(last=False)
                else:
                    _cache.move_to_end(key)
                row = dict(cached["row"])
                row["scope"] = row_scope
                row["enabled"] = row["name"] not in disabled
                row["requirements"], readiness = _requirements(cached["header"], credentials)
                row["readiness"] = readiness if row["enabled"] else "disabled"
                if query.casefold() not in f'{row["name"]} {row["description"]}'.casefold():
                    continue
                records.append(row)
    names: dict[str, int] = {}
    for row in records:
        names[row["name"]] = names.get(row["name"], 0) + 1
    for row in records:
        if names[row["name"]] > 1:
            row["duplicate_warning"] = "Duplicate name; select by source and stable identity. Toggles apply to all skills with this name."
    return sorted(records, key=lambda row: (row["name"].casefold(), row["skill_id"]))
