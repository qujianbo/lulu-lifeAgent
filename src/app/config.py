from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "life-agent"
    app_env: Literal["local", "test", "prod"] = "local"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    scheduler_poll_seconds: int = 30

    public_base_url: HttpUrl | None = None

    database_url: str | None = None
    redis_url: str | None = None

    llm_provider: str = "deepseek"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str | None = None
    llm_timeout_seconds: int = 30

    wechat_app_id: str | None = None
    wechat_app_secret: str | None = None
    wechat_token: str | None = None
    wechat_encoding_aes_key: str | None = None

    admin_token: str | None = Field(default=None, repr=False)
    briefing_rss_urls: str | None = None
    briefing_rss_timeout_seconds: int = 8

    web_search_provider: Literal["tavily", "google"] = "tavily"
    web_search_timeout_seconds: int = 8
    tavily_api_key: str | None = None
    google_search_api_key: str | None = None
    google_search_cx: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
