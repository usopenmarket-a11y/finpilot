---
name: crypto module test patterns
description: Coverage baseline, known unreachable lines, and mock patterns for app/crypto.py tests
type: project
---

`app/crypto.py` encapsulates AES-256-GCM encryption for bank credentials.

Public API:
- `encrypt(plaintext: str, key: SecretStr) -> str` — returns base64url token
- `decrypt(token: str, key: SecretStr) -> str` — returns plaintext
- `CryptoError` — raised for key/format errors; `ValueError` raised for GCM auth failures (wrong key / tampered ciphertext)

Test file: `app/tests/test_crypto.py` (19 tests, 96% coverage as of 2026-03-16)

Coverage ceiling: 96% is the practical maximum. Lines 108 and 162 are `except CryptoError: raise` re-raise guards inside the `encrypt` and `decrypt` try blocks. `_decode_key` runs *before* the try block, so `CryptoError` can never originate from inside `AESGCM.encrypt/decrypt` under normal conditions.

Key test patterns established:
- Valid test key: `SecretStr("00" * 32)` (64 hex chars, 32 zero bytes)
- Tamper test: decode token, flip last byte with `^= 0xFF`, re-encode — triggers `ValueError`
- Too-short token: `base64.urlsafe_b64encode(b"\x00" * 11)` — passes base64 decode, fails length check -> `CryptoError`
- Invalid base64: string with `!`, `@`, `#`, `$` characters — `urlsafe_b64decode` rejects -> `CryptoError`
- Unexpected exception branch: `patch("app.crypto.AESGCM", return_value=MagicMock(encrypt/decrypt=RuntimeError))` -> `CryptoError`

Dependency note: `cryptography` is NOT in `pyproject.toml` (as of 2026-03-16). It must be `uv pip install cryptography` into the venv before tests run. The Architect Agent should add it as a formal dependency.

**Why:** Encryption is the security backbone for stored bank credentials. These patterns ensure any regression in the GCM authentication or key-length validation is caught immediately.

**How to apply:** When adding new crypto primitives or credential storage, extend `test_crypto.py` following the tamper/short-token/bad-key triad already established.
