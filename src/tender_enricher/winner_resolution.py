from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from tender_enricher.models import (
    CompanyField,
    CompanyProfile,
    Evidence,
    Issue,
    Source,
    SourceType,
    WinnerClaim,
)
from tender_enricher.normalization import company_key
from tender_enricher.verification import independent_count, verify_fields


@dataclass
class WinnerDecision:
    company: CompanyProfile | None = None
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0
    review_required: bool = False
    issues: list[Issue] = field(default_factory=list)


def resolve_winner(
    tender_id: str, claims: Sequence[WinnerClaim], sources: Sequence[Source]
) -> WinnerDecision:
    source_map = {source.id: source for source in sources}
    groups: dict[str, list[WinnerClaim]] = defaultdict(list)
    for claim in claims:
        if claim.tender_id != tender_id or not claim.company.company_name:
            continue
        proof = [
            item
            for item in claim.evidence
            if item.field == CompanyField.WINNER
            and item.source_id in source_map
            and company_key(item.value) == company_key(claim.company.company_name)
        ]
        if proof:
            groups[company_key(claim.company.company_name)].append(claim)
    if not groups:
        return WinnerDecision(
            issues=[
                Issue(
                    stage="winner_resolution",
                    code="winner_not_found",
                    message="No explicit winner evidence tied to the tender identifier was found.",
                )
            ]
        )
    if len(groups) > 1:
        return WinnerDecision(
            review_required=True,
            issues=[
                Issue(
                    stage="winner_resolution",
                    code="conflicting_winners",
                    message="Sources name different winners; manual review is required.",
                )
            ],
        )
    grouped = next(iter(groups.values()))
    evidence = list({item.id: item for claim in grouped for item in claim.evidence}.values())
    proof = [item for item in evidence if item.field == CompanyField.WINNER]
    official = any(
        source_map[item.source_id].source_type == SourceType.OFFICIAL_AWARD for item in proof
    )
    if not official and independent_count(proof, source_map) < 2:
        return WinnerDecision(
            review_required=True,
            issues=[
                Issue(
                    stage="winner_resolution",
                    code="winner_uncorroborated",
                    message="A single non-official publisher cannot establish the tender winner.",
                )
            ],
        )
    profile, verification = verify_fields(evidence, sources)
    if any(item.status == "conflicting" for item in verification.values()):
        return WinnerDecision(
            review_required=True,
            issues=[
                Issue(
                    stage="winner_resolution",
                    code="winner_identity_conflict",
                    message="Winner evidence contains conflicting identity or contact fields.",
                )
            ],
        )
    return WinnerDecision(company=profile, evidence=evidence, confidence=0.9 if official else 0.85)
