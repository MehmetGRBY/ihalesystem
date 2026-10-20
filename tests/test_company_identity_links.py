import pytest
from pydantic import HttpUrl

from tender_enricher.collectors.company_website.website import (
    CompanyWebsiteCollector,
    identity_links,
    parse_companies,
)
from tender_enricher.collectors.ekap.award import PublicAwardCollector
from tender_enricher.collectors.web import Document
from tender_enricher.errors import CollectionError
from tender_enricher.evidence import make_source
from tender_enricher.models import CompanyProfile, SourceType
from tender_enricher.pipeline import Pipeline

FULL = "Merkez Mah. Çiçek Sk. Bina No: 1/1A Şişli / İstanbul Şişli/İstanbul"
SHORT = "Çiçek Sok. No:1/1A, 34300 Şişli/İstanbul"

NAME = "Atlas Tıbbi Cihazlar Sanayi Ticaret Limited Şirketi"
CONTACT = f"""<meta property="og:site_name" content="AtlasAir">
<link rel="canonical" href="https://atlas.example/contact">
<a href="mailto:info@atlas.example">Yazın</a><h5>Adres</h5><p>{SHORT}</p>
<a href="/about">Hakkımızda</a><a href="/kvkk#policy">KVKK</a>"""
LEGAL = f"""<meta property="og:site_name" content="AtlasAir">
<link rel="canonical" href="https://atlas.example/kvkk">
<p>Veri sorumlusu olarak <b>{NAME}</b> bu siteyi işletir.</p>
<a href="tel:02120000000">Merkez</a><h5>Adres</h5><p>{SHORT}</p>"""


def test_explicit_site_owner_identity_is_read_from_legal_statement():
    page = make_source(
        "https://atlas.example/kvkk",
        "https://atlas.example/kvkk",
        LEGAL,
        SourceType.COMPANY_WEBSITE,
    )
    candidate = parse_companies(LEGAL, page)[0]
    assert candidate.company.company_name == NAME
    assert candidate.company.phone == "+902120000000"
    proof = next(item for item in candidate.evidence if item.field == "company_name")
    assert proof.source_id == page.id and NAME in proof.excerpt and proof.locator


def test_unrelated_bold_legal_name_does_not_replace_site_identity():
    body = CONTACT + "<p>Müşterilerimiz: <b>Başka Firma Anonim Şirketi</b></p>"
    page = make_source(
        "https://atlas.example/contact",
        "https://atlas.example/contact",
        body,
        SourceType.COMPANY_WEBSITE,
    )
    assert parse_companies(body, page)[0].company.company_name == "AtlasAir"


def test_identity_links_are_observed_same_host_visible_and_bounded():
    body = (
        CONTACT
        + """<a href="https://other.example/kvkk">KVKK</a>
    <a href="//127.0.0.1/kvkk">KVKK</a><a href="javascript:kvkk">KVKK</a>
    <a href="https://user:secret@atlas.example/kvkk">KVKK</a>
    <a href="/">Bu büyük menünün içinde şirket ürünleri hizmetleri
    iletişim bilgileri ve KVKK bağlantısı yazıyor</a>
    <form><a href="/hidden-kvkk">KVKK</a></form>
    <div style="display:none"><a href="/hidden">KVKK</a></div>"""
    )
    assert identity_links(body, "https://atlas.example/contact") == [
        "https://atlas.example/kvkk",
        "https://atlas.example/about",
    ]


class Pages:
    def __init__(self, failure=None, redirect=False):
        self.visited = []
        self.failure, self.redirect = failure, redirect

    def begin_tender(self):
        pass

    def fetch(self, url):
        self.visited.append(url)
        if "awards.demo.test" in url:
            body = (
                f"<p>İKN:2026/123456</p><p>Yüklenici:{NAME}</p>"
                f'<section id="winner-details"><p>Yüklenici Adresi:{FULL}</p></section>'
            )
            return Document(url, url, body)
        if url.endswith("/contact"):
            return Document(url, url, CONTACT)
        if self.failure:
            raise CollectionError(self.failure, "Identity page unavailable")
        return Document(url, "https://other.example/kvkk" if self.redirect else url, LEGAL)


