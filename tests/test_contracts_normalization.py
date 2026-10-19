import json

import pytest
from pydantic import ValidationError

from tender_enricher.models import CompanyProfile, EnrichmentResult, Source, TenderInput
from tender_enricher.normalization import company_key, normalize_tender, tender_id, text_key


def test_turkish_normalization_and_legal_form():
    assert text_key("İNŞAAT IŞIK") == "insaat isik"
    assert company_key("ABC İnşaat Sanayi ve Ticaret A.Ş.") == company_key(
        "ABC İnşaat San. ve Tic. Anonim Şirketi"
    )
    assert company_key("ABC Ltd. Şti.") != company_key("ABC A.Ş.")


def test_normalizer_preserves_project_location(tender):
    record = tender.model_copy(update={"tender_id": "2026 / 00123456", "title": "Hastane  Yapımı"})
    normalized = normalize_tender(record)
    assert normalized.tender_id == "2026/123456"
    assert normalized.title == "Hastane Yapımı"
    assert normalized.location == "Van"


@pytest.mark.parametrize("value", ["abc", "2026/0", "2026/123/4", "123456"])
def test_invalid_identifier_rejected(value):
    with pytest.raises(ValueError):
        tender_id(value)


def test_identifiers_remain_strings_with_leading_zero():
    profile = CompanyProfile(mersis_no="0012345678901234", tax_no="0012345678")
    assert profile.mersis_no.startswith("00")
    with pytest.raises(ValidationError):
        CompanyProfile(tax_no="12345678901")


def test_output_cannot_contain_unproven_contact():
    with pytest.raises(ValidationError, match="requires evidence"):
        EnrichmentResult(
            tender_id="2026/1", status="partial", winner=CompanyProfile(phone="+902121234567")
        )


def test_source_requires_timezone():
    with pytest.raises(ValidationError):
        Source.model_validate(
            {
                "id": "s",
                "url": "https://a.com",
                "final_url": "https://a.com",
                "source_type": "news",
                "publisher_group": "a.com",
                "retrieved_at": "2026-01-01T10:00:00",
                "content_sha256": "abc",
            }
        )


def test_input_rejects_faked_trust_flag(tender):
    with pytest.raises(ValidationError):
        TenderInput.model_validate({**tender.model_dump(), "is_official": True})


def test_accepted_status_requires_winner_proof():
    with pytest.raises(ValidationError, match="winner proof"):
        EnrichmentResult(tender_id="2026/1", status="resolved")


def test_schema_is_versioned_and_preserves_nulls():
    result = EnrichmentResult(tender_id="2026/1", status="unresolved")
    assert json.loads(result.model_dump_json())["winner"] is None
    assert result.schema_version == "1.0"
