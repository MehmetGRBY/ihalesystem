from collections import defaultdict
from collections.abc import Sequence

from tender_enricher.models import (
    CompanyField,
    CompanyProfile,
    Evidence,
    FieldVerification,
    Source,
    SourceType,
)
from tender_enricher.normalization import normalize_value

RELIABILITY = {
    SourceType.OFFICIAL_AWARD: 0.95,
    SourceType.PUBLIC_REGISTRY: 0.95,
    SourceType.COMPANY_WEBSITE: 0.75,
    SourceType.NEWS: 0.6,
}


def independent_count(evidence: Sequence[Evidence], sources: dict[str, Source]) -> int:
    """A repeated publisher or a byte-identical syndicated page adds no corroboration."""
    parents: dict[str, str] = {}
    owners: dict[str, str] = {}

    def root(publisher: str) -> str:
        while parents[publisher] != publisher:
            publisher = parents[publisher]
        return publisher

    for item in evidence:
        source = sources[item.source_id]
        publisher = source.publisher_group
        parents.setdefault(publisher, publisher)
        owner = owners.setdefault(source.content_sha256, publisher)
        parents[root(publisher)] = root(owner)
    return len({root(publisher) for publisher in parents})


def verify_fields(
    evidence: Sequence[Evidence], sources: Sequence[Source]
) -> tuple[CompanyProfile, dict[str, FieldVerification]]:
    source_map = {source.id: source for source in sources}
    profile: dict[str, str | None] = {}
    verifications: dict[str, FieldVerification] = {}
    for field in CompanyField:
        if field == CompanyField.WINNER:
            continue
        claims = [item for item in evidence if item.field == field and item.source_id in source_map]
        groups: dict[str, list[Evidence]] = defaultdict(list)
        for claim in claims:
            groups[normalize_value(field, claim.value)].append(claim)
        if not claims:
            profile[field] = None
            verifications[field] = FieldVerification(status="missing", confidence=0)
        elif len(groups) > 1:
            profile[field] = None
            verifications[field] = FieldVerification(
                status="conflicting",
                confidence=0,
                evidence_ids=[item.id for item in claims],
                alternatives=list(dict.fromkeys(item.value for item in claims)),
            )
        else:
            best = max(claims, key=lambda item: RELIABILITY[source_map[item.source_id].source_type])
            count = independent_count(claims, source_map)
            score = RELIABILITY[source_map[best.source_id].source_type]
            if count >= 2:
                score = min(0.98, score + 0.15)
            profile[field] = best.value
            verifications[field] = FieldVerification(
                status="verified" if count >= 2 else "single_source",
                confidence=score,
                evidence_ids=[item.id for item in claims],
            )
    return CompanyProfile.model_validate(profile), verifications
