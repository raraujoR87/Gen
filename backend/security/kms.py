"""Thin wrapper around modal.Secret for the envelope-encryption master key.

Per docs/ARCHITECTURE.md section 2, item 4: exchange credentials are
encrypted at rest with a master key sourced from Modal's KMS
(`modal.Secret`), named by the `KMS_SECRET_NAME` env var (see
.env.example). This module is the single place that resolves that master
key so the rest of `backend.security` never talks to `modal` directly.

Dev/test fallback: if the `modal` package is not installed, or a
`modal.Secret` lookup fails (e.g. no Modal token configured, running in a
local pytest sandbox with no network), we fall back to reading the key
straight from an env var (`ENVELOPE_KEY_ID` by convention, see
.env.example) or from `MASTER_KEY_OVERRIDE` when explicitly supplied. This
fallback is intentionally loud (a warning, never silent) and is GATED
behind `TRADING_MODE` — if `TRADING_MODE=live`, the fallback is refused
and `KmsUnavailableError` is raised instead, because a live deployment
silently degrading to a locally-guessable key would defeat the entire
key-vault threat model. Only `testnet`/dev environments may fall back.
"""
from __future__ import annotations

import base64
import binascii
import os
import warnings

try:  # pragma: no cover - import guard exercised implicitly by test env
    import modal

    _MODAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    modal = None  # type: ignore[assignment]
    _MODAL_AVAILABLE = False

KEY_SIZE_BYTES = 32  # AES-256, must match backend.security.envelope.KEY_SIZE_BYTES


class KmsUnavailableError(Exception):
    """Raised when the master key cannot be obtained and no safe fallback applies."""


def _decode_key_material(raw: str) -> bytes:
    """Accept either raw base64 or hex-encoded 32-byte key material."""
    raw = raw.strip()
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == KEY_SIZE_BYTES:
            return decoded
    except (binascii.Error, ValueError):
        pass

    try:
        decoded = bytes.fromhex(raw)
        if len(decoded) == KEY_SIZE_BYTES:
            return decoded
    except ValueError:
        pass

    raise KmsUnavailableError(
        "Master key material is not a valid base64 or hex encoding of "
        f"{KEY_SIZE_BYTES} bytes."
    )


def _dev_fallback_key(env: dict) -> bytes:
    trading_mode = env.get("TRADING_MODE", "testnet").strip().lower()
    if trading_mode == "live":
        raise KmsUnavailableError(
            "modal.Secret lookup failed and TRADING_MODE=live: refusing to "
            "fall back to a local env-var master key in production. Fix "
            "the Modal KMS secret configuration instead."
        )

    raw = env.get("MASTER_KEY_OVERRIDE") or env.get("ENVELOPE_KEY_ID")
    if not raw or raw == "change-me":
        raise KmsUnavailableError(
            "No modal.Secret master key available and no local dev "
            "fallback key configured (set MASTER_KEY_OVERRIDE or "
            "ENVELOPE_KEY_ID to a real base64/hex 32-byte key for local "
            "development)."
        )

    warnings.warn(
        "backend.security.kms: modal.Secret unavailable, falling back to "
        "a local env-var master key. This is only acceptable in "
        "dev/testnet — never in production.",
        RuntimeWarning,
        stacklevel=2,
    )
    return _decode_key_material(raw)


def get_master_key(secret_name: str | None = None) -> bytes:
    """Return the 32-byte AES-256 master key used for envelope encryption.

    Resolution order:
      1. `modal.Secret(secret_name)` — the production path. The secret is
         expected to expose the key material under an env var also named
         `secret_name` (Modal's convention of injecting each secret's keys
         into the function environment) or under `MASTER_KEY` if present.
      2. Local dev fallback (env var), only when `TRADING_MODE != "live"`.

    Raises `KmsUnavailableError` if neither path yields a valid key.
    """
    secret_name = secret_name or os.environ.get("KMS_SECRET_NAME", "arbitrage-secrets")

    if _MODAL_AVAILABLE:
        try:
            modal.Secret.from_name(secret_name)  # type: ignore[union-attr]
            # In a real Modal function invocation, secrets referenced via
            # modal.Secret.from_name(...) are injected into os.environ by
            # the Modal runtime before the function body executes — there
            # is no separate "read the secret value" API from inside the
            # container. We therefore look the key up from the environment
            # under the secret's own name or MASTER_KEY, matching Modal's
            # documented behavior.
            raw = os.environ.get("MASTER_KEY") or os.environ.get(secret_name)
            if raw:
                return _decode_key_material(raw)
        except Exception as exc:  # noqa: BLE001 - broad: any modal/network failure degrades to fallback
            warnings.warn(
                f"backend.security.kms: modal.Secret('{secret_name}') lookup "
                f"failed ({exc!r}); attempting local dev fallback.",
                RuntimeWarning,
                stacklevel=2,
            )

    return _dev_fallback_key(os.environ)