def test_full_pipeline_uses_linked_legal_identity_and_keeps_single_source_contacts(
    tender, settings, repository
):
    pages = Pages()
    record = tender.model_copy(
        update={
            "award_urls": [HttpUrl("https://awards.demo.test/result")],
            "company_urls": [HttpUrl("https://atlas.example/contact")],
        }
    )
    result = Pipeline(
        [PublicAwardCollector(pages, settings)],
        [CompanyWebsiteCollector(pages, settings)],
        repository,
    ).process(record)
    assert result.winner.company_name == NAME
    assert result.winner.phone == "+902120000000"
    assert result.winner.address == FULL
    assert result.winner.email == "info@atlas.example"
    assert result.field_verification["email"].status == "single_source"
    email = next(proof for proof in result.evidence if proof.field == "email")
    source = next(page for page in result.sources if page.id == email.source_id)
    assert str(source.final_url) == "https://atlas.example/contact"
    assert any(issue.code == "linked_company_identity" for issue in result.issues)
    assert result.field_verification["phone"].status == "single_source"
    assert result.field_verification["address"].status == "verified"
    assert result.status == "partial"
    assert pages.visited.count("https://atlas.example/kvkk") == 1


@pytest.mark.parametrize("failure", ["robots_denied", "access_protected", "page_budget_exceeded"])
def test_identity_page_failure_preserves_existing_sources_and_policy(tender, settings, failure):
    pages = Pages(failure=failure)
    record = tender.model_copy(update={"company_urls": [HttpUrl("https://atlas.example/contact")]})
    result = CompanyWebsiteCollector(pages, settings).collect(
        record, CompanyProfile(company_name=NAME, address=FULL)
    )
    assert len(result.sources) == 1
    assert any(issue.code == failure for issue in result.issues)
    assert len(pages.visited) <= 3


def test_link_redirect_to_other_host_is_not_collected(tender, settings):
    pages = Pages(redirect=True)
    record = tender.model_copy(update={"company_urls": [HttpUrl("https://atlas.example/contact")]})
    result = CompanyWebsiteCollector(pages, settings).collect(
        record, CompanyProfile(company_name=NAME, address=FULL)
    )
    assert len(result.sources) == 1
    assert any(issue.code == "identity_redirect_offsite" for issue in result.issues)


def test_follow_up_identity_pages_share_existing_page_budget(tender, settings):
    pages = Pages()
    configured = settings.model_copy(update={"max_pages_per_tender": 2})
    record = tender.model_copy(update={"company_urls": [HttpUrl("https://atlas.example/contact")]})
    CompanyWebsiteCollector(pages, configured).collect(
        record, CompanyProfile(company_name=NAME, address=FULL)
    )
    assert pages.visited == ["https://atlas.example/contact", "https://atlas.example/kvkk"]


@pytest.mark.parametrize("change", ["address", "brand", "no_link", "different_owner"])
def test_contact_identity_chain_requires_all_conditions(tender, settings, repository, change):
    class ChangedPages(Pages):
        def fetch(self, url):
            document = super().fetch(url)
            if url.endswith("/contact"):
                body = document.body
                if change == "address":
                    body = body.replace("No:1/1A", "No:99")
                elif change == "no_link":
                    body = body.replace('<a href="/kvkk#policy">KVKK</a>', "").replace(
                        '<a href="/about">Hakkımızda</a>', ""
                    )
                return Document(url, url, body)
            if url.endswith(("/kvkk", "/about")):
                body = document.body
                if change == "brand":
                    body = body.replace("AtlasAir", "OtherBrand")
                if change == "different_owner":
                    body = body.replace(NAME, "Başka Tıbbi Cihazlar Limited Şirketi")
                return Document(url, url, body)
            return document

    pages = ChangedPages()
    record = tender.model_copy(
        update={
            "award_urls": [HttpUrl("https://awards.demo.test/result")],
            "company_urls": [HttpUrl("https://atlas.example/contact")],
        }
    )
    result = Pipeline(
        [PublicAwardCollector(pages, settings)],
        [CompanyWebsiteCollector(pages, settings)],
        repository,
    ).process(record)
    assert result.winner.email is None
    assert not any(issue.code == "linked_company_identity" for issue in result.issues)


def test_conflicting_linked_owners_do_not_borrow_contact(tender, settings, repository):
    class ConflictingPages(Pages):
        def fetch(self, url):
            page = super().fetch(url)
            if url.endswith("/about"):
                return Document(url, url, page.body.replace(NAME, "Başka Tıbbi Limited Şirketi"))
            return page

    record = tender.model_copy(
        update={
            "award_urls": [HttpUrl("https://awards.demo.test/result")],
            "company_urls": [HttpUrl("https://atlas.example/contact")],
        }
    )
    pages = ConflictingPages()
    result = Pipeline(
        [PublicAwardCollector(pages, settings)],
        [CompanyWebsiteCollector(pages, settings)],
        repository,
    ).process(record)
    assert result.winner.email is None
