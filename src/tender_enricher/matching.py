from difflib import SequenceMatcher

from tender_enricher.addressing import address_supports_identity
from tender_enricher.models import CompanyProfile, MatchDecision
from tender_enricher.normalization import company_key, domain, text_key


def match_company(anchor: CompanyProfile, candidate: CompanyProfile) -> MatchDecision:
    name_score = SequenceMatcher(
        None, company_key(anchor.company_name), company_key(candidate.company_name)
    ).ratio()
    if not anchor.company_name or not candidate.company_name or name_score < 0.9:
        return MatchDecision(accepted=False, score=name_score, reasons=["name_mismatch"])

    left_name, right_name = company_key(anchor.company_name), company_key(candidate.company_name)
    left_legal = set(left_name.split()) & {"as", "ltd"}
    right_legal = set(right_name.split()) & {"as", "ltd"}
    if left_legal and right_legal and left_legal != right_legal:
        return MatchDecision(accepted=False, score=0, reasons=["legal_form_conflict"])

    strong: list[str] = []
    for field in ("mersis_no", "tax_no"):
        left, right = getattr(anchor, field), getattr(candidate, field)
        if left and right:
            if left != right:
                return MatchDecision(accepted=False, score=0, reasons=[f"{field}_conflict"])
            strong.append(f"{field}_match")
    if anchor.trade_registry_no and candidate.trade_registry_no:
        if anchor.trade_registry_office and candidate.trade_registry_office:
            if text_key(anchor.trade_registry_office) == text_key(
                candidate.trade_registry_office
            ) and text_key(anchor.trade_registry_no) == text_key(candidate.trade_registry_no):
                strong.append("registry_identity_match")
            else:
                return MatchDecision(accepted=False, score=0, reasons=["registry_conflict"])
    if anchor.city and candidate.city and text_key(anchor.city) != text_key(candidate.city):
        return MatchDecision(accepted=False, score=0, reasons=["city_conflict"])
    if anchor.website and candidate.website:
        if domain(str(anchor.website)) != domain(str(candidate.website)):
            return MatchDecision(accepted=False, score=0, reasons=["domain_conflict"])
        strong.append("domain_match")
    if anchor.address and candidate.address:
        if address_supports_identity(anchor.address, candidate.address):
            strong.append("address_match")
    if not strong:
        reasons = ["name_only_insufficient"]
        if anchor.city and candidate.city:
            reasons.append("city_match_alone_insufficient")
        return MatchDecision(accepted=False, score=round(name_score * 0.5, 3), reasons=reasons)
    return MatchDecision(
        accepted=True,
        score=round(min(0.98, 0.7 * name_score + 0.25), 3),
        reasons=["name_match", *strong],
    )
