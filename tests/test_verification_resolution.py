from tender_enricher.collectors.parsing import profile_from_values
from tender_enricher.evidence import make_evidence, make_source, publisher_group
from tender_enricher.models import CompanyField, SourceType, WinnerClaim
from tender_enricher.verification import verify_fields
from tender_enricher.winner_resolution import resolve_winner


def claim(source, name="ABC İnşaat A.Ş.", identifier="2026/123456"):
    company, evidence = profile_from_values({"company_name": (name, "td")}, source)
    evidence.append(make_evidence(CompanyField.WINNER, name, source, "td", name))
    return WinnerClaim(tender_id=identifier, company=company, evidence=evidence)


def source(url="https://a.com/award", body="award", kind=SourceType.NEWS):
    return make_source(url, url, body, kind)


def test_one_news_source_requires_review():
    page = source()
    decision = resolve_winner("2026/123456", [claim(page)], [page])
    assert decision.company is None and decision.review_required


def test_two_independent_reports_confirm_winner():
    pages = [source(), source("https://b.com/award", "second independent text")]
    decision = resolve_winner("2026/123456", [claim(page) for page in pages], pages)
    assert decision.company.company_name == "ABC İnşaat A.Ş."
    assert decision.confidence == 0.85


def test_official_award_can_confirm_alone():
    page = source(kind=SourceType.OFFICIAL_AWARD)
    decision = resolve_winner("2026/123456", [claim(page)], [page])
    assert decision.company is not None and decision.confidence == 0.9


def test_conflicting_contractor_details_require_review():
    page = source(kind=SourceType.OFFICIAL_AWARD)
    observed = claim(page)
    for value in ("0012345678901234", "0012345678901235"):
        observed.evidence.append(make_evidence(CompanyField.MERSIS_NO, value, page, "p", value))
    decision = resolve_winner("2026/123456", [observed], [page])
    assert decision.company is None and decision.review_required
    assert decision.issues[0].code == "winner_identity_conflict"


def test_different_tender_is_not_evidence():
    page = source(kind=SourceType.OFFICIAL_AWARD)
    assert resolve_winner("2026/2", [claim(page)], [page]).company is None


def test_conflicting_winners_are_not_ranked_into_false_certainty():
    pages = [source(kind=SourceType.OFFICIAL_AWARD), source("https://b.com/a", "different")]
    decision = resolve_winner("2026/123456", [claim(pages[0]), claim(pages[1], "XYZ A.Ş.")], pages)
    assert decision.company is None and decision.review_required


def test_syndicated_copy_and_same_publisher_are_not_independent():
    for pages in (
        [source(), source("https://b.com/award", "award")],
        [source(), source("https://news.a.com/other", "other body")],
    ):
        decision = resolve_winner("2026/123456", [claim(page) for page in pages], pages)
        assert decision.company is None


def test_field_conflict_retains_alternatives_and_returns_null():
    pages = [source(), source("https://b.com/contact", "second")]
    evidence = [
        make_evidence(CompanyField.PHONE, number, page, "a", number)
        for page, number in zip(pages, ["+902120000000", "+902120000001"], strict=True)
    ]
    company, fields = verify_fields(evidence, pages)
    assert company.phone is None
    assert fields["phone"].status == "conflicting"
    assert len(fields["phone"].alternatives) == 2


def test_format_equivalent_phone_verified_from_two_sources():
    pages = [source(), source("https://b.com/contact", "second")]
    evidence = [
        make_evidence(CompanyField.PHONE, number, page, "a", number)
        for page, number in zip(pages, ["+902120000000", "0212 000 00 00"], strict=True)
    ]
    company, fields = verify_fields(evidence, pages)
    assert company.phone is not None
    assert fields["phone"].status == "verified"
    assert fields["mersis_no"].status == "missing"
    assert company.mersis_no is None


def test_copied_content_connects_publishers_even_with_other_pages():
    pages = [
        source("https://a.com/one", "original"),
        source("https://a.com/two", "syndicated"),
        source("https://b.com/two", "syndicated"),
    ]
    decision = resolve_winner("2026/123456", [claim(page) for page in pages], pages)
    assert decision.company is None and decision.review_required


def test_publisher_group_uses_public_suffix_and_handles_demo_domains():
    assert publisher_group("https://news.abc.com.tr/a") == "abc.com.tr"
    assert publisher_group("https://abc.demo.test/") == "abc.demo.test"
    assert publisher_group("https://registry.demo.test/") != publisher_group(
        "https://abc.demo.test/"
    )
