from pathlib import Path

from pydantic import Field, SecretStr
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
    brave_api_key: SecretStr | None = None
    official_award_hosts: list[str] = ["ekap.kik.gov.tr", "kik.gov.tr"]
    registry_hosts: list[str] = ["ticaretsicil.gov.tr", "www.ticaretsicil.gov.tr"]
    user_agent: str = "TenderEnricher/0.1 (public-source research; local MVP)"
