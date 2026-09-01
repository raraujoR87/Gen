"""API key permission gate.

Per docs/ARCHITECTURE.md section 2 (Protocolo de Seguranca e Criptografia de
Credenciais), item 1: a exchange API key supplied by a user MUST have
withdrawal and external-transfer permissions disabled before this system will
accept it. Only spot trading and read-only balance access are allowed.

This is the mandatory gate that runs before any key is persisted (see
`backend.security.envelope` for how it is stored afterwards). No key may
reach `envelope.encrypt_secret` / the `exchange_accounts` table without first
passing `validate_key_permissions`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ccxt is used both as the exchange client abstraction and, indirectly, as
# the source of the `fetch_permissions` / `apiKey` metadata calls that most
# exchange adapters expose. We only rely on ccxt's exception types here so
# unit tests can inject a fake client without a live network call.
import ccxt


class InsecureApiKeyError(Exception):
    """Raised when an exchange API key has withdrawal or transfer rights.

    This is a hard-stop: the caller MUST NOT persist, encrypt, or otherwise
    use the offending key/secret pair. Treat this exception as a security
    boundary, not a recoverable/retryable error.
    """


# Permission flags that, if enabled, disqualify a key. Exchange APIs are not
# consistent about naming, so we normalize a handful of common aliases seen
# across ccxt unified `fetch_permissions()` / raw `permissions` payloads
# (Binance, Bybit, OKX, Kraken, Coinbase, ...) into this canonical set.
_WITHDRAWAL_ALIASES = frozenset({
    "withdraw",
    "withdrawal",
    "withdrawals",
    "enablewithdrawals",
    "can_withdraw",
    "canwithdraw",
})

_TRANSFER_ALIASES = frozenset({
    "transfer",
    "transfers",
    "internal_transfer",
    "internaltransfer",
    "enableinternaltransfer",
    "can_transfer",
    "cantransfer",
})

# Permissions that are required (must be present/true) for the key to be
# useful at all — a key that can't trade spot or read balances is useless
# to this system even though it isn't "insecure".
_REQUIRED_ALIASES = {
    "spot": frozenset({"spot", "spot_trading", "spottrading", "enablespottrading", "can_trade"}),
    "read": frozenset({"read", "read_only", "readonly", "enablereading", "can_read"}),
}


@dataclass(frozen=True)
class KeyPermissionReport:
    """Normalized result of a permission check, for logging/auditing."""

    exchange: str
    withdrawal_enabled: bool
    transfer_enabled: bool
    spot_trading_enabled: bool
    read_enabled: bool
    raw_permissions: dict[str, Any] = field(default_factory=dict)

    @property
    def is_safe(self) -> bool:
        return (
            not self.withdrawal_enabled
            and not self.transfer_enabled
            and self.spot_trading_enabled
            and self.read_enabled
        )


def _normalize_permissions(raw: dict[str, Any]) -> dict[str, bool]:
    """Lowercase/flatten a raw permissions dict from ccxt into `name -> bool`.

    Handles both `{"withdraw": True}` shaped dicts and list-shaped
    permissions like `{"permissions": ["SPOT", "READ"]}` (values default to
    True when the key's presence in a list is what signals it's enabled).
    """
    normalized: dict[str, bool] = {}

    def _add(name: Any, value: bool) -> None:
        if not isinstance(name, str):
            return
        normalized[name.strip().lower()] = bool(value)

    for key, value in raw.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                _add(sub_key, sub_value)
            continue
        if isinstance(value, (list, tuple, set)):
            for item in value:
                _add(item, True)
            continue
        _add(key, value)

    return normalized


def _flag_from_aliases(normalized: dict[str, bool], aliases: frozenset[str]) -> bool:
    return any(normalized.get(alias, False) for alias in aliases)


def evaluate_permissions(exchange_name: str, raw_permissions: dict[str, Any]) -> KeyPermissionReport:
    """Pure function: turn a raw ccxt permissions payload into a report.

    Does not raise; use `validate_key_permissions` (or check
    `report.is_safe`) for the enforcing gate.
    """
    normalized = _normalize_permissions(raw_permissions)

    return KeyPermissionReport(
        exchange=exchange_name,
        withdrawal_enabled=_flag_from_aliases(normalized, _WITHDRAWAL_ALIASES),
        transfer_enabled=_flag_from_aliases(normalized, _TRANSFER_ALIASES),
        spot_trading_enabled=_flag_from_aliases(normalized, _REQUIRED_ALIASES["spot"]),
        read_enabled=_flag_from_aliases(normalized, _REQUIRED_ALIASES["read"]),
        raw_permissions=raw_permissions,
    )


def fetch_key_permissions(exchange_client: Any) -> dict[str, Any]:
    """Query an authenticated ccxt exchange client for its API key permissions.

    `exchange_client` is expected to be a ccxt exchange instance (sync or a
    duck-typed test double) already constructed with the candidate
    apiKey/secret. Most ccxt exchanges expose either a unified
    `fetch_permissions()` method or a raw `apiKeyInfo`/`account` style call;
    we try the unified method first and fall back to `sapi_get_account`-style
    private calls when present, matching what real ccxt adapters expose.
    """
    if hasattr(exchange_client, "fetch_permissions"):
        try:
            return exchange_client.fetch_permissions() or {}
        except ccxt.NotSupported:
            pass
        except ccxt.BaseError as exc:
            raise InsecureApiKeyError(
                f"Could not verify permissions for exchange key on "
                f"{getattr(exchange_client, 'id', 'unknown')}: {exc}. "
                "Refusing to accept a key whose permissions cannot be verified."
            ) from exc

    # Fallback: some ccxt exchange objects surface a generic private
    # "account info" call that includes permission flags.
    for attr in ("fetch_account", "fetchAccount"):
        if hasattr(exchange_client, attr):
            result = getattr(exchange_client, attr)()
            if isinstance(result, dict):
                return result

    raise InsecureApiKeyError(
        "Exchange client does not expose a way to verify API key permissions "
        "(no fetch_permissions/fetch_account). Refusing to accept an "
        "unverifiable key."
    )


def validate_key_permissions(
    exchange_client: Any,
    *,
    exchange_name: str | None = None,
    raw_permissions: dict[str, Any] | None = None,
) -> KeyPermissionReport:
    """Mandatory gate: raises InsecureApiKeyError if the key is unsafe.

    Call this BEFORE any key/secret pair reaches `envelope.encrypt_secret`
    or is persisted to `exchange_accounts`. On success, returns the
    `KeyPermissionReport` for audit logging.

    Args:
        exchange_client: authenticated ccxt exchange instance (or test
            double) used to query permissions, unless `raw_permissions` is
            supplied directly (e.g. for unit tests or pre-fetched data).
        exchange_name: label for error messages / audit logs. Defaults to
            `exchange_client.id` when available.
        raw_permissions: skip the network call and evaluate this payload
            directly (primarily for tests).
    """
    name = exchange_name or getattr(exchange_client, "id", None) or "unknown"

    permissions = raw_permissions if raw_permissions is not None else fetch_key_permissions(exchange_client)
    report = evaluate_permissions(name, permissions)

    if report.withdrawal_enabled or report.transfer_enabled:
        raise InsecureApiKeyError(
            f"Rejected API key for exchange '{name}': withdrawal_enabled="
            f"{report.withdrawal_enabled}, transfer_enabled={report.transfer_enabled}. "
            "Only spot trading and balance read permissions are allowed — "
            "disable withdrawals and external transfers on this key before "
            "adding it."
        )

    if not report.spot_trading_enabled or not report.read_enabled:
        raise InsecureApiKeyError(
            f"Rejected API key for exchange '{name}': key must have spot "
            f"trading and balance read permissions enabled "
            f"(spot_trading_enabled={report.spot_trading_enabled}, "
            f"read_enabled={report.read_enabled})."
        )

    return report
