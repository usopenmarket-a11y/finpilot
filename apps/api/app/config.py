from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_reload: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "info"

    # ------------------------------------------------------------------
    # Supabase
    # ------------------------------------------------------------------
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Service role key has elevated privileges — never expose to clients.
    # SecretStr ensures the value is masked in all repr/log output.
    supabase_service_role_key: SecretStr = SecretStr("")

    # ------------------------------------------------------------------
    # Encryption
    # Bank credentials are AES-256-GCM encrypted before any persistence.
    # Must be a 32-byte value encoded as a hex string (64 hex characters).
    # SecretStr ensures the key material is never emitted to logs or repr.
    # ------------------------------------------------------------------
    encryption_key: SecretStr = SecretStr("")

    # ------------------------------------------------------------------
    # Claude API (Haiku for transaction categorisation)
    # ------------------------------------------------------------------
    # SecretStr ensures the API key is never emitted to logs or repr.
    claude_api_key: SecretStr = SecretStr("")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


settings = Settings()
