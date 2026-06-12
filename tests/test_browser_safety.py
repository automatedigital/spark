"""Tests for the agent-browser efficiency & safety features (PLAN.md 2b):

- accessibility-tree tool (``browser_a11y``)
- append-only action log (record/retrieve)
- permission-gate classifier + config flag

The agent-browser runtime is mocked throughout; these tests never spawn a
real browser.
"""

from __future__ import annotations

import json

import pytest

from tools import browser_action_log, browser_permission_gate

# ── Action log ────────────────────────────────────────────────────────────────


def test_action_log_record_and_read_roundtrip(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    browser_action_log.record_action(
        "navigate", status="ok", detail={"url": "https://example.com"}, slug="proj"
    )
    browser_action_log.record_action(
        "click", status="ok", detail={"ref": "@e5"}, slug="proj"
    )
    actions = browser_action_log.read_actions(slug="proj")
    assert [a["action"] for a in actions] == ["navigate", "click"]
    assert actions[0]["detail"]["url"] == "https://example.com"
    assert all("ts" in a for a in actions)


def test_action_log_path_under_spark_home(monkeypatch):
    from core.spark_constants import get_spark_home

    path = browser_action_log.log_path(slug="proj")
    assert str(path).startswith(str(get_spark_home()))
    assert path.name == "action_log.jsonl"


def test_action_log_session_slug_strips_prefix(monkeypatch):
    monkeypatch.setenv("SPARK_BROWSER_PREVIEW_SESSION", "spark-preview-mysite")
    browser_action_log.record_action("a11y", status="ok")
    # Reading by the bare slug must find the same bucket the env binding wrote.
    actions = browser_action_log.read_actions(slug="mysite")
    assert actions and actions[-1]["action"] == "a11y"


def test_action_log_since_ts_filter(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    browser_action_log.record_action("navigate", slug="s")
    first = browser_action_log.read_actions(slug="s")
    cutoff = first[-1]["ts"]
    browser_action_log.record_action("click", slug="s")
    later = browser_action_log.read_actions(slug="s", since_ts=cutoff)
    assert [a["action"] for a in later] == ["click"]


def test_action_log_read_missing_returns_empty(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    assert browser_action_log.read_actions(slug="never-written") == []


# ── Permission-gate classifier ────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_gate_state():
    browser_permission_gate.reset_state()
    yield
    browser_permission_gate.reset_state()


def test_classify_payment_is_sensitive():
    c = browser_permission_gate.classify_action(
        "click", url="https://shop.com/checkout", context_text="Pay Now"
    )
    assert c.sensitive
    assert c.category == browser_permission_gate.CATEGORY_PAYMENT


def test_classify_message_is_sensitive():
    c = browser_permission_gate.classify_action(
        "click", url="https://x.com", context_text="Send message"
    )
    assert c.sensitive
    assert c.category == browser_permission_gate.CATEGORY_MESSAGE


def test_classify_login_new_domain_is_sensitive():
    c = browser_permission_gate.classify_action(
        "click", url="https://bank.com/login", context_text="Sign in",
        is_new_domain=True,
    )
    assert c.sensitive
    assert c.category == browser_permission_gate.CATEGORY_LOGIN_NEW_DOMAIN
    assert c.domain == "bank.com"


def test_classify_login_known_domain_not_sensitive():
    browser_permission_gate.note_login_domain("https://accounts.known.com")
    c = browser_permission_gate.classify_action(
        "click", url="https://www.known.com/login", context_text="Sign in"
    )
    assert not c.sensitive


def test_classify_benign_action_not_sensitive():
    c = browser_permission_gate.classify_action(
        "click", url="https://example.com", context_text="Read more"
    )
    assert not c.sensitive


def test_grant_then_is_granted(monkeypatch):
    monkeypatch.delenv("SPARK_BROWSER_PREVIEW_SESSION", raising=False)
    c = browser_permission_gate.classify_action(
        "click", url="https://shop.com/checkout", context_text="Place order"
    )
    assert not browser_permission_gate.is_granted(c)
    browser_permission_gate.grant(c)
    assert browser_permission_gate.is_granted(c)


def test_gate_enabled_default_true(monkeypatch):
    # No config / unreadable config must fail safe to True.
    monkeypatch.setattr(
        "spark_cli.config.read_raw_config", lambda: {}, raising=True
    )
    assert browser_permission_gate.gate_enabled() is True


def test_gate_disabled_by_config(monkeypatch):
    monkeypatch.setattr(
        "spark_cli.config.read_raw_config",
        lambda: {"security": {"browser_confirm_sensitive": False}},
        raising=True,
    )
    assert browser_permission_gate.gate_enabled() is False


def test_config_default_has_safety_flag():
    from spark_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["security"]["browser_confirm_sensitive"] is True


# ── browser_a11y tool (runtime mocked) ────────────────────────────────────────


def test_browser_a11y_returns_structured_refs(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(
        bt,
        "_run_browser_command",
        lambda task_id, cmd, args, **kw: {
            "success": True,
            "data": {
                "refs": {
                    "e5": {"role": "button", "name": "Submit", "value": None},
                    "e6": {"role": "link", "name": "Home"},
                },
                "snapshot": "button Submit\nlink Home",
            },
        },
    )
    out = json.loads(bt.browser_a11y(interactive_only=True, task_id="t"))
    assert out["success"] is True
    assert out["element_count"] == 2
    refs = {e["ref"] for e in out["elements"]}
    assert refs == {"@e5", "@e6"}
    submit = next(e for e in out["elements"] if e["ref"] == "@e5")
    assert submit["role"] == "button"
    assert submit["name"] == "Submit"


def test_browser_a11y_records_action(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setenv("SPARK_BROWSER_PREVIEW_SESSION", "spark-preview-logslug")
    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(
        bt,
        "_run_browser_command",
        lambda task_id, cmd, args, **kw: {
            "success": True,
            "data": {"refs": {"e1": {"role": "button", "name": "X"}}, "snapshot": ""},
        },
    )
    bt.browser_a11y(task_id="t")
    actions = browser_action_log.read_actions(slug="logslug")
    assert any(a["action"] == "a11y" for a in actions)


def test_browser_a11y_error_path(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(
        bt,
        "_run_browser_command",
        lambda *a, **k: {"success": False, "error": "no page"},
    )
    out = json.loads(bt.browser_a11y(task_id="t"))
    assert out["success"] is False
    assert "no page" in out["error"]


# ── browser_click / browser_type permission gating (runtime mocked) ────────────


def test_browser_click_blocks_sensitive_then_proceeds_on_confirm(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(bt.browser_permission_gate, "gate_enabled", lambda: True)
    monkeypatch.setattr(bt, "_current_page_url", lambda tid: "https://shop.com/checkout")
    monkeypatch.setattr(bt, "_resolve_ref_label", lambda tid, ref: "Pay Now")
    monkeypatch.setattr(
        bt, "_run_browser_command", lambda *a, **k: {"success": True}
    )

    blocked = json.loads(bt.browser_click(ref="@e5", task_id="t"))
    assert blocked["needs_confirmation"] is True
    assert blocked["category"] == browser_permission_gate.CATEGORY_PAYMENT

    ok = json.loads(bt.browser_click(ref="@e5", task_id="t", confirm=True))
    assert ok["success"] is True


def test_browser_click_benign_not_gated(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(bt.browser_permission_gate, "gate_enabled", lambda: True)
    monkeypatch.setattr(bt, "_current_page_url", lambda tid: "https://example.com")
    monkeypatch.setattr(bt, "_resolve_ref_label", lambda tid, ref: "Read more")
    monkeypatch.setattr(
        bt, "_run_browser_command", lambda *a, **k: {"success": True}
    )
    out = json.loads(bt.browser_click(ref="@e9", task_id="t"))
    assert out["success"] is True


def test_browser_click_gate_disabled_skips(monkeypatch):
    import tools.browser_tool as bt

    monkeypatch.setattr(bt, "_is_camofox_mode", lambda: False, raising=False)
    monkeypatch.setattr(bt.browser_permission_gate, "gate_enabled", lambda: False)
    monkeypatch.setattr(bt, "_resolve_ref_label", lambda tid, ref: "Pay Now")
    monkeypatch.setattr(
        bt, "_run_browser_command", lambda *a, **k: {"success": True}
    )
    out = json.loads(bt.browser_click(ref="@e5", task_id="t"))
    assert out["success"] is True


# ── Registration loads end-to-end ─────────────────────────────────────────────


def test_browser_a11y_registered():
    from core.model_tools import _discover_tools
    from core.toolsets import resolve_toolset

    _discover_tools()
    assert "browser_a11y" in resolve_toolset("browser")
