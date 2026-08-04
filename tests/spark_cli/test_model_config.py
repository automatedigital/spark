from spark_cli.model_config import (
    AUTO_ROLE_NAMES,
    normalize_auto_policy,
    read_auto_policy,
    read_global_model_config,
)


def test_legacy_model_smart_and_delegation_settings_project_to_auto_roles():
    config = {
        "model": {
            "default": "terra-model",
            "provider": "codex",
            "base_url": "https://codex.example/v1",
        },
        "agent": {"reasoning_effort": "high"},
        "smart_model_routing": {
            "enabled": True,
            "cheap_model": {
                "provider": "codex",
                "model": "luna-model",
                "api_mode": "responses",
            },
        },
        "delegation": {
            "provider": "codex",
            "model": "child-model",
            "reasoning_effort": "medium",
        },
    }

    normalized = normalize_auto_policy(config)
    roles = normalized["model"]["auto"]["roles"]
    assert set(roles) == set(AUTO_ROLE_NAMES)
    assert roles["lead"]["model"] == "terra-model"
    assert roles["balanced"]["provider"] == "codex"
    assert roles["fast"]["model"] == "luna-model"
    assert roles["subagent"]["model"] == "child-model"
    assert normalized["smart_model_routing"]["cheap_model"]["model"] == "luna-model"


def test_explicit_legacy_model_is_pinned_but_empty_model_defaults_to_auto():
    pinned = read_global_model_config({"model": {"default": "user-model"}})
    auto = read_global_model_config({"model": ""})

    assert pinned.selection == "pinned"
    assert pinned.is_pinned
    assert auto.selection == "auto"
    assert not auto.is_pinned


def test_auto_policy_reads_role_targets_without_inventing_models():
    policy = read_auto_policy(
        {
            "smart_model_routing": {
                "auto": {
                    "enabled": True,
                    "roles": {
                        "lead": {
                            "provider": "account",
                            "model": "lead-model",
                            "reasoning_effort": "high",
                            "fallback": ["balanced"],
                        }
                    },
                }
            }
        }
    )

    assert policy.role("lead").model == "lead-model"
    assert policy.role("lead").reasoning_effort == "high"
    assert policy.role("lead").fallback == ("balanced",)
    assert policy.role("fast").model == ""
