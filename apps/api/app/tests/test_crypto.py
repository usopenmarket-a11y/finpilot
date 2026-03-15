"""Unit tests for apps/api/app/crypto.py.

Coverage targets:
- encrypt / decrypt round-trip
- token format (valid base64url)
- nonce randomness (same plaintext -> different tokens)
- wrong key raises ValueError
- tampered ciphertext raises ValueError
- token too short raises CryptoError
- invalid base64 raises CryptoError
- key with wrong hex chars raises CryptoError
- key that decodes to wrong byte length raises CryptoError
- empty-string plaintext round-trip
- non-ASCII / unicode plaintext round-trip
- defensive except-CryptoError and except-Exception branches in encrypt/decrypt
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.crypto import CryptoError, decrypt, encrypt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 32 zero-bytes encoded as 64 hex characters — valid AES-256 test key.
_VALID_KEY_HEX: str = "00" * 32
_VALID_KEY: SecretStr = SecretStr(_VALID_KEY_HEX)

# A second distinct key used to test authentication failures.
_OTHER_KEY_HEX: str = "ff" * 32
_OTHER_KEY: SecretStr = SecretStr(_OTHER_KEY_HEX)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def test_round_trip_ascii() -> None:
    """encrypt followed by decrypt returns the original plaintext."""
    plaintext = "super-secret-password-123"
    token = encrypt(plaintext, _VALID_KEY)
    recovered = decrypt(token, _VALID_KEY)
    assert recovered == plaintext


def test_round_trip_empty_string() -> None:
    """Empty string encrypts and decrypts correctly (case 10)."""
    token = encrypt("", _VALID_KEY)
    assert decrypt(token, _VALID_KEY) == ""


def test_round_trip_unicode() -> None:
    """Non-ASCII / unicode string encrypts and decrypts correctly (case 11)."""
    plaintext = "مرحبا — Héllo — 日本語 — €€€"
    token = encrypt(plaintext, _VALID_KEY)
    assert decrypt(token, _VALID_KEY) == plaintext


# ---------------------------------------------------------------------------
# Token-format tests
# ---------------------------------------------------------------------------


def test_encrypt_returns_valid_base64url() -> None:
    """encrypt output is a valid URL-safe base64 string (case 2)."""
    token = encrypt("test_value", _VALID_KEY)
    # Must be a str
    assert isinstance(token, str)
    # Must contain only base64url-safe characters (no + or /)
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")
    assert all(ch in allowed for ch in token), f"Non-base64url char found in: {token!r}"
    # Must decode without error
    decoded = base64.urlsafe_b64decode(token + "==")  # pad for safety
    # Token must contain at least 12-byte nonce + 16-byte GCM tag = 28 bytes minimum.
    assert len(decoded) >= 28


def test_encrypt_nonce_is_random() -> None:
    """Two encrypt calls with identical plaintext produce different tokens (case 3)."""
    plaintext = "same_plaintext_value"
    token_a = encrypt(plaintext, _VALID_KEY)
    token_b = encrypt(plaintext, _VALID_KEY)
    assert token_a != token_b, "Repeated encryptions must use distinct nonces"


# ---------------------------------------------------------------------------
# Authentication-failure tests (ValueError)
# ---------------------------------------------------------------------------


def test_decrypt_wrong_key_raises_value_error() -> None:
    """decrypt with a different key raises ValueError (case 4)."""
    token = encrypt("credential_data", _VALID_KEY)
    with pytest.raises(ValueError):
        decrypt(token, _OTHER_KEY)


def test_decrypt_tampered_ciphertext_raises_value_error() -> None:
    """decrypt with a bit-flipped ciphertext raises ValueError (case 5)."""
    token = encrypt("important_secret", _VALID_KEY)
    raw = base64.urlsafe_b64decode(token + "==")

    # Flip the last byte (within the GCM tag region) to tamper the token.
    tampered = bytearray(raw)
    tampered[-1] ^= 0xFF
    tampered_token = base64.urlsafe_b64encode(bytes(tampered)).decode("ascii")

    with pytest.raises(ValueError):
        decrypt(tampered_token, _VALID_KEY)


# ---------------------------------------------------------------------------
# Malformed-token tests (CryptoError)
# ---------------------------------------------------------------------------


def test_decrypt_token_too_short_raises_crypto_error() -> None:
    """decrypt with a token shorter than the nonce length raises CryptoError (case 6).

    The nonce is 12 bytes.  We encode 11 bytes to produce a token that is
    valid base64 but too short to contain a full nonce.
    """
    short_raw = b"\x00" * 11  # 11 bytes < 12-byte nonce requirement
    short_token = base64.urlsafe_b64encode(short_raw).decode("ascii")
    with pytest.raises(CryptoError):
        decrypt(short_token, _VALID_KEY)


def test_decrypt_invalid_base64_raises_crypto_error() -> None:
    """decrypt with non-base64 input raises CryptoError (case 7).

    urlsafe_b64decode is lenient with padding but rejects characters outside
    the base64url alphabet such as '@'.
    """
    with pytest.raises(CryptoError):
        decrypt("not!valid@base64#token$", _VALID_KEY)


# ---------------------------------------------------------------------------
# Invalid-key tests (CryptoError)
# ---------------------------------------------------------------------------


def test_encrypt_non_hex_key_raises_crypto_error() -> None:
    """encrypt with a key containing non-hex characters raises CryptoError (case 8)."""
    bad_key = SecretStr("zz" * 32)  # 64 chars but not valid hex
    with pytest.raises(CryptoError):
        encrypt("payload", bad_key)


def test_decrypt_non_hex_key_raises_crypto_error() -> None:
    """decrypt with a key containing non-hex characters raises CryptoError (case 8)."""
    token = encrypt("payload", _VALID_KEY)
    bad_key = SecretStr("zz" * 32)
    with pytest.raises(CryptoError):
        decrypt(token, bad_key)


def test_encrypt_short_key_raises_crypto_error() -> None:
    """encrypt with a 31-byte (62 hex-char) key raises CryptoError (case 9)."""
    short_key = SecretStr("00" * 31)  # 62 hex chars -> 31 bytes, not 32
    with pytest.raises(CryptoError):
        encrypt("payload", short_key)


def test_decrypt_short_key_raises_crypto_error() -> None:
    """decrypt with a 31-byte (62 hex-char) key raises CryptoError (case 9)."""
    token = encrypt("payload", _VALID_KEY)
    short_key = SecretStr("00" * 31)
    with pytest.raises(CryptoError):
        decrypt(token, short_key)


def test_encrypt_long_key_raises_crypto_error() -> None:
    """encrypt with a 33-byte (66 hex-char) key raises CryptoError (case 9)."""
    long_key = SecretStr("00" * 33)  # 66 hex chars -> 33 bytes, not 32
    with pytest.raises(CryptoError):
        encrypt("payload", long_key)


def test_decrypt_long_key_raises_crypto_error() -> None:
    """decrypt with a 33-byte (66 hex-char) key raises CryptoError (case 9)."""
    token = encrypt("payload", _VALID_KEY)
    long_key = SecretStr("00" * 33)
    with pytest.raises(CryptoError):
        decrypt(token, long_key)


# ---------------------------------------------------------------------------
# Edge-case / boundary tests
# ---------------------------------------------------------------------------


def test_token_structure_nonce_prefix() -> None:
    """Verify the token's leading 12 bytes differ across calls (nonce is random)."""
    token_a = encrypt("x", _VALID_KEY)
    token_b = encrypt("x", _VALID_KEY)
    raw_a = base64.urlsafe_b64decode(token_a + "==")
    raw_b = base64.urlsafe_b64decode(token_b + "==")
    nonce_a = raw_a[:12]
    nonce_b = raw_b[:12]
    assert nonce_a != nonce_b, "Nonces must be independently random"


