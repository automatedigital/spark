import os
import sys
import tempfile
import threading
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

import pytest


TOOLS_DIR = Path(__file__).resolve().parents[2] / "src" / "tools"


def _load_tool_module(module_name: str, filename: str):
    spec = spec_from_file_location(module_name, TOOLS_DIR / filename)
    assert spec and spec.loader
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _reset_modules(prefixes: tuple[str, ...]):
    for name in list(sys.modules):
        if name.startswith(prefixes):
            sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def _restore_tool_and_agent_modules():
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "tools"
        or name.startswith("tools.")
        or name == "agent"
        or name.startswith("agent.")
    }
    try:
        yield
    finally:
        _reset_modules(("tools", "agent"))
        sys.modules.update(original_modules)


def _install_fake_tools_package():
    _reset_modules(("tools", "agent"))

    tools_package = types.ModuleType("tools")
    tools_package.__path__ = [str(TOOLS_DIR)]  # type: ignore[attr-defined]
    sys.modules["tools"] = tools_package

    env_package = types.ModuleType("tools.environments")
    env_package.__path__ = [str(TOOLS_DIR / "environments")]  # type: ignore[attr-defined]
    sys.modules["tools.environments"] = env_package

    agent_package = types.ModuleType("agent")
    agent_package.__path__ = []  # type: ignore[attr-defined]
    sys.modules["agent"] = agent_package
    sys.modules["agent.auxiliary_client"] = types.SimpleNamespace(
        call_llm=lambda *args, **kwargs: "",
    )

    sys.modules["tools.managed_tool_gateway"] = _load_tool_module(
        "tools.managed_tool_gateway",
        "managed_tool_gateway.py",
    )

    interrupt_event = threading.Event()
    sys.modules["tools.interrupt"] = types.SimpleNamespace(
        set_interrupt=lambda value=True: interrupt_event.set() if value else interrupt_event.clear(),
        is_interrupted=lambda: interrupt_event.is_set(),
        _interrupt_event=interrupt_event,
    )
    sys.modules["tools.approval"] = types.SimpleNamespace(
        detect_dangerous_command=lambda *args, **kwargs: None,
        check_dangerous_command=lambda *args, **kwargs: {"approved": True},
        check_all_command_guards=lambda *args, **kwargs: {"approved": True},
        load_permanent_allowlist=lambda *args, **kwargs: [],
        DANGEROUS_PATTERNS=[],
    )

    class _Registry:
        def register(self, **kwargs):
            return None

    from tools.registry import tool_error

    sys.modules["tools.registry"] = types.SimpleNamespace(
        registry=_Registry(), tool_error=tool_error,
    )

    class _DummyEnvironment:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def cleanup(self):
            return None

    sys.modules["tools.environments.base"] = types.SimpleNamespace(BaseEnvironment=_DummyEnvironment)
    sys.modules["tools.environments.local"] = types.SimpleNamespace(LocalEnvironment=_DummyEnvironment)
    sys.modules["tools.environments.singularity"] = types.SimpleNamespace(
        _get_scratch_dir=lambda: Path(tempfile.gettempdir()),
        SingularityEnvironment=_DummyEnvironment,
    )
    sys.modules["tools.environments.ssh"] = types.SimpleNamespace(SSHEnvironment=_DummyEnvironment)
    sys.modules["tools.environments.docker"] = types.SimpleNamespace(DockerEnvironment=_DummyEnvironment)
    sys.modules["tools.environments.modal"] = types.SimpleNamespace(ModalEnvironment=_DummyEnvironment)
    sys.modules["tools.environments.managed_modal"] = types.SimpleNamespace(ManagedModalEnvironment=_DummyEnvironment)


def test_browser_use_explicit_local_mode_stays_local_even_when_managed_gateway_is_ready(tmp_path):
    _install_fake_tools_package()
    (tmp_path / "config.yaml").write_text("browser:\n  cloud_provider: local\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("BROWSER_USE_API_KEY", None)
    env.update({
        "SPARK_HOME": str(tmp_path),
        "TOOL_GATEWAY_USER_TOKEN": "nous-token",
        "BROWSER_USE_GATEWAY_URL": "http://127.0.0.1:3009",
    })

    with patch.dict(os.environ, env, clear=True):
        browser_tool = _load_tool_module("tools.browser_tool", "browser_tool.py")

        local_mode = browser_tool._is_local_mode()
        provider = browser_tool._get_cloud_provider()

    assert local_mode is True
    assert provider is None


def test_browserbase_does_not_use_gateway_only_configuration():
    _install_fake_tools_package()
    env = os.environ.copy()
    env.pop("BROWSERBASE_API_KEY", None)
    env.pop("BROWSERBASE_PROJECT_ID", None)
    env.update({
        "TOOL_GATEWAY_USER_TOKEN": "nous-token",
        "BROWSERBASE_GATEWAY_URL": "http://127.0.0.1:3009",
    })

    with patch.dict(os.environ, env, clear=True):
        browserbase_module = _load_tool_module(
            "tools.browser_providers.browserbase",
            "browser_providers/browserbase.py",
        )
        provider = browserbase_module.BrowserbaseProvider()

    assert provider.is_configured() is False


def test_terminal_tool_auto_mode_falls_back_to_direct_modal_when_managed_unavailable():
    _install_fake_tools_package()
    env = os.environ.copy()
    env.update({
        "MODAL_TOKEN_ID": "tok-id",
        "MODAL_TOKEN_SECRET": "tok-secret",
    })

    with patch.dict(os.environ, env, clear=True):
        terminal_tool = _load_tool_module("tools.terminal_tool", "terminal_tool.py")

        with (
            patch.object(terminal_tool, "is_managed_tool_gateway_ready", return_value=False),
            patch.object(terminal_tool, "_ManagedModalEnvironment", return_value="managed-modal-env") as managed_ctor,
            patch.object(terminal_tool, "_ModalEnvironment", return_value="direct-modal-env") as direct_ctor,
        ):
            result = terminal_tool._create_environment(
                env_type="modal",
                image="python:3.11",
                cwd="/root",
                timeout=60,
                container_config={
                    "container_cpu": 1,
                    "container_memory": 2048,
                    "container_disk": 1024,
                    "container_persistent": True,
                    "modal_mode": "auto",
                },
                task_id="task-modal-direct-fallback",
            )

    assert result == "direct-modal-env"
    assert direct_ctor.called
    assert not managed_ctor.called


def test_terminal_tool_respects_direct_modal_mode_without_falling_back_to_managed():
    _install_fake_tools_package()
    env = os.environ.copy()
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)

    with patch.dict(os.environ, env, clear=True):
        terminal_tool = _load_tool_module("tools.terminal_tool", "terminal_tool.py")

        with (
            patch.object(terminal_tool, "is_managed_tool_gateway_ready", return_value=True),
            patch.object(Path, "exists", return_value=False),
        ):
            with pytest.raises(ValueError, match="direct Modal credentials"):
                terminal_tool._create_environment(
                    env_type="modal",
                    image="python:3.11",
                    cwd="/root",
                    timeout=60,
                    container_config={
                        "container_cpu": 1,
                        "container_memory": 2048,
                        "container_disk": 1024,
                        "container_persistent": True,
                        "modal_mode": "direct",
                    },
                    task_id="task-modal-direct-only",
                )
