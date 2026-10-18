"""Bind the production gateway policy without starting a gateway or provider."""
from types import SimpleNamespace


def bind_approval_policy(adapter):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.pairing_store = SimpleNamespace(is_approved=lambda platform, user: False)
    adapter.set_approval_authorizer(runner._is_user_authorized)
    return runner
