from dataclasses import FrozenInstanceError

import pytest

from agent.prompt_blocks import (
    PromptBlock,
    PromptBundle,
    StabilityScope,
    anthropic_system_segments,
    lint_prompt_blocks,
)


def _block(kind, content, scope, source, order):
    return PromptBlock.create(
        kind=kind, content=content, scope=scope, source=source, order=order,
    )


def _bundle(project="project rules", turn="hook A"):
    return PromptBundle.build([
        _block("identity", "Spark identity", "release", "spark", 0),
        _block("context", project, "project", "context:AGENTS.md", 1),
        _block("memory", "profile memory", "profile", "profile:memory", 2),
        _block("metadata", "Conversation started: today", "session", "session", 3),
        _block("hook", turn, "turn", "hook", 4),
    ])


def test_blocks_are_typed_hashed_ordered_and_immutable():
    bundle = _bundle()
    assert [segment.name for segment in bundle.segments] == ["release", "profile_project", "session"]
    assert all(block.content_hash and block.token_estimate >= 0 for block in bundle.blocks)
    assert bundle.render().index("Spark identity") < bundle.render().index("project rules")
    assert bundle.render().index("project rules") < bundle.render().index("Conversation started")
    with pytest.raises(FrozenInstanceError):
        bundle.blocks[0].content = "mutated"


def test_cache_reuse_invalidates_only_the_changed_scope():
    first = _bundle()
    same_project = _bundle(turn="different turn hook")
    changed_project = _bundle(project="changed AGENTS.md")
    assert first.segments[0].fingerprint == same_project.segments[0].fingerprint
    assert first.segments[1].fingerprint == same_project.segments[1].fingerprint
    assert first.segments[2].fingerprint != same_project.segments[2].fingerprint
    assert first.segments[0].fingerprint == changed_project.segments[0].fingerprint
    assert first.segments[1].fingerprint != changed_project.segments[1].fingerprint


def test_anthropic_adapter_uses_stable_prefix_breakpoints():
    system = anthropic_system_segments(_bundle(), cache_ttl="1h", ephemeral_suffix="turn-only diagnostic")
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert system[1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "cache_control" not in system[2]
    assert system[-1]["text"] == "turn-only diagnostic"


def test_prompt_lint_reports_without_removing_user_content():
    duplicate = _block("user", "same rule", StabilityScope.PROJECT, "context:a", 0)
    blocks = [
        duplicate,
        _block("user", "same rule", StabilityScope.PROJECT, "context:b", 1),
        _block("bad", "Conversation started: now", StabilityScope.RELEASE, "spark:bad", 2),
    ]
    issues = lint_prompt_blocks(blocks, [
        {"function": {"name": "z"}}, {"function": {"name": "a"}},
    ])
    assert {issue.code for issue in issues} == {
        "duplicate-guidance", "unstable-in-stable-segment", "unordered-tool-schemas",
    }
    assert [block.content for block in blocks] == ["same rule", "same rule", "Conversation started: now"]


def test_twenty_turn_uncached_input_reduction_exceeds_thirty_percent():
    release = "r" * 8_000
    project = "p" * 8_000
    session = "s" * 2_000
    bundle = PromptBundle.build([
        _block("release", release, "release", "spark", 0),
        _block("project", project, "project", "context:AGENTS.md", 1),
        _block("session", session, "session", "session", 2),
    ])
    release_tokens, project_tokens, session_tokens = [s.token_estimate for s in bundle.segments]
    baseline_uncached = (release_tokens + project_tokens + session_tokens) * 20
    segmented_write = release_tokens + project_tokens + session_tokens
    segmented_uncached = segmented_write + session_tokens * 19
    reduction = 1 - segmented_uncached / baseline_uncached
    assert reduction >= 0.30


def test_instruction_adherence_fixture_contains_every_scope_verbatim():
    bundle = _bundle()
    rendered = bundle.render()
    for required in ("Spark identity", "project rules", "profile memory", "Conversation started", "hook A"):
        assert required in rendered
