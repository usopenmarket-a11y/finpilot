---
name: AES-256-GCM crypto module
description: Implementation decisions and security contract for apps/api/app/crypto.py
type: project
---

AES-256-GCM encryption module lives at `apps/api/app/crypto.py`. Implemented using `cryptography.hazmat.primitives.ciphers.aead.AESGCM` (not pycryptodome).

**Token wire format:** `base64url( nonce[12] | ciphertext | gcm_tag[16] )` — single opaque string, no separators.

**Key contract:** `encryption_key` in Settings is a 64-char hex string; decoded to 32 bytes inside each function call, never at module level. Key bytes are zeroed in `finally` blocks after use.

**Exception contract:**
- `CryptoError` (subclass of `Exception`) — malformed key, bad base64, token too short, or unexpected crypto failure.
- `ValueError` — GCM tag verification failed (wrong key or tampered ciphertext). Callers must treat this as a hard stop; never attempt to use partial output.

**AAD:** Currently `None`. If context binding is added in future (e.g., binding ciphertext to user_id), it must be added consistently in both encrypt and decrypt or all existing tokens become unreadable.

**Why:** Bank credentials must never be stored in plaintext (security rule #1). AES-256-GCM provides authenticated encryption so tampering is detected on decrypt.

**How to apply:** Any code that persists bank credentials must call `encrypt` before write and `decrypt` after read. The plaintext must be zeroed by the caller (scraper scope) after use — the crypto module only zeroes the key, not the returned plaintext.
