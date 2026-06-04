"""OS keychain-backed secret storage for preview-pane credentials.

Any secret Spark manages itself (not the browser's own cookie jar) is stored in
the OS keychain via ``keyring`` — never plaintext on disk. ``keyring`` is an
optional dependency (``pip install 'spark-agent[keychain]'``); callers get a
clear error when it's missing, and reads degrade to ``None``.
"""

from __future__ import annotations

_SERVICE_PREFIX = "spark-preview"


class KeychainUnavailable(RuntimeError):
    """Raised when the `keyring` backend is not installed/available."""


def _keyring():
    try:
        import keyring  # type: ignore
    except ImportError as exc:
        raise KeychainUnavailable(
            "keyring is not installed — run `pip install 'spark-agent[keychain]'`"
        ) from exc
    return keyring


def _service(slug: str) -> str:
    return f"{_SERVICE_PREFIX}:{slug}"


def set_secret(slug: str, key: str, value: str) -> None:
    """Store a secret in the OS keychain, scoped to a workspace."""
    _keyring().set_password(_service(slug), key, value)


def get_secret(slug: str, key: str) -> str | None:
    """Read a secret from the keychain; returns None if absent or backend missing."""
    try:
        return _keyring().get_password(_service(slug), key)
    except KeychainUnavailable:
        return None


def delete_secret(slug: str, key: str) -> bool:
    """Delete a secret. Returns False if it didn't exist or the backend is missing."""
    try:
        kr = _keyring()
    except KeychainUnavailable:
        return False
    try:
        kr.delete_password(_service(slug), key)
        return True
    except Exception:
        return False
