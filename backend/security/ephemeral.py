"""Ephemeral in-memory secret handling with best-effort zeroing.

Per docs/ARCHITECTURE.md section 2, item 4: the Modal worker decrypts
credentials only within the scope of a single order's execution, and must
zero the buffer afterwards. This module provides that scope as a context
manager so callers never have to remember to clean up manually.

Caveat (documented, not hidden): CPython strings are immutable and may be
interned/copied by the interpreter, so a `str` cannot be reliably zeroed in
place. `ephemeral_secret` therefore decrypts into a `bytearray` (mutable,
zeroable) and yields that; callers needing a `str` (e.g. to hand to ccxt)
should keep its lifetime as short as possible and understand that the
`str` itself is not zeroed by this utility — only the `bytearray` is. This
is the best guarantee achievable in pure Python without relying on
non-standard mlock/secure-malloc primitives.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from backend.security.envelope import decrypt_secret


def zero_buffer(buffer: bytearray) -> None:
    """Overwrite every byte of `buffer` with 0 in place."""
    for i in range(len(buffer)):
        buffer[i] = 0


@contextmanager
def ephemeral_secret(ciphertext: bytes, key: bytes) -> Iterator[bytearray]:
    """Decrypt `ciphertext` for the duration of the `with` block only.

    Yields a mutable `bytearray` containing the UTF-8 plaintext. When the
    block exits (normally or via exception) the buffer is overwritten with
    zeros before the context manager returns, so the decrypted secret does
    not linger in memory beyond the scope of its use (e.g. a single order
    dispatch).

    Example:
        with ephemeral_secret(encrypted_api_secret, master_key) as secret:
            client = ccxt.binance({"secret": secret.decode("utf-8")})
            ... dispatch order ...
        # `secret` is now all zero bytes here.
    """
    plaintext_str = decrypt_secret(ciphertext, key)
    buffer = bytearray(plaintext_str.encode("utf-8"))
    try:
        yield buffer
    finally:
        zero_buffer(buffer)
