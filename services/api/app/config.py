from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Monica Next CRM"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://crm:crm@localhost:5432/crm"
    wechat_database_url: str = ""
    instagram_database_url: str = ""
    linkedin_database_url: str = ""
    raw_root: Path = Path("./runtime/raw")
    media_root: Path = Path("./runtime/media")
    session_secret: str = "development-only-change-me"
    import_hmac_secret: str = "development-only-change-me"
    import_hmac_secrets: str = ""
    session_ttl_seconds: int = 60 * 60 * 24 * 14
    import_signature_ttl_seconds: int = 300
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.raw_root.mkdir(parents=True, exist_ok=True)
    settings.media_root.mkdir(parents=True, exist_ok=True)
    return settings
