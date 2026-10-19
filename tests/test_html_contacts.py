import pytest

from tender_enricher.collectors.company_website.website import parse_companies
from tender_enricher.collectors.web import check_challenge
from tender_enricher.errors import CollectionError
from tender_enricher.evidence import make_source
from tender_enricher.models import SourceType


def parse(body):
    source = make_source(
        "https://abc.com/contact", "https://abc.com/contact", body, SourceType.NEWS
    )
    return parse_companies(body, source)


def test_microdata_organization_preserves_legal_identity_and_excludes_person():
    body = """
    <div itemscope itemtype="https://schema.org/Organization">
      <span itemprop="name">ABC</span><span itemprop="legalName">ABC İnşaat A.Ş.</span>
      <a itemprop="url" href="https://abc.com/">Site</a>
      <a itemprop="telephone" href="tel:02120000000">Telefon</a>
      <a itemprop="email" href="mailto:info@abc.com">E-posta</a>
      <div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">
        <span itemprop="streetAddress">Örnek Cad. No: 1</span>
        <span itemprop="addressRegion">İstanbul</span>
        <span itemprop="addressLocality">Şişli</span>
      </div>
      <div itemscope itemtype="https://schema.org/Person">
        <span itemprop="name">Yönetici</span><span itemprop="telephone">05320000000</span>
      </div>
    </div>"""
    result = parse(body)[0]
    assert result.company.company_name == "ABC İnşaat A.Ş."
    assert result.company.phone == "+902120000000"
    assert result.company.email == "info@abc.com"
    assert result.company.city == "İstanbul"
    assert result.company.district == "Şişli"
    assert not any("0532" in item.value for item in result.evidence)
    assert all(item.locator and item.excerpt for item in result.evidence)


def test_hcard_contact_markup_is_supported():
    result = parse("""<div class="vcard">
      <span class="org">ABC İnşaat A.Ş.</span>
      <a class="url" href="https://abc.com/">Site</a>
      <span class="tel">0212 000 00 00</span>
      <a class="email" href="mailto:info@abc.com?subject=Contact">E-posta</a>
      <div class="adr"><span class="street-address">Örnek Cad. No:1</span></div>
    </div>""")[0]
    assert result.company.phone == "+902120000000"
    assert result.company.email == "info@abc.com"
    assert result.company.address == "Örnek Cad. No:1"
    assert result.company.city is None


def test_person_hcard_is_not_treated_as_a_company():
    assert not parse("""<div class="vcard"><span class="fn">Bir Kişi</span>
      <span class="tel">0532 000 00 00</span></div>""")


def test_public_contact_page_uses_visible_identity_and_ignores_form_data():
    result = parse("""<title>İletişim | ABC İnşaat</title>
      <meta property="og:site_name" content="ABC İnşaat">
      <link rel="canonical" href="https://abc.com/contact">
      <main><h1>İletişim</h1>
        <a href="tel:02120000000">Telefon</a>
        <a href="mailto:%20info@abc.com?subject=Contact">Yazın</a>
        <h5>Adresimiz</h5><p>Örnek Cad. No: 1 Şişli/İstanbul</p>
        <form><p>Ticaret Unvanı: Müşteri Ltd. Şti.</p>
          <a href="tel:05320000000">Form verisi</a></form>
      </main>
      <footer><p>ABC İnşaat Anonim Şirketi kaliteli hizmet sunar.</p></footer>""")[0]
    assert result.company.company_name == "ABC İnşaat Anonim Şirketi"
    assert result.company.phone == "+902120000000"
    assert result.company.email == "info@abc.com"
    assert result.company.address == "Örnek Cad. No: 1 Şişli/İstanbul"
    assert result.company.city is None
    assert str(result.company.website) == "https://abc.com/contact"
    assert not any("0532" in item.value for item in result.evidence)


def test_page_without_company_identity_does_not_create_candidate():
    assert not parse('<title>İletişim</title><a href="tel:02120000000">Ara</a>')


def test_contact_page_multiple_legal_names_are_not_assigned_shared_contacts():
    assert not parse("""<meta property="og:site_name" content="ABC">
      <p>ABC İnşaat Anonim Şirketi</p><p>ABC Mekanik Limited Şirketi</p>
      <a href="tel:02120000000">Merkez</a>""")


