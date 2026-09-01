"""Tests for backend.security: key validation, envelope encryption, KMS,
and ephemeral buffer zeroing."""
from __future__ import annotations

import os

import pytest

from backend.security.envelope import (
    KEY_SIZE_BYTES,
    EnvelopeDecryptionError,
    decrypt_secret,
    encrypt_secret,
)
from backend.security.ephemeral import ephemeral_secret, zero_buffer
from backend.security.key_validation import (
    InsecureApiKeyError,
    evaluate_permissions,
    validate_key_permissions,
)
from backend.security.kms import KmsUnavailableError, get_master_key


# ---------------------------------------------------------------------------
# key_validation
# ---------------------------------------------------------------------------

SAFE_PERMISSIONS = {
    "spot": True,
    "read": True,
    "withdraw": False,
    "transfer": False,
}

WITHDRAWAL_ENABLED_PERMISSIONS = {
    "spot": True,
    "read": True,
    "withdraw": True,
    "transfer": False,
}

TRANSFER_ENABLED_PERMISSIONS = {
    "spot": True,
    "read": True,
    "withdraw": False,
    "transfer": True,
}

LIST_SHAPED_UNSAFE_PERMISSIONS = {
    "permissions": ["SPOT", "READ", "WITHDRAWALS"],
}


def test_safe_key_passes_validation():
    report = validate_key_permissions(
        exchange_client=None, exchange_name="binance", raw_permissions=SAFE_PERMISSIONS
    )
    assert report.is_safe
    assert not report.withdrawal_enabled
    assert not report.transfer_enabled


def test_withdrawal_enabled_key_is_rejected():
    with pytest.raises(InsecureApiKeyError):
        validate_key_permissions(
            exchange_client=None,
            exchange_name="binance",
            raw_permissions=WITHDRAWAL_ENABLED_PERMISSIONS,
        )


def test_transfer_enabled_key_is_rejected():
    with pytest.raises(InsecureApiKeyError):
        validate_key_permissions(
            exchange_client=None,
            exchange_name="okx",
            raw_permissions=TRANSFER_ENABLED_PERMISSIONS,
        )


def test_list_shaped_permissions_with_withdrawals_rejected():
    with pytest.raises(InsecureApiKeyError):
        validate_key_permissions(
            exchange_client=None,
            exchange_name="bybit",
            raw_permissions=LIST_SHAPED_UNSAFE_PERMISSIONS,
        )


def test_key_missing_spot_or_read_is_rejected():
    with pytest.raises(InsecureApiKeyError):
        validate_key_permissions(
            exchange_client=None,
            exchange_name="kraken",
            raw_permissions={"spot": False, "read": True, "withdraw": False, "transfer": False},
        )


def test_evaluate_permissions_is_pure_and_does_not_raise():
    report = evaluate_permissions("binance", WITHDRAWAL_ENABLED_PERMISSIONS)
    assert report.withdrawal_enabled is True
    assert report.is_safe is False


class _FakeExchangeClient:
    id = "fakeexchange"

    def __init__(self, permissions):
        self._permissions = permissions

    def fetch_permissions(self):
        return self._permissions


def test_validate_key_permissions_fetches_from_exchange_client():
    client = _FakeExchangeClient(SAFE_PERMISSIONS)
    report = validate_key_permissions(client)
    assert report.is_safe


def test_validate_key_permissions_rejects_unverifiable_client():
    class _NoPermissionsClient:
        id = "mystery"

    with pytest.raises(InsecureApiKeyError):
        validate_key_permissions(_NoPermissionsClient())


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip():
    key = os.urandom(KEY_SIZE_BYTES)
    plaintext = "super-secret-api-key-123"

    ciphertext = encrypt_secret(plaintext, key)
    assert isinstance(ciphertext, bytes)
    assert ciphertext != plaintext.encode("utf-8")

    recovered = decrypt_secret(ciphertext, key)
    assert recovered == plaintext


