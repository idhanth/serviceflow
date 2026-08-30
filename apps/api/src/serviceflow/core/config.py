"""Application settings, loaded once from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: PostgresDsn = Field(
        default=...,
        description="SQLAlchemy/psycopg DSN for the primary PostgreSQL database.",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    redis_url: RedisDsn = Field(default=...)

    # Auth. The dev provider is the default so the demo accounts in the seed data
    # work out of the box; setting clerk_secret_key switches to Clerk.
    auth_provider: Literal["dev", "clerk"] = "dev"
    jwt_secret: str = Field(default=..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 60
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    clerk_secret_key: str | None = None
    clerk_jwks_url: str | None = None

    # NoDecode: parse the comma-separated env value ourselves instead of as JSON.
    # ---- Object storage -------------------------------------------------
    # One S3 client serves both: locally s3_endpoint_url points at MinIO, in
    # production it is unset and boto3 talks to AWS. Nothing else changes.
    s3_bucket: str = "serviceflow-media"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None
    # What the browser should be given, when it differs from the endpoint the
    # API dials (containers, or a CDN in front of the bucket).
    s3_public_endpoint_url: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_upload_ttl_seconds: int = 300
    s3_download_ttl_seconds: int = 900

    # ---- Email --------------------------------------------------------
    # "smtp" is the development transport (MailPit); "resend" is the production
    # provider. Business logic never sees the difference.
    email_provider: Literal["smtp", "resend"] = "smtp"
    email_from: str = "ServiceFlow <hello@serviceflow.demo>"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    resend_api_key: str | None = None
    email_timeout_seconds: int = 10

    # ---- Celery -------------------------------------------------------
    # Deliberately *not* named CELERY_BROKER_URL: Celery reads that name from the
    # environment itself and would then override any app constructed with an
    # explicit broker, which silently reconfigures every app in the process.
    celery_broker_url: str | None = Field(default=None, alias="SERVICEFLOW_BROKER_URL")
    celery_result_backend: str | None = Field(default=None, alias="SERVICEFLOW_RESULT_BACKEND")
    email_max_retries: int = 5
    # How long before an appointment the reminder goes out.
    reminder_lead_hours: int = 24
    reminder_window_minutes: int = 90

    # ---- Realtime -----------------------------------------------------
    sse_keepalive_seconds: int = 20

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or str(self.redis_url)

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or str(self.redis_url)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