def test_external_canonical_is_not_used_as_company_website():
    result = parse("""<meta property="og:site_name" content="ABC İnşaat">
      <link rel="canonical" href="https://other.com/">
      <a href="tel:02120000000">Ara</a>""")[0]
    assert result.company.website is None


def test_different_public_phones_remain_separate_evidence():
    result = parse("""<meta property="og:site_name" content="ABC İnşaat">
      <a href="tel:02120000000">Merkez</a><a href="tel:02120000001">Şube</a>""")[0]
    assert {item.value for item in result.evidence if item.field == "phone"} == {
        "+902120000000",
        "+902120000001",
    }


def test_bad_tel_attribute_does_not_hide_valid_public_phone():
    result = parse("""<meta property="og:site_name" content="ABC İnşaat">
      <a href="tel:icon">Icon</a><a href="tel:02120000000">Ara</a>
      <span hidden><a href="tel:05320000000">Hidden</a></span>""")[0]
    assert result.company.phone == "+902120000000"
    assert {item.value for item in result.evidence if item.field == "phone"} == {"+902120000000"}


@pytest.mark.parametrize("wrong_identity", [False, True])
def test_plain_contact_page_enriches_only_matching_official_winner(
    tender, settings, repository, wrong_identity
):
    from pydantic import HttpUrl

    from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
    from tender_enricher.collectors.ekap.award import PublicAwardCollector
    from tender_enricher.collectors.web import Document
    from tender_enricher.pipeline import Pipeline

    name = "XYZ Mekanik" if wrong_identity else "ABC İnşaat"
    company_html = f'''<meta property="og:site_name" content="{name}">
      <link rel="canonical" href="https://abc.com/contact">
      <p>{name} Anonim Şirketi</p>
      <a href="tel:02120000000">Ara</a><a href="mailto:info@abc.com">Yazın</a>
      <h5>Adresimiz</h5><p>Örnek Cad. No:1</p>'''
    award_html = """<p>İKN: 2026/123456</p><p>Yüklenici: ABC İnşaat A.Ş.</p>
      <section id="winner-details"><p>Yüklenici Adresi: Örnek Cad. No:1</p>
      <p>Yüklenici Web Sitesi: https://abc.com/</p></section>"""

    class Pages:
        def begin_tender(self):
            pass

        def fetch(self, url):
            return Document(url, url, award_html if "awards.demo.test" in url else company_html)

    record = tender.model_copy(
        update={
            "award_urls": [HttpUrl("https://awards.demo.test/result")],
            "company_urls": [HttpUrl("https://abc.com/contact")],
        }
    )
    pages = Pages()
    result = Pipeline(
        [PublicAwardCollector(pages, settings)],
        [CompanyWebsiteCollector(pages, settings)],
        repository,
    ).process(record)
    assert result.winner.company_name == "ABC İnşaat A.Ş."
    if wrong_identity:
        assert result.winner.phone is None
        assert any(issue.code == "candidate_rejected" for issue in result.issues)
    else:
        assert result.winner.phone == "+902120000000"
        assert result.winner.email == "info@abc.com"
        assert result.winner.city is None
        assert result.field_verification["phone"].status == "single_source"


def test_contact_form_captcha_does_not_block_public_contact_details():
    check_challenge("""<title>ABC İletişim</title><main><h1>ABC Firma İletişim Bilgileri</h1>
      <p>Şirketimizin merkez ofisi ve iletişim bilgileri aşağıda yayımlanmıştır.</p>
      <a href="mailto:info@abc.com">info@abc.com</a>
      <form><div class="g-recaptcha"></div><button>Gönder</button></form></main>""")


@pytest.mark.parametrize(
    "body",
    [
        '<title>Verify you are human</title><form><div class="g-recaptcha"></div></form>',
        '<div class="hcaptcha">Complete challenge</div>',
        "<script>window._cf_chl_opt={}</script><p>cf-chl-gate</p>",
        '<h1>Access denied</h1><a href="mailto:info@abc.com">Support</a>',
    ],
)
def test_actual_access_gates_remain_blocked(body):
    with pytest.raises(CollectionError) as failure:
        check_challenge(body)
    assert failure.value.code == "access_protected"
