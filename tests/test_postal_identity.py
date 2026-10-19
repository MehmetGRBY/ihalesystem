from itertools import permutations

import pytest

from tender_enricher.addressing import address_supports_identity, same_address
from tender_enricher.evidence import make_evidence, make_source
from tender_enricher.matching import match_company
from tender_enricher.models import CompanyField, CompanyProfile, SourceType
from tender_enricher.verification import verify_fields

FULL = "Merkez Mah. Çiçek Sk. Bina No: 1/1A Şişli / İstanbul Şişli/İstanbul"
SHORT = "Çiçek Sok. No:1/1A, 34300 Şişli/İstanbul"


@pytest.mark.parametrize(
    "left,right",
    [
        (FULL, SHORT),
        ("Çiçek Sokak No: 1/1A Şişli/İstanbul", SHORT),
        (
            "Merkez Mahallesi Çiçek Caddesi No: 5 Daire No: 2 Şişli/İstanbul",
            "Merkez Mah. Çiçek Cad. No:5 İç Kapı No:2 Şişli/İstanbul",
        ),
    ],
)
def test_explicit_postal_identity_matches_format_variants(left, right):
    assert same_address(left, right) and same_address(right, left)
    assert match_company(
        CompanyProfile(company_name="Atlas Tıbbi Cihazlar Ltd. Şti.", address=left),
        CompanyProfile(company_name="Atlas Tıbbi Cihazlar Limited Şirketi", address=right),
    ).accepted


@pytest.mark.parametrize(
    "other",
    [
        "Çiçek Sk. No: 1/1B Şişli/İstanbul",
        "Çiçek Sk. No: 1 Şişli/İstanbul",
        "Çiçek Sk. No: 1/1A Kadıköy/İstanbul",
        "Çiçek Sk. No: 1/1A Şişli/Ankara",
        "Gül Sk. No: 1/1A Şişli/İstanbul",
        "Çiçek Cad. No: 1/1A Şişli/İstanbul",
        "Diğer Mah. Çiçek Sk. No: 1/1A Şişli/İstanbul",
        "Çiçek Sk. No: 1/1A Daire No:2 Şişli/İstanbul",
        "Çiçek Sk. No: 1/1A İstanbul",
        "Çiçek Sk. No:1/1A",
        "Çiçek Sk. No:1/1A No:2 Şişli/İstanbul",
        "Şişli/İstanbul",
    ],
)
def test_incomplete_or_conflicting_address_does_not_match(other):
    assert not same_address(FULL, other)
    assert not same_address(other, FULL)


@pytest.mark.parametrize("qualifier", ["A Blok", "Kat:1", "Daire No:2"])
def test_published_block_floor_and_office_conflicts_are_retained(qualifier):
    left = f"Çiçek Sk. {qualifier} No:1/1A Şişli/İstanbul"
    right = left.replace("A Blok", "B Blok").replace("Kat:1", "Kat:2").replace("No:2", "No:3")
    assert not same_address(left, right)


def test_negative_floor_and_city_only_are_not_identity():
    assert not address_supports_identity("İstanbul", "İstanbul")
    assert not address_supports_identity("34300 Şişli İstanbul", "34300 Şişli İstanbul")
    assert not same_address(
        "Çiçek Sk. No:1 Kat:-1 Şişli/İstanbul", "Çiçek Sk. No:1 Kat:1 Şişli/İstanbul"
    )


def test_address_variants_keep_original_evidence_and_best_official_display():
    pages = [
        make_source(
            "https://award.example/", "https://award.example/", "award", SourceType.OFFICIAL_AWARD
        ),
        make_source(
            "https://atlas.example/",
            "https://atlas.example/",
            "contact",
            SourceType.COMPANY_WEBSITE,
        ),
    ]
    evidence = [
        make_evidence(CompanyField.ADDRESS, value, page, "address", value)
        for value, page in zip([FULL, SHORT], pages, strict=True)
    ]
    company, fields = verify_fields(evidence, pages)
    assert company.address == FULL
    assert fields["address"].status == "verified"
    assert len(fields["address"].evidence_ids) == 2
    assert [item.value for item in evidence] == [FULL, SHORT]


@pytest.mark.parametrize(
    "addresses",
    list(
        permutations(
            [
                "Birinci Mah. Çiçek Sk. No:1/1A Şişli/İstanbul",
                "Çiçek Sk. No:1/1A Şişli/İstanbul",
                "İkinci Mah. Çiçek Sk. No:1/1A Şişli/İstanbul",
            ]
        )
    ),
)
def test_missing_qualifier_cannot_bridge_conflicting_addresses(addresses):
    pages = [
        make_source(
            f"https://source{i}.example/", f"https://source{i}.example/", str(i), SourceType.NEWS
        )
        for i in range(3)
    ]
    evidence = [
        make_evidence(CompanyField.ADDRESS, value, page, "address", value)
        for value, page in zip(addresses, pages, strict=True)
    ]
    company, fields = verify_fields(evidence, pages)
    assert company.address is None
    assert fields["address"].status == "conflicting"
