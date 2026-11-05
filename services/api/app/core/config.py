from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parent / "../../../../.env").resolve(), extra="ignore"
    )
    app_env: str = "development"
    auth_login_attempts: int = Field(default=10, ge=3, le=100)
    auth_peer_login_attempts: int = Field(default=500, ge=10, le=10000)
    auth_cookie_secure: bool = False
    auth_session_seconds: int = Field(default=28800, ge=300, le=604800)
    auth_allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @model_validator(mode="after")
    def production_cookie(self):
        if self.app_env == "production" and not self.auth_cookie_secure:
            raise ValueError("Production requires secure session cookies")
        if not self.auth_allowed_origins or "*" in self.auth_allowed_origins:
            raise ValueError("Explicit trusted browser origins required")
        for origin in self.auth_allowed_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or origin != f"{parsed.scheme}://{parsed.netloc}"
            ):
                raise ValueError("Origins must be exact HTTP(S) scheme/host/port values")
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production browser origins require HTTPS")
        return self

    report_allow_draft_export: bool = True

    model_provider: Literal["disabled", "openai_compatible"] = "disabled"
    model_base_url: str = "https://api.deepseek.com/v1"
    model_name: str = Field(default="deepseek-chat", min_length=1, max_length=160)
    model_api_key: SecretStr = SecretStr("")
    model_timeout_seconds: int = Field(default=40, ge=5, le=60)
    model_max_output_tokens: int = Field(default=4000, ge=256, le=12000)
    model_org_daily_token_limit: int = Field(default=200000, ge=1000, le=10000000)
    model_org_concurrency: int = Field(default=1, ge=1, le=8)
    model_input_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    model_output_price_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator(
        "model_input_price_per_million", "model_output_price_per_million", mode="before"
    )
    @classmethod
    def optional_price(cls, value):
        return None if value == "" else value

    @field_validator("model_base_url")
    @classmethod
    def secure_model_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Model endpoint requires HTTPS without credentials or query")
        return value.rstrip("/")

    database_url: SecretStr
    redis_url: SecretStr
    s3_endpoint_url: str
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr
    knowledge_max_file_bytes: int = Field(default=10485760, ge=1024, le=10485760)
    s3_bucket: str = "peclaw-documents"
    s3_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
