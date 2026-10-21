"""Regression cases for EFA-only discovery and separation from generic construction."""

import copy

import bulucu
import pytest
from efa_scope import assess, match_work
from opportunities import enrich

from system_bridge import eligibility


@pytest.mark.parametrize(
    "title,category",
    [
        ("VRF klima montaj ve devreye alma işi", "klima"),
        ("Hastane iklimlendirme sistemleri filtre alımı", "klima"),
        ("Duvar tipi split klimaların bakım onarımı", "klima"),
        ("Sığınak havalandırma tesisatı yapılması", "havalandirma"),
        ("Seramik radyant ısıtma sistemi kurulumu", "isitma"),
        ("Kazan dairesi doğalgaz dönüşümü", "isitma"),
        ("Yoğuşmalı kazan alımı", "isitma"),
        ("Chiller soğutma grubu boru yenilenmesi", "sogutma"),
        ("Mekanik tesisat onarımı", "mekanik"),
        ("Kazan Dairesi Kömürlü Kazan ve Ekipmanlarının Yenilenmesi", "isitma"),
    ],
)
def test_explicit_efa_work_is_recognized(title, category):
    assert category in match_work(title)
    assert assess({"title": title})["matched"] is True


@pytest.mark.parametrize(
    "title",
    [
        "Hastane binası inşaatı",
        "Okul dış cephe boyası ve çatı onarımı",
        "Yol ve çevre düzenlemesi",
        "Hastane yemek ve güvenlik hizmeti alımı",
        "Kök havalandırma makinesi ve çim bakım traktörü alımı",
        "Çim havalandırma makineleri alımı",
        "Ankara Kazan Belediyesi okul onarım işi",
        "Süt taşıma ve süt soğutma tankı alımı",
        "Yangın söndürme ve soğutma çalışmaları için hortum alımı",
        "Klimalı otobüs alımı",
        "Isıtma maksatlı ithal kalorifer kömürü alımı",
        "Fındık Kalorifer Kömürü",
        "KATI YAKIT (KÖMÜR) SATIN ALINACAKTIR",
        "Karayolları Bakım Müdürlüğü ısıtma amaçlı linyit kömürü alımı",
        "Kazan dairesi kısımlarında yardımcı işçilik hizmeti alımı",
        "Yemek kazanı alımı",
        "Buji, CNG, Klima ve Oto Elektrik Kısmı Yedek Parça Alımı",
        "Toplu Taşıma Otobüslerinin Isıtma Sistemi İçin Yedek Parça Alımı",
        "Elektrikli Araç Yangını Müdahale Seti",
    ],
)
def test_generic_buildings_and_misleading_words_are_not_efa_proof(title):
    # Legacy labels/imported keyword claims must not bypass the current policy.
    result = assess({"title": title, "relevance": "dogrudan", "matched_keywords": ["klima"]})
    assert result["matched"] is False
    assert result["categories"] == []


def test_only_work_description_counts_not_authority_address_or_qualification():
    text = """3.1. Adı : Okul bahçe düzenleme
3.2. Niteliği : Çim ve toprak işleri
3.3. Yapılacağı yer : Klima Sanayi Sitesi
4.4. Benzer işler : Klima ve havalandırma bakım onarımı
"""
    row = {
        "title": "Okul bahçe düzenleme",
        "authority": "Klima Müdürlüğü",
        "announcement_text": text,
    }
    assert assess(row)["matched"] is False
    row["announcement_text"] = text.replace("Çim ve toprak işleri", "2 adet VRF klima montajı")
    result = assess(row)
    assert result["matched"] is True
    assert result["basis"] == "scope"
    assert "2 adet VRF" in result["evidence"]
    assert "Benzer işler" not in result["evidence"]


def test_legacy_scope_is_rechecked_and_mixed_tender_keeps_independent_hvac_work():
    row = {
        "title": "Spor tesisi malzeme alımı",
        "match_basis": "scope",
        "match_evidence": "Kök havalandırma makinesi",
    }
    assert assess(row)["matched"] is False
    row["match_evidence"] += "; idari bina için 3 adet split klima montajı"
    assert assess(row)["categories"] == ["klima"]
    row["match_evidence"] = "1 adet binanın mekanik tesisat onarımı"
    assert assess(row)["categories"] == ["mekanik"]


def test_cancellation_keeps_previous_work_evidence_without_reopening_tender():
    row = {
        "title": "İptal kararı",
        "stage": "iptal",
        "match_basis": "title",
        "match_evidence": "Hastane VRF klima montajı",
    }
    before = copy.deepcopy(row)
    result = enrich(row)
    assert result["efa_scope"]["matched"] is True
    assert result["opportunity"]["status"] == "arsiv"
    assert row == before


def test_no_technical_specification_claim_or_research_budget_for_unrelated_record():
    related = enrich({"title": "Hastane mekanik tesisat onarımı"})
    assert related["efa_scope"]["matched"] is True
    assert related["opportunity"]["hvac_scope_confirmed"] is False
    unrelated = enrich(
        {
            "title": "Çim bakım makineleri alımı",
            "stage": "ilan",
            "tender_number": "2026/123",
            "authority": "İdare",
        }
    )
    assert "EFA" in eligibility(unrelated)
    assert unrelated["efa_scope"]["matched"] is False
    # Broad discovery history stays stored for future scope extraction; no data is deleted.
    assert bulucu.classify("Hastane binası inşaatı")[0] == "potansiyel"


def test_old_result_layout_extracts_work_scope_but_not_similar_work():
    row = {
        "title": "Onarım işi",
        "announcement_text": (
            "2- İhale konusu işin a) Adı : Onarım b) Niteliği : Klima montajı "
            "c) Yapılacağı yer : Van\nBenzer işler: kazan"
        ),
    }
    assert assess(row)["categories"] == ["klima"]


def test_vehicle_title_context_rejects_generic_cooling_scope_but_keeps_building_hvac():
    row = {
        "title": "Elektrikli Araç Yangını Müdahale Seti",
        "match_basis": "scope",
        "match_evidence": "Batarya soğutma ekipmanları alımı",
    }
    assert assess(row)["matched"] is False
    assert assess({"title": "Otobüs işletmesi idari bina klima montajı"})["categories"] == ["klima"]
