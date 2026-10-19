import logging
from collections.abc import Sequence

from tender_enricher.enrichment import enrich_company, provider_failure
from tender_enricher.models import (
    Collection,
    CompanyCandidate,
    CompanyField,
    EnrichmentResult,
    Evidence,
    FieldVerification,
    Issue,
    NormalizedTender,
    Source,
    TenderInput,
    WinnerClaim,
)
from tender_enricher.normalization import normalize_tender
from tender_enricher.ports import CompanyProvider, ResultRepository, WinnerProvider
from tender_enricher.verification import verify_fields
from tender_enricher.winner_resolution import resolve_winner

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        winner_providers: Sequence[WinnerProvider],
        company_providers: Sequence[CompanyProvider],
        repository: ResultRepository,
        *,
        is_demo: bool = False,
    ) -> None:
        self.winner_providers = winner_providers
        self.company_providers = company_providers
        self.repository = repository
        self.is_demo = is_demo

    def process(self, record: TenderInput) -> EnrichmentResult:
        try:
            tender = normalize_tender(record)
        except ValueError:
            return EnrichmentResult(
                tender_id=record.tender_id,
                status="failed",
                issues=[
                    Issue(
                        stage="normalization",
                        code="invalid_tender_id",
                        message="Tender identifier must use YYYY/number format.",
                    )
                ],
                is_demo=self.is_demo,
            )
        result = self._resolve(tender)
        try:
            self.repository.save(tender, result)
        except Exception:
            result = result.model_copy(
                update={
                    "status": "failed",
                    "issues": [
                        *result.issues,
                        Issue(
                            stage="database",
                            code="persistence_failed",
                            message="Database transaction failed; data remains in the output.",
                        ),
                    ],
                }
            )
        logger.info(
            "tender=%s status=%s confidence=%.3f",
            result.tender_id,
            result.status,
            result.confidence,
        )
        return result

    def _resolve(self, tender: NormalizedTender) -> EnrichmentResult:
        collections: list[Collection] = []
        issues: list[Issue] = []
        for provider in self.winner_providers:
            try:
                collection = provider.collect(tender)
                collections.append(collection)
                issues.extend(collection.issues)
            except Exception as error:
                issues.append(provider_failure(provider.name, "winner_collection", error))
        sources, all_evidence = _observations(collections)
        claims = [claim for collection in collections for claim in collection.winner_claims]
        decision = resolve_winner(tender.tender_id, claims, sources)
        issues.extend(decision.issues)
        if any(issue.code == "award_ambiguous" for issue in issues):
            decision.company = None
            decision.review_required = True
        if decision.company is None:
            return EnrichmentResult(
                tender_id=tender.tender_id,
                status="review_required" if decision.review_required else "unresolved",
                sources=sources,
                evidence=all_evidence,
                issues=issues,
                is_demo=self.is_demo,
            )
        enriched = enrich_company(tender, decision.company, self.company_providers)
        issues.extend(enriched.issues)
        collections.extend(enriched.collections)
        sources, all_evidence = _observations(collections)
        accepted = [*decision.evidence, *enriched.accepted_evidence]
        profile, fields = verify_fields(accepted, sources)
        conflicts = [key for key, item in fields.items() if item.status == "conflicting"]
        if conflicts:
            issues.append(
                Issue(
                    stage="verification",
                    code="field_conflict",
                    message="Conflicting fields were left null: " + ", ".join(conflicts),
                )
            )
        fields[CompanyField.WINNER] = FieldVerification(
            status="verified",
            confidence=decision.confidence,
            evidence_ids=[
                item.id for item in decision.evidence if item.field == CompanyField.WINNER
            ],
        )
        values = profile.model_dump(mode="json")
        completeness = sum(value is not None for value in values.values()) / len(values)
        present_scores = [
            fields[key].confidence for key, value in values.items() if value is not None
        ]
        confidence = (
            min(decision.confidence, sum(present_scores) / len(present_scores))
            if present_scores
            else 0
        )
        essential = ("company_name", "phone", "email", "website", "address", "city")
        status = (
            "resolved"
            if all(values[key] and fields[key].status == "verified" for key in essential)
            else "partial"
        )
        if conflicts:
            status = "review_required"
        return EnrichmentResult.model_validate(
            {
                "tender_id": tender.tender_id,
                "status": status,
                "winner": profile,
                "sources": sources,
                "evidence": all_evidence,
                "field_verification": fields,
                "winner_confidence": decision.confidence,
                "confidence": round(confidence, 3),
                "completeness": round(completeness, 3),
                "issues": issues,
                "is_demo": self.is_demo,
            }
        )


def _observations(collections: Sequence[Collection]) -> tuple[list[Source], list[Evidence]]:
    sources = {source.id: source for collection in collections for source in collection.sources}
    evidence: dict[str, Evidence] = {}
    for collection in collections:
        observations: list[WinnerClaim | CompanyCandidate] = [
            *collection.winner_claims,
            *collection.candidates,
        ]
        for observation in observations:
            evidence.update({item.id: item for item in observation.evidence})
    return list(sources.values()), list(evidence.values())
