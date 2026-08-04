from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, field_validator
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

    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_from_email: str | None = None
    smtp_from_name: str = "生活管家 Agent"
    smtp_use_ssl: bool = True
    smtp_use_starttls: bool = False
    email_enabled: bool = False
    email_default_daily_briefing_time: str = "09:00"
    email_max_retries: int = 3

    memory_provider: Literal["mem0"] = "mem0"
    memory_enabled: bool = False
    memory_write_enabled: bool = False
    memory_search_top_k: int = 5
    memory_timeout_seconds: int = 8

    mem0_llm_provider: str = "deepseek"
    mem0_llm_model: str = "deepseek-chat"
    mem0_llm_base_url: str = "https://api.deepseek.com"
    mem0_llm_api_key: str | None = Field(default=None, repr=False)
    mem0_embedder_provider: str | None = None
    mem0_embedder_model: str | None = None
    mem0_embedder_api_key: str | None = Field(default=None, repr=False)
    mem0_embedding_dims: int | None = None

    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "life_agent_memories"
    qdrant_distance: str = "Cosine"

    @field_validator("public_base_url", "mem0_embedding_dims", mode="before")
    @classmethod
    def empty_optional_config_to_none(cls, value: str | None) -> str | None:
        if value == "":
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
