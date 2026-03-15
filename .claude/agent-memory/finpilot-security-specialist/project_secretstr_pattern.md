---
name: SecretStr Enforcement Pattern
description: Standard pattern for using Pydantic SecretStr for all secret fields in settings and API models
type: project
---

All secret-bearing fields in FinPilot MUST use `pydantic.SecretStr`, not `str`.

**Why:** Plain `str` fields are emitted verbatim in Pydantic repr, FastAPI validation error bodies, Python logging, and Sentry/error-tracker payloads. SecretStr masks the value as `'**********'` in all of these contexts. Callers must explicitly call `.get_secret_value()` to obtain the raw string, creating an intentional friction point.

**How to apply:** Any time you write or review a Pydantic model that contains a password, API key, encryption key, or token, verify the field type is `SecretStr`.

## Affected files as of M1

- `apps/api/app/config.py`: `supabase_service_role_key`, `encryption_key`, `claude_api_key`
- `apps/api/app/models/api.py`: `SignUpRequest.password`, `SignInRequest.password`

## Usage pattern

```python
from pydantic import SecretStr

# Reading in a route handler:
raw_key = settings.encryption_key.get_secret_value()
# Then zero it when done — do not store in a variable longer than needed.

# Reading a user password:
raw_password = request.password.get_secret_value()
```

## Do NOT do this

```python
# WRONG — exposes key in logs and repr
encryption_key: str = ""

# WRONG — logs the raw value
logger.info(f"Using key: {settings.encryption_key}")

# WRONG — passes SecretStr object to a function expecting str without unwrapping
supabase.auth.sign_in(password=request.password)  # must be .get_secret_value()
```
