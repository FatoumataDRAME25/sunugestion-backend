from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable through a .env file."""

    n8n_webhook_url: str = "http://localhost:5678/webhook/extract-persons"
    n8n_timeout_seconds: int = 60
    paddleocr_lang: str = "fr"
    cors_origins: list[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
