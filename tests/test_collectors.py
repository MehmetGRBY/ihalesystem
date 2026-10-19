import json

import pytest
from conftest import ROOT
from pydantic import HttpUrl

from tender_enricher.collectors.company_website.website import (
    CompanyWebsiteCollector,
    parse_companies,
)
from tender_enricher.collectors.demo import DemoFetcher
from tender_enricher.collectors.ekap.award import PublicAwardCollector
from tender_enricher.collectors.web import Document
from tender_enricher.evidence import make_source
from tender_enricher.models import CompanyProfile, SourceType
from tender_enricher.normalization import normalize_tender


class Pages:
    def __init__(self, body, final_url=None):
        self.body, self.final_url = body, final_url

    def fetch(self, url):
        return Document(url, self.final_url or url, self.body)

    def begin_tender(self):
        pass


def collect_award(body, tender, settings, final_url=None):
    record = tender.model_copy(update={"award_urls": [HttpUrl("https://awards.demo.test/result")]})
    return PublicAwardCollector(Pages(body, final_url), settings).collect(normalize_tender(record))


def test_award_does_not_use_project_city_as_company_city(tender, settings):
    body = "<p>İKN: 2026/123456</p><p>Yüklenici: ABC A.Ş.</p><p>İl: Van</p>"
    collection = collect_award(body, tender, settings)
    assert collection.winner_claims[0].company.city is None


@pytest.mark.parametrize(
    "body",
    [
        "<p>İKN: 2026/123457</p><p>Yüklenici: ABC A.Ş.</p>",
        "<p>İKN: 2026/123456</p><p>İKN: 2026/123457</p><p>Yüklenici: ABC A.Ş.</p>",
        "<p>2026/123456 ABC A.Ş. projesi</p>",
    ],
)
def test_unrelated_or_unsupported_award_page_returns_no_claim(body, tender, settings):
    assert not collect_award(body, tender, settings).winner_claims


@pytest.mark.parametrize(
    "extra", ["İhale iptal edildi", "ABC ve XYZ İş Ortaklığı", "ABC A.Ş. & XYZ A.Ş."]
)
def test_cancellation_or_joint_venture_requires_review(extra, tender, settings):
    result = collect_award(f"<p>İKN: 2026/123456</p><p>Yüklenici: {extra}</p>", tender, settings)
    assert not result.winner_claims
    assert result.issues[0].code == "award_ambiguous"


def test_official_redirect_to_news_loses_official_trust(tender, settings):
    result = collect_award(
        "<p>İKN: 2026/123456</p><p>Yüklenici: ABC A.Ş.</p>",
        tender,
        settings,
        "https://external.com/award",
    )
    assert result.sources[0].source_type == SourceType.NEWS


def test_jsonld_graph_and_invalid_identifier():
    body = (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@graph": [
                    {
                        "@type": "Organization",
                        "legalName": "ABC A.Ş.",
                        "url": "https://abc.com/",
                        "telephone": "0212 000 00 00",
                        "taxID": "12345678901",
                        "identifier": {"propertyID": "MERSIS", "value": "0012345678901234"},
                    }
                ]
            }
        )
        + "</script>"
    )
    source = make_source("https://abc.com/", "https://abc.com/", body, SourceType.COMPANY_WEBSITE)
    candidate = parse_companies(body, source)[0]
    assert candidate.company.mersis_no == "0012345678901234"
    assert candidate.company.tax_no is None
    assert candidate.company.phone == "+902120000000"
    assert all(item.source_id == source.id for item in candidate.evidence)


def test_multiple_contact_values_are_preserved_as_evidence():
    body = (
        "<p>Ticaret Unvanı: ABC A.Ş.</p><p>Telefon: 0212 000 00 00</p>"
        "<p>Telefon: 0212 000 00 01</p>"
    )
    source = make_source("https://abc.com", "https://abc.com", body, SourceType.COMPANY_WEBSITE)
    candidate = parse_companies(body, source)[0]
    assert len([item for item in candidate.evidence if item.field == "phone"]) == 2


def test_directory_is_not_company_website(tender, settings):
    body = '<script type="application/ld+json">{"@type":"Organization","name":"ABC A.Ş.","url":"https://abc.com/"}</script>'
    record = normalize_tender(
        tender.model_copy(update={"company_urls": [HttpUrl("https://directory.com/abc")]})
    )
    result = CompanyWebsiteCollector(Pages(body), settings).collect(record, CompanyProfile())
    assert result.sources[0].source_type == SourceType.NEWS


def test_bad_source_does_not_stop_remaining_urls(tender, settings):
    class MixedPages(Pages):
        def fetch(self, url):
            if "broken" in url:
                raise RuntimeError("broken parser")
            return super().fetch(url)

    record = tender.model_copy(
        update={
            "award_urls": [
                HttpUrl("https://awards.demo.test/broken"),
                HttpUrl("https://awards.demo.test/good"),
            ]
        }
    )
    collector = PublicAwardCollector(
        MixedPages("<p>İKN: 2026/123456</p><p>Yüklenici: ABC A.Ş.</p>"), settings
    )
    result = collector.collect(normalize_tender(record))
    assert len(result.winner_claims) == 1
    assert result.issues[0].code == "provider_error"


def test_offline_demo_is_explicitly_marked():
    document = DemoFetcher(ROOT / "data/demo").fetch("https://abc.demo.test/")
    assert document.is_demo
