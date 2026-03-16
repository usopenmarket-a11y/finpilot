"""
AES-256-GCM encryption utilities for FinPilot bank credential storage.

All key material is accepted as Pydantic SecretStr so it can never be
accidentally emitted to logs or repr output.  Plaintext and key bytes are
never assigned to module-level variables.

Authenticated encryption guarantee: AESGCM produces and verifies a 128-bit
authentication tag, so any bit-flip in the ciphertext or nonce causes decrypt
to raise an exception rather than return corrupt plaintext.
"""

import base64
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

# AES-256 requires exactly 32 bytes (256 bits).
_REQUIRED_KEY_BYTES: Final[int] = 32

# GCM standard nonce length.
_NONCE_BYTES: Final[int] = 12

# Associated data is left empty; change consistently if you add context binding.
_AAD: Final[None] = None


class CryptoError(Exception):
    """Raised for any crypto-level failure in this module.

    Callers should catch this exception rather than the lower-level
    ``cryptography`` exceptions so the public contract stays stable if the
    underlying library ever changes.
    """


def _decode_key(key: SecretStr) -> bytes:
    """Decode the hex-encoded AES key to raw bytes.

    Args:
        key: 64-character hex string wrapped in SecretStr.

    Returns:
        Exactly 32 raw key bytes.

    Raises:
        CryptoError: If the hex string is missing, malformed, or does not
            decode to exactly 32 bytes.
    """
    raw_hex: str = key.get_secret_value()
    try:
        key_bytes: bytes = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise CryptoError("encryption_key is not valid hexadecimal") from exc

    if len(key_bytes) != _REQUIRED_KEY_BYTES:
        raise CryptoError(
            f"encryption_key must decode to {_REQUIRED_KEY_BYTES} bytes "
            f"({_REQUIRED_KEY_BYTES * 2} hex characters); "
            f"got {len(key_bytes)} bytes"
        )

    return key_bytes


def encrypt(plaintext: str, key: SecretStr) -> str:
    """Encrypt *plaintext* with AES-256-GCM and return a compact token.

    The returned token is a URL-safe base64 string containing::

        nonce (12 bytes) | ciphertext | GCM tag (16 bytes)

    All three parts are concatenated before encoding so the caller stores a
    single opaque string.  A fresh random nonce is generated for every call,
    making repeated encryptions of the same plaintext produce distinct tokens.

    Args:
        plaintext: The credential string to protect.  Must be a valid UTF-8
            string; empty strings are accepted.
        key: 64-character hex-encoded AES-256 key wrapped in SecretStr.
            Obtained from ``settings.encryption_key``.

    Returns:
        URL-safe base64-encoded string (no padding characters omitted) that
        can be stored in the database and passed directly to :func:`decrypt`.

    Raises:
        CryptoError: If the key is invalid or any underlying crypto operation
            fails.
    """
    key_bytes: bytes = _decode_key(key)
    try:
        nonce: bytes = os.urandom(_NONCE_BYTES)
        aesgcm = AESGCM(key_bytes)
        # AESGCM.encrypt returns ciphertext + 16-byte tag concatenated.
        ciphertext_and_tag: bytes = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), _AAD)
        token: bytes = nonce + ciphertext_and_tag
        return base64.urlsafe_b64encode(token).decode("ascii")
    except CryptoError:
        raise
    except Exception as exc:
        raise CryptoError("Encryption failed") from exc
    finally:
        # Zero the local key copy before the reference is dropped.
        key_bytes = b"\x00" * len(key_bytes)  # noqa: F841 — intentional zeroing


def decrypt(token: str, key: SecretStr) -> str:
    """Decrypt a token produced by :func:`encrypt`.

    Args:
        token: URL-safe base64 string as returned by :func:`encrypt`.
        key: The same 64-character hex-encoded AES-256 key used during
            encryption, wrapped in SecretStr.

    Returns:
        The original plaintext string.

    Raises:
        ValueError: If the GCM authentication tag does not verify — i.e. the
            token was encrypted with a different key or has been tampered with.
            Callers MUST treat this as a hard failure; do not attempt to use
            the return value on exception.
        CryptoError: If the token is malformed (wrong base64, too short to
            contain a nonce) or the key is invalid.
    """
    key_bytes: bytes = _decode_key(key)
    try:
        raw: bytes = base64.urlsafe_b64decode(token)
    except Exception as exc:
        raise CryptoError("token is not valid base64url") from exc

    if len(raw) < _NONCE_BYTES:
        raise CryptoError(
            f"token is too short: expected at least {_NONCE_BYTES} bytes, got {len(raw)}"
        )

    nonce: bytes = raw[:_NONCE_BYTES]
    ciphertext_and_tag: bytes = raw[_NONCE_BYTES:]

    try:
        aesgcm = AESGCM(key_bytes)
        plaintext_bytes: bytes = aesgcm.decrypt(nonce, ciphertext_and_tag, _AAD)
        return plaintext_bytes.decode("utf-8")
    except InvalidTag as exc:
        # Re-raise as ValueError per the public contract so callers get a
        # meaningful, stable exception type regardless of the crypto library.
        raise ValueError(
            "GCM authentication tag verification failed: "
            "wrong key or ciphertext has been tampered with"
        ) from exc
    except CryptoError:
        raise
    except Exception as exc:
        raise CryptoError("Decryption failed") from exc
    finally:
        key_bytes = b"\x00" * len(key_bytes)  # noqa: F841 — intentional zeroing
