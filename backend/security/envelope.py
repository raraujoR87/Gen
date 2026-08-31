"""AES-256-GCM envelope encryption for exchange credentials.

Per docs/ARCHITECTURE.md section 2, item 3-4: exchange API key/secret pairs
are encrypted with AES-256-GCM before being persisted to
`exchange_accounts.encrypted_api_key` / `encrypted_api_secret`
(db/schema.sql). The encryption key itself ("envelope key") is the KMS
master key obtained via `backend.security.kms.get_master_key`.

Wire format for the returned ciphertext is:

    nonce (12 bytes) || ciphertext_with_gcm_tag

A fresh random 96-bit nonce is generated for every `encrypt_secret` call, as
required by GCM (nonce reuse under the same key breaks confidentiality and
authenticity). The nonce is not secret and is safe to store alongside the
ciphertext, which is why it's simply prepended.
"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE_BYTES = 12  # 96-bit nonce, the size recommended for AES-GCM.
KEY_SIZE_BYTES = 32  # AES-256.


class EnvelopeDecryptionError(Exception):
    """Raised when ciphertext fails authentication (tampered, wrong key, or
    truncated input) or is otherwise malformed."""


def _validate_key(key: bytes) -> None:
    if not isinstance(key, (bytes, bytearray)):
        raise TypeError("envelope key must be bytes")
    if len(key) != KEY_SIZE_BYTES:
        raise ValueError(
            f"envelope key must be exactly {KEY_SIZE_BYTES} bytes (AES-256), got {len(key)}"
        )


def encrypt_secret(plaintext: str, key: bytes) -> bytes:
    """Encrypt `plaintext` (e.g. an exchange API key or secret) with AES-256-GCM.

    Returns `nonce || ciphertext_with_tag` as raw bytes, safe to store
    directly in `exchange_accounts.encrypted_api_key` /
    `encrypted_api_secret` (base64/hex-encode at the storage layer if the
    column is text-typed, as it is in db/schema.sql).
    """
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be a str")
    _validate_key(key)

    nonce = os.urandom(NONCE_SIZE_BYTES)
    aesgcm = AESGCM(bytes(key))
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ciphertext


def decrypt_secret(ciphertext: bytes, key: bytes) -> str:
    """Decrypt bytes produced by `encrypt_secret` back into the plaintext string.

    Raises `EnvelopeDecryptionError` if the ciphertext is malformed or fails
    GCM tag authentication (tampering or wrong key).
    """
    if not isinstance(ciphertext, (bytes, bytearray)):
        raise TypeError("ciphertext must be bytes")
    _validate_key(key)

    if len(ciphertext) < NONCE_SIZE_BYTES:
        raise EnvelopeDecryptionError("ciphertext too short to contain a nonce")

    nonce, actual_ciphertext = bytes(ciphertext[:NONCE_SIZE_BYTES]), bytes(ciphertext[NONCE_SIZE_BYTES:])
    aesgcm = AESGCM(bytes(key))
    try:
        plaintext = aesgcm.decrypt(nonce, actual_ciphertext, associated_data=None)
    except InvalidTag as exc:
        raise EnvelopeDecryptionError(
            "failed to decrypt secret: authentication tag mismatch "
            "(wrong key or tampered/corrupted ciphertext)"
        ) from exc

    return plaintext.decode("utf-8")