def test_decrypt_exact_nonce_boundary_raises_crypto_error() -> None:
    """A token of exactly 12 bytes (nonce only, zero ciphertext+tag bytes) fails GCM
    verification and must raise — either CryptoError or ValueError is acceptable
    since the token is structurally just long enough to pass the length check but
    the GCM tag is absent."""
    boundary_raw = b"\x00" * 12  # exactly _NONCE_BYTES, no ciphertext or tag
    boundary_token = base64.urlsafe_b64encode(boundary_raw).decode("ascii")
    with pytest.raises((CryptoError, ValueError)):
        decrypt(boundary_token, _VALID_KEY)


# ---------------------------------------------------------------------------
# Defensive-branch tests (lines only reachable via mocked AESGCM failure)
# ---------------------------------------------------------------------------


def test_encrypt_unexpected_exception_wrapped_as_crypto_error() -> None:
    """If AESGCM.encrypt raises an unexpected Exception (not CryptoError),
    encrypt must wrap it in CryptoError (covers the bare except-Exception branch).
    """
    mock_aesgcm = MagicMock()
    mock_aesgcm.encrypt.side_effect = RuntimeError("unexpected low-level failure")
    with patch("app.crypto.AESGCM", return_value=mock_aesgcm):
        with pytest.raises(CryptoError, match="Encryption failed"):
            encrypt("payload", _VALID_KEY)


def test_decrypt_unexpected_exception_wrapped_as_crypto_error() -> None:
    """If AESGCM.decrypt raises an unexpected Exception (not InvalidTag or CryptoError),
    decrypt must wrap it in CryptoError (covers the bare except-Exception branch).
    """
    token = encrypt("payload", _VALID_KEY)
    mock_aesgcm = MagicMock()
    mock_aesgcm.decrypt.side_effect = RuntimeError("unexpected low-level failure")
    with patch("app.crypto.AESGCM", return_value=mock_aesgcm):
        with pytest.raises(CryptoError, match="Decryption failed"):
            decrypt(token, _VALID_KEY)
