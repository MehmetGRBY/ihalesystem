import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TE_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/tender_enricher.db"
    input_path: Path = Path("data/inbox/tenders.json")
    output_path: Path = Path("data/outbox/results.json")
    request_interval_seconds: float = Field(default=2, ge=0.1)
    request_timeout_seconds: float = Field(default=15, gt=0, le=120)
    max_attempts: int = Field(default=3, ge=1, le=5)
    max_retry_delay_seconds: float = Field(default=30, ge=0, le=60)
    max_pages_per_tender: int = Field(default=12, ge=1, le=50)
    max_response_bytes: int = Field(default=2_000_000, ge=1024)
    browser_enabled: bool = False
    research_batch_size: int = Field(default=5, ge=1, le=20)
    research_interval_minutes: int = Field(default=60, ge=5, le=1440)
    research_daily_limit: int = Field(default=20, ge=1, le=200)
    research_refresh_days: int = Field(default=7, ge=1, le=90)
    backup_interval_hours: int = Field(default=24, ge=1, le=168)
    backup_keep: int = Field(default=7, ge=2, le=30)
    brave_api_key: SecretStr | None = None
    serper_api_key: SecretStr | None = None
    tavily_api_key: SecretStr | None = None
    searxng_url: HttpUrl | None = None
    searxng_engines: list[str] = Field(default_factory=list, max_length=20)
    search_providers: list[Literal["brave", "serper", "tavily", "searxng"]] = [
        "brave",
        "serper",
        "tavily",
        "searxng",
    ]
    official_award_hosts: list[str] = ["ekap.kik.gov.tr", "kik.gov.tr"]
    registry_hosts: list[str] = ["ticaretsicil.gov.tr", "www.ticaretsicil.gov.tr"]
    user_agent: str = "TenderEnricher/0.1 (public-source research; local MVP)"

    @field_validator("search_providers")
    @classmethod
    def unique_providers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Search providers must be unique")
        return value

    @field_validator("searxng_engines")
    @classmethod
    def valid_searxng_engines(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"[a-z0-9][a-z0-9_. -]{0,59}", name) for name in value
        ):
            raise ValueError("SearXNG engines must be unique, plain engine names")
        return value

    @field_validator("searxng_url", mode="before")
    @classmethod
    def empty_searxng_url(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("searxng_url")
    @classmethod
    def plain_searxng_url(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value:
            parsed = urlsplit(str(value))
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("SearXNG endpoint must not contain credentials, query or fragment")
        return value