def test_encrypt_uses_random_nonce_each_call():
    key = os.urandom(KEY_SIZE_BYTES)
    plaintext = "same-secret"

    ciphertext_a = encrypt_secret(plaintext, key)
    ciphertext_b = encrypt_secret(plaintext, key)

    # Different nonces (and thus different ciphertexts) for identical input.
    assert ciphertext_a != ciphertext_b
    assert decrypt_secret(ciphertext_a, key) == plaintext
    assert decrypt_secret(ciphertext_b, key) == plaintext


def test_decrypt_with_wrong_key_fails():
    key = os.urandom(KEY_SIZE_BYTES)
    wrong_key = os.urandom(KEY_SIZE_BYTES)
    ciphertext = encrypt_secret("secret", key)

    with pytest.raises(EnvelopeDecryptionError):
        decrypt_secret(ciphertext, wrong_key)


def test_decrypt_tampered_ciphertext_fails():
    key = os.urandom(KEY_SIZE_BYTES)
    ciphertext = bytearray(encrypt_secret("secret", key))
    ciphertext[-1] ^= 0xFF  # flip a bit in the GCM tag/ciphertext

    with pytest.raises(EnvelopeDecryptionError):
        decrypt_secret(bytes(ciphertext), key)


def test_encrypt_rejects_wrong_key_size():
    with pytest.raises(ValueError):
        encrypt_secret("secret", os.urandom(16))


# ---------------------------------------------------------------------------
# kms
# ---------------------------------------------------------------------------


def test_get_master_key_dev_fallback(monkeypatch):
    key_hex = os.urandom(KEY_SIZE_BYTES).hex()
    monkeypatch.setenv("TRADING_MODE", "testnet")
    monkeypatch.setenv("MASTER_KEY_OVERRIDE", key_hex)
    monkeypatch.delenv("KMS_SECRET_NAME", raising=False)

    key = get_master_key(secret_name="does-not-exist-in-this-test-env")
    assert isinstance(key, bytes)
    assert len(key) == KEY_SIZE_BYTES
    assert key == bytes.fromhex(key_hex)


def test_get_master_key_refuses_fallback_in_live_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("MASTER_KEY_OVERRIDE", os.urandom(KEY_SIZE_BYTES).hex())

    with pytest.raises(KmsUnavailableError):
        get_master_key(secret_name="does-not-exist-in-this-test-env")


def test_get_master_key_raises_without_fallback_configured(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "testnet")
    monkeypatch.delenv("MASTER_KEY_OVERRIDE", raising=False)
    monkeypatch.delenv("ENVELOPE_KEY_ID", raising=False)

    with pytest.raises(KmsUnavailableError):
        get_master_key(secret_name="does-not-exist-in-this-test-env")


# ---------------------------------------------------------------------------
# ephemeral
# ---------------------------------------------------------------------------


def test_zero_buffer_clears_all_bytes():
    buffer = bytearray(b"sensitive-data")
    zero_buffer(buffer)
    assert buffer == bytearray(len(buffer))


def test_ephemeral_secret_yields_correct_plaintext_and_zeroes_after():
    key = os.urandom(KEY_SIZE_BYTES)
    plaintext = "order-scoped-api-secret"
    ciphertext = encrypt_secret(plaintext, key)

    captured_ref = None
    with ephemeral_secret(ciphertext, key) as secret:
        captured_ref = secret
        assert secret.decode("utf-8") == plaintext

    # Same buffer object, now zeroed, after the `with` block exits.
    assert captured_ref is not None
    assert all(b == 0 for b in captured_ref)


def test_ephemeral_secret_zeroes_even_on_exception():
    key = os.urandom(KEY_SIZE_BYTES)
    ciphertext = encrypt_secret("secret-during-order", key)

    captured_ref = None
    with pytest.raises(RuntimeError):
        with ephemeral_secret(ciphertext, key) as secret:
            captured_ref = secret
            raise RuntimeError("order dispatch failed mid-flight")

    assert captured_ref is not None
    assert all(b == 0 for b in captured_ref)
