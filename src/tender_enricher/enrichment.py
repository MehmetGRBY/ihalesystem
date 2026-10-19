from collections.abc import Sequence
from dataclasses import dataclass, field

from tender_enricher.errors import CollectionError
from tender_enricher.matching import match_company
from tender_enricher.models import Collection, CompanyProfile, Evidence, Issue, NormalizedTender
from tender_enricher.ports import CompanyProvider


@dataclass
class Enrichment:
    collections: list[Collection] = field(default_factory=list)
    accepted_evidence: list[Evidence] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def provider_failure(provider: str, stage: str, error: Exception) -> Issue:
    return Issue(
        stage=stage,
        code=error.code if isinstance(error, CollectionError) else "provider_error",
        message=str(error)
        if isinstance(error, CollectionError)
        else "Provider failed; other providers continue. Local debugging can diagnose the failure.",
        provider=provider,
    )


def enrich_company(
    tender: NormalizedTender, winner: CompanyProfile, providers: Sequence[CompanyProvider]
) -> Enrichment:
    enriched = Enrichment()
    for provider in providers:
        try:
            collection = provider.collect(tender, winner)
        except Exception as error:
            enriched.issues.append(provider_failure(provider.name, "enrichment", error))
            continue
        enriched.collections.append(collection)
        enriched.issues.extend(collection.issues)
        for candidate in collection.candidates:
            decision = match_company(winner, candidate.company)
            if decision.accepted:
                enriched.accepted_evidence.extend(candidate.evidence)
            else:
                enriched.issues.append(
                    Issue(
                        stage="matching",
                        code="candidate_rejected",
                        message=", ".join(decision.reasons),
                        provider=provider.name,
                    )
                )
    return enriched
