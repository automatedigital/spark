"""Tool-output normalization pipeline (TokenJuice port).

Ported from OpenHuman (`src/openhuman/tokenjuice/` in the reference repo).
Applies rule-driven compaction to tool handler return strings before they
are appended to conversation history: ANSI stripping, dedup, head/tail
summarization, JSON pretty-print, pattern filtering.

Three-layer rule overlay (later layers override earlier by rule `id`):
  1. Builtin     — ``normalization_rules/builtin.json`` (shipped)
  2. User        — ``{SPARK_HOME}/normalization_rules/*.json``
  3. Project     — ``./.spark/normalization_rules/*.json``

Entry point: ``compact_tool_output(result, tool_name, argv=None, rules=None)``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Outputs shorter than this skip the pipeline entirely (mirrors OH).
TINY_OUTPUT_MAX_CHARS = 240

_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


# --------------------------------------------------------------------------
# Rule schema (mirrors openhuman/tokenjuice/types.rs)
# --------------------------------------------------------------------------


@dataclass
class RuleMatch:
    tool_names: list[str] = field(default_factory=list)
    argv0: list[str] = field(default_factory=list)
    argv_includes_any: list[str] = field(default_factory=list)
    argv_includes_all: list[str] = field(default_factory=list)
    command_includes_any: list[str] = field(default_factory=list)
    command_includes_all: list[str] = field(default_factory=list)


@dataclass
class RuleFilters:
    skip_patterns: list[re.Pattern] = field(default_factory=list)
    keep_patterns: list[re.Pattern] = field(default_factory=list)


@dataclass
class RuleTransforms:
    strip_ansi: bool = False
    trim_empty_edges: bool = False
    dedupe_adjacent: bool = False
    pretty_print_json: bool = False


@dataclass
class RuleSummarize:
    head: int | None = None
    tail: int | None = None


@dataclass
class RuleCounter:
    name: str
    pattern: re.Pattern


@dataclass
class Rule:
    id: str
    match: RuleMatch
    filters: RuleFilters
    transforms: RuleTransforms
    summarize: RuleSummarize | None = None
    counters: list[RuleCounter] = field(default_factory=list)


@dataclass
class CompiledRules:
    rules: list[Rule]

    def matching(self, tool_name: str, argv: list[str] | None) -> list[Rule]:
        argv = argv or []
        argv0 = argv[0] if argv else ""
        command = " ".join(argv)
        out = []
        for r in self.rules:
            m = r.match
            if m.tool_names and tool_name not in m.tool_names:
                continue
            if m.argv0 and argv0 not in m.argv0:
                continue
            if m.argv_includes_any and not any(x in argv for x in m.argv_includes_any):
                continue
            if m.argv_includes_all and not all(x in argv for x in m.argv_includes_all):
                continue
            if m.command_includes_any and not any(x in command for x in m.command_includes_any):
                continue
            if m.command_includes_all and not all(x in command for x in m.command_includes_all):
                continue
            out.append(r)
        return out


@dataclass
class CompactionStats:
    input_chars: int
    output_chars: int
    rules_applied: list[str] = field(default_factory=list)

    @property
    def reduction_ratio(self) -> float:
        if self.input_chars == 0:
            return 0.0
        return 1.0 - (self.output_chars / self.input_chars)


# --------------------------------------------------------------------------
# Rule compilation
# --------------------------------------------------------------------------


def _compile_patterns(items: Any) -> list[re.Pattern]:
    if not items:
        return []
    return [re.compile(p) for p in items]


def _parse_rule(raw: dict) -> Rule:
    m = raw.get("match", {})
    f = raw.get("filters", {})
    t = raw.get("transforms", {})
    s = raw.get("summarize")
    c = raw.get("counters", []) or []
    return Rule(
        id=raw["id"],
        match=RuleMatch(
            tool_names=list(m.get("tool_names", [])),
            argv0=list(m.get("argv0", [])),
            argv_includes_any=list(m.get("argv_includes_any", [])),
            argv_includes_all=list(m.get("argv_includes_all", [])),
            command_includes_any=list(m.get("command_includes_any", [])),
            command_includes_all=list(m.get("command_includes_all", [])),
        ),
        filters=RuleFilters(
            skip_patterns=_compile_patterns(f.get("skip_patterns")),
            keep_patterns=_compile_patterns(f.get("keep_patterns")),
        ),
        transforms=RuleTransforms(
            strip_ansi=bool(t.get("strip_ansi", False)),
            trim_empty_edges=bool(t.get("trim_empty_edges", False)),
            dedupe_adjacent=bool(t.get("dedupe_adjacent", False)),
            pretty_print_json=bool(t.get("pretty_print_json", False)),
        ),
        summarize=(
            RuleSummarize(head=s.get("head"), tail=s.get("tail")) if s else None
        ),
        counters=[
            RuleCounter(name=ce["name"], pattern=re.compile(ce["pattern"]))
            for ce in c
        ],
    )


def _load_rules_file(path: Path) -> list[Rule]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("normalize: failed to load %s: %s", path, e)
        return []
    if isinstance(data, dict):
        data = data.get("rules", [])
    try:
        return [_parse_rule(r) for r in data]
    except Exception as e:
        logger.warning("normalize: failed to parse rules from %s: %s", path, e)
        return []


def load_rules(user_dir: Path | None = None, project_dir: Path | None = None) -> CompiledRules:
    """Load and overlay builtin + user + project rules.

    Later layers override earlier layers by rule ``id``.
    """
    layers: list[list[Rule]] = []

    builtin = Path(__file__).parent / "normalization_rules" / "builtin.json"
    if builtin.exists():
        layers.append(_load_rules_file(builtin))

    if user_dir and user_dir.exists():
        for p in sorted(user_dir.glob("*.json")):
            layers.append(_load_rules_file(p))

    if project_dir and project_dir.exists():
        for p in sorted(project_dir.glob("*.json")):
            layers.append(_load_rules_file(p))

    merged: dict[str, Rule] = {}
    for layer in layers:
        for r in layer:
            merged[r.id] = r
    return CompiledRules(rules=list(merged.values()))


# Module-level cache, refreshed via reload_default_rules().
_default_rules: CompiledRules | None = None


def default_rules() -> CompiledRules:
    global _default_rules
    if _default_rules is None:
        user_dir = None
        try:
            from core.spark_constants import get_spark_home
            user_dir = get_spark_home() / "normalization_rules"
        except Exception:
            pass
        project_dir = Path.cwd() / ".spark" / "normalization_rules"
        _default_rules = load_rules(user_dir=user_dir, project_dir=project_dir)
    return _default_rules


def reload_default_rules() -> CompiledRules:
    global _default_rules
    _default_rules = None
    return default_rules()


# --------------------------------------------------------------------------
# Transform implementations
# --------------------------------------------------------------------------


def _apply_filters(lines: list[str], filters: RuleFilters) -> list[str]:
    if not filters.skip_patterns and not filters.keep_patterns:
        return lines
    out = []
    for line in lines:
        if filters.keep_patterns and any(p.search(line) for p in filters.keep_patterns):
            out.append(line)
            continue
        if filters.skip_patterns and any(p.search(line) for p in filters.skip_patterns):
            continue
        out.append(line)
    return out


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _dedupe_adjacent(lines: list[str]) -> list[str]:
    out: list[str] = []
    prev = object()
    for line in lines:
        if line != prev:
            out.append(line)
            prev = line
    return out


def _trim_empty_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _summarize_head_tail(lines: list[str], head: int | None, tail: int | None) -> list[str]:
    n = len(lines)
    head = head or 0
    tail = tail or 0
    if head + tail >= n or (head == 0 and tail == 0):
        return lines
    elided = n - head - tail
    out: list[str] = []
    if head:
        out.extend(lines[:head])
    out.append(f"… {elided} lines elided …")
    if tail:
        out.extend(lines[-tail:])
    return out


def _apply_counters(lines: list[str], counters: list[RuleCounter]) -> tuple[list[str], list[str]]:
    if not counters:
        return lines, []
    counts = {c.name: 0 for c in counters}
    kept: list[str] = []
    for line in lines:
        matched = False
        for c in counters:
            if c.pattern.search(line):
                counts[c.name] += 1
                matched = True
                break
        if not matched:
            kept.append(line)
    summary = [f"summary: {name}={n}" for name, n in counts.items() if n]
    return kept, summary


def _maybe_pretty_print_json(text: str) -> str:
    s = text.strip()
    if not s or s[0] not in "{[":
        return text
    try:
        obj = json.loads(s)
    except Exception:
        return text
    return json.dumps(obj, indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def compact_tool_output(
    result: str,
    tool_name: str,
    argv: list[str] | None = None,
    rules: CompiledRules | None = None,
) -> tuple[str, CompactionStats]:
    """Apply matching normalization rules to a tool result string.

    Returns ``(compacted_text, stats)``. If no rules match or the input is
    below ``TINY_OUTPUT_MAX_CHARS``, returns the input unchanged.
    """
    input_chars = len(result)
    stats = CompactionStats(input_chars=input_chars, output_chars=input_chars)

    if not isinstance(result, str) or input_chars < TINY_OUTPUT_MAX_CHARS:
        return result, stats

    rules = rules if rules is not None else default_rules()
    matched = rules.matching(tool_name, argv)
    if not matched:
        return result, stats

    text = result
    # Apply transforms in a deterministic order: ANSI → JSON-pretty → line ops.
    if any(r.transforms.strip_ansi for r in matched):
        text = _strip_ansi(text)
    if any(r.transforms.pretty_print_json for r in matched):
        text = _maybe_pretty_print_json(text)

    lines = text.split("\n")

    for r in matched:
        lines = _apply_filters(lines, r.filters)
        if r.transforms.dedupe_adjacent:
            lines = _dedupe_adjacent(lines)
        if r.transforms.trim_empty_edges:
            lines = _trim_empty_edges(lines)
        if r.counters:
            lines, summary = _apply_counters(lines, r.counters)
            lines.extend(summary)
        if r.summarize and (r.summarize.head or r.summarize.tail):
            lines = _summarize_head_tail(lines, r.summarize.head, r.summarize.tail)

    out_text = "\n".join(lines)
    stats.output_chars = len(out_text)
    stats.rules_applied = [r.id for r in matched]
    return out_text, stats
