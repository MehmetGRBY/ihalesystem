"""Shared, versioned contracts. No scraping or persistence dependencies."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

Score = Annotated[float, Field(ge=0, le=1)]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TenderInput(Contract):
    tender_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authority: str = Field(min_length=1)
    location: str | None = None
    award_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    company_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)
    registry_urls: list[HttpUrl] = Field(default_factory=list, max_length=20)


class NormalizedTender(TenderInput):
    pass


class CompanyProfile(Contract):
    company_name: str | None = None
    phone: str | None = None
    email: str | None = None
    website: HttpUrl | None = None
    address: str | None = None
    city: str | None = None
    district: str | None = None
    mersis_no: str | None = Field(default=None, pattern=r"^\d{16}$")
    trade_registry_no: str | None = None
    trade_registry_office: str | None = None
    tax_no: str | None = Field(default=None, pattern=r"^\d{10}$")
    tax_office: str | None = None


class CompanyField(StrEnum):
    COMPANY_NAME = "company_name"
    PHONE = "phone"
    EMAIL = "email"
    WEBSITE = "website"
    ADDRESS = "address"
    CITY = "city"
    DISTRICT = "district"
    MERSIS_NO = "mersis_no"
    TRADE_REGISTRY_NO = "trade_registry_no"
    TRADE_REGISTRY_OFFICE = "trade_registry_office"
    TAX_NO = "tax_no"
    TAX_OFFICE = "tax_office"
    WINNER = "winner.company_name"


class SourceType(StrEnum):
    OFFICIAL_AWARD = "official_award"
    COMPANY_WEBSITE = "company_website"
    PUBLIC_REGISTRY = "public_registry"
    NEWS = "news"


class Source(Contract):
    id: str
    url: HttpUrl
    final_url: HttpUrl
    source_type: SourceType
    publisher_group: str
    retrieved_at: AwareDatetime
    content_sha256: str
    is_demo: bool = False


class Evidence(Contract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    field: CompanyField
    value: str = Field(min_length=1)
    source_id: str
    excerpt: str = Field(max_length=600)
    locator: str


class WinnerClaim(Contract):
    tender_id: str
    company: CompanyProfile
    evidence: list[Evidence]


class CompanyCandidate(Contract):
    company: CompanyProfile
    evidence: list[Evidence]


class Issue(Contract):
    stage: str
    code: str
    message: str
    provider: str | None = None


class Collection(Contract):
    sources: list[Source] = Field(default_factory=list)
    winner_claims: list[WinnerClaim] = Field(default_factory=list)
    candidates: list[CompanyCandidate] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sources(self) -> "Collection":
        source_ids = {source.id for source in self.sources}
        observations: list[WinnerClaim | CompanyCandidate] = [*self.winner_claims, *self.candidates]
        if any(
            item.source_id not in source_ids
            for observation in observations
            for item in observation.evidence
        ):
            raise ValueError("Provider evidence must reference a collected source")
        return self


class MatchDecision(Contract):
    accepted: bool
    score: Score
    reasons: list[str]


class FieldVerification(Contract):
    status: Literal["missing", "single_source", "verified", "conflicting"]
    confidence: Score
    evidence_ids: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)


class EnrichmentResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    tender_id: str
    status: Literal["resolved", "partial", "review_required", "unresolved", "failed"]
    winner: CompanyProfile | None = None
    sources: list[Source] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    field_verification: dict[str, FieldVerification] = Field(default_factory=dict)
    winner_confidence: Score = 0
    confidence: Score = 0
    completeness: Score = 0
    issues: list[Issue] = Field(default_factory=list)
    processed_at: AwareDatetime = Field(default_factory=utc_now)
    is_demo: bool = False

    @model_validator(mode="after")
    def validate_references(self) -> "EnrichmentResult":
        source_ids = {source.id for source in self.sources}
        evidence_ids = {item.id for item in self.evidence}
        if len(source_ids) != len(self.sources) or len(evidence_ids) != len(self.evidence):
            raise ValueError("Source and evidence ids must be unique")
        if any(item.source_id not in source_ids for item in self.evidence):
            raise ValueError("Evidence references an unknown source")
        if any(source.is_demo != self.is_demo for source in self.sources):
            raise ValueError("Demo sources and live results cannot be mixed")
        for verification in self.field_verification.values():
            if not set(verification.evidence_ids).issubset(evidence_ids):
                raise ValueError("Field verification references unknown evidence")
        if self.winner:
            for field, value in self.winner.model_dump(mode="json").items():
                if value is not None and not any(
                    item.field == field and item.value == str(value) for item in self.evidence
                ):
                    raise ValueError(f"Non-null field {field} requires evidence")
        if self.status in {"resolved", "partial"}:
            proof = self.field_verification.get(CompanyField.WINNER)
            if (
                not self.winner
                or not self.winner.company_name
                or not proof
                or not proof.evidence_ids
            ):
                raise ValueError("Accepted winner requires an identity and winner proof")
            if not any(
                item.id in proof.evidence_ids and item.field == CompanyField.WINNER
                for item in self.evidence
            ):
                raise ValueError("Winner proof must reference winner evidence")
        return self
