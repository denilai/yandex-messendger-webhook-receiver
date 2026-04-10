from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    basic_auth_username: str = Field(alias="BASIC_AUTH_USERNAME")
    basic_auth_password: str = Field(alias="BASIC_AUTH_PASSWORD")
    basic_auth_realm: str = Field(default="alertmanager-webhook", alias="BASIC_AUTH_REALM")

    yandex_oauth_token: str = Field(alias="YANDEX_OAUTH_TOKEN")
    yandex_api_base: str = Field(
        default="https://botapi.messenger.yandex.net",
        alias="YANDEX_API_BASE",
    )
    yandex_http_timeout_seconds: float = Field(
        default=5.0,
        alias="YANDEX_HTTP_TIMEOUT_SECONDS",
    )
    fail_on_yandex_4xx: bool = Field(default=False, alias="FAIL_ON_YANDEX_4XX")

    message_template: str | None = Field(default=None, alias="MESSAGE_TEMPLATE")
    message_template_file: str | None = Field(default=None, alias="MESSAGE_TEMPLATE_FILE")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="console", alias="LOG_FORMAT")
    log_config: str | None = Field(default=None, alias="LOG_CONFIG")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]

