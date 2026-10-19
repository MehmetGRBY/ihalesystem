import pytest

from tender_enricher.matching import match_company
from tender_enricher.models import CompanyProfile


def profile(**fields):
    return CompanyProfile.model_validate({"company_name": "ABC İnşaat A.Ş.", **fields})


@pytest.mark.parametrize("fields", [{}, {"city": "İstanbul"}])
def test_name_or_name_plus_city_cannot_auto_merge(fields):
    assert not match_company(profile(**fields), profile(**fields)).accepted


def test_canonical_domain_supports_matching():
    decision = match_company(
        profile(website="https://www.abc.com.tr/"), profile(website="https://abc.com.tr/iletisim")
    )
    assert decision.accepted
    assert "domain_match" in decision.reasons


@pytest.mark.parametrize(
    "field,left,right",
    [
        ("mersis_no", "0012345678901234", "0012345678901235"),
        ("tax_no", "0012345678", "0012345679"),
        ("city", "İstanbul", "Ankara"),
        ("website", "https://abc.com.tr", "https://other.com.tr"),
    ],
)
def test_identity_conflict_blocks_even_with_same_name(field, left, right):
    decision = match_company(profile(**{field: left}), profile(**{field: right}))
    assert not decision.accepted
    assert decision.score == 0


def test_address_and_official_identifier_are_supporting_signals():
    assert match_company(
        profile(address="Demo Cad. No:1"), profile(address="Demo Cad No 1")
    ).accepted
    assert match_company(
        profile(mersis_no="0012345678901234"), profile(mersis_no="0012345678901234")
    ).accepted


def test_registry_number_requires_registry_office():
    assert not match_company(
        profile(trade_registry_no="123"), profile(trade_registry_no="123")
    ).accepted
    assert match_company(
        profile(trade_registry_no="123", trade_registry_office="İstanbul"),
        profile(trade_registry_no="123", trade_registry_office="İstanbul"),
    ).accepted


def test_legal_form_conflict_blocks_similar_name():
    assert not match_company(
        profile(website="https://abc.com.tr"),
        profile(company_name="ABC İnşaat Ltd. Şti.", website="https://abc.com.tr"),
    ).accepted
