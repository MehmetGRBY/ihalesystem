import hashlib
import json
from pathlib import Path

import bulucu
import ekap_bulletin
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app
from system_bridge import BulletinWinnerProvider, EnrichmentService, ResearchRequest, as_tender
from tender_enricher.db.models import RunRow, TenderRow
from tender_enricher.models import TenderInput
from tender_enricher.normalization import normalize_tender

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def service(tmp_path, monkeypatch, settings):
    monkeypatch.setattr(bulucu, "DATA", tmp_path / "discovery")
    bulucu.DATA.mkdir()
    monkeypatch.setattr(bulucu, "DB", bulucu.DATA / "test.sqlite3")
    monkeypatch.setattr(ekap_bulletin, "STORE", bulucu.DATA / "ekap-bulten")
    instance = EnrichmentService(
        ROOT,
        settings.model_copy(
            update={"database_url": "sqlite:///" + str(tmp_path / "enrichment.sqlite3")}
        ),
        demo=True,
        start_worker=False,
    )
    yield instance
    instance.close()


def seeded():
    return app.seed_demo()


def test_two_motors_resolve_demo_in_single_record_and_export(service):
    rows = seeded()
    assert service.request_batch(rows) == 2
    service.drain()
    snapshot = service.snapshot()
    by_number = {row["tender_number"]: row for row in snapshot["items"]}
    resolved = by_number["2026/123456"]
    result = resolved["enrichment"]["result"]
    assert result["status"] == "resolved"
    assert result["winner"]["company_name"].startswith("ABC")
    assert result["sources"] and result["evidence"]
    assert result["is_demo"] is True
    assert resolved["id"] == next(
        row["id"] for row in rows if row["tender_number"] == "2026/123456"
    )
    assert by_number["2026/654321"]["enrichment"]["result"]["status"] == "unresolved"
    path = bulucu.DATA.parent / "ihalesystem.json"
    assert json.loads(path.read_text())["schema_version"] == "2.0"
    assert all(row["title"] for row in json.loads(path.read_text())["items"])


def test_repeated_research_cached_but_forced_run_preserves_history(service):
    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    request = ResearchRequest(id=row["id"])
    assert service.request(row, request) == "queued"
    assert service.request(row, request) == "queued"
    service.drain()
    assert service.request(row, request) == "cached"
    assert service.request(row, request.model_copy(update={"force": True})) == "queued"
    service.drain()
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(RunRow)) == 2


def test_changed_and_cancelled_record_hides_stale_company_result(service):
    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    changed = dict(row, stage="iptal")
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [changed])
    view = service.attach(bulucu.records())
    cancelled = next(r for r in view if r["id"] == row["id"])
    assert cancelled["enrichment"]["state"] == "stale"
    assert cancelled["enrichment"]["result"] is None
    with pytest.raises(ValueError):
        service.request(cancelled, ResearchRequest(id=row["id"]))


def test_record_changing_while_queued_is_not_researched(service):
    row = seeded()[0]
    service.request(row, ResearchRequest(id=row["id"]))
    changed = dict(row, authority="Different authority")
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [changed])
    service.drain()
    assert service.jobs()[row["id"]]["state"] == "stale"
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(RunRow)) == 0


def test_same_number_in_two_authorities_has_separate_history(service):
    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    other = dict(
        row,
        source_key="other",
        id=hashlib.sha256(b"other").hexdigest()[:24],
        authority="Other demo authority",
    )
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [other])
    for record in [row, other]:
        service.request(record, ResearchRequest(id=record["id"]))
    service.drain()
    with Session(service.engine) as session:
        assert session.scalar(select(func.count()).select_from(TenderRow)) == 2
        assert session.scalar(select(func.count()).select_from(RunRow)) == 2
    assert service.jobs()[row["id"]]["payload"] != service.jobs()[other["id"]]["payload"]


def test_projects_missing_fields_and_mixed_demo_do_not_disappear(service):
    row = seeded()[0]
    project = dict(row, stage="proje")
    missing = dict(row, tender_number="")
    real = dict(row, is_demo=False)
    views = service.attach([project, missing, real])
    assert len(views) == 3
    assert all(view["enrichment"]["state"] == "unavailable" for view in views)
    for value in [project, missing, real]:
        with pytest.raises(ValueError):
            service.request(value, ResearchRequest(id=value["id"]))


def test_full_export_has_evidence_compact_does_not(service):
    row = seeded()[0]
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    compact = service.attach([row], compact=True)[0]["enrichment"]["result"]
    assert "evidence" not in compact
    assert compact["field_verification"]["phone"] == {"status": "verified"}
    full = service.attach([row])[0]["enrichment"]["result"]
    assert full["evidence"] and full["field_verification"]


def test_import_accepts_discovery_export_without_faking_enrichment(service, tmp_path):
    rows = seeded()
    row = dict(rows[0], enrichment={"state": "completed", "result": {"winner": "FAKE"}})
    path = tmp_path / "source.json"
    path.write_text(json.dumps({"schema_version": "1.3", "items": [row]}))
    assert app.import_discovery(path, demo=True) == 1
    with bulucu.connect() as conn:
        assert "enrichment" not in json.loads(
            conn.execute("SELECT payload FROM tenders WHERE id=?", (row["id"],)).fetchone()[0]
        )
    assert service.attach([row])[0]["enrichment"]["result"] is None


def test_demo_does_not_use_live_brave_key(service):
    service.settings = service.settings.model_copy(update={"brave_api_key": "not-used"})
    row = seeded()[0]
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    assert service.jobs()[row["id"]]["state"] == "completed"


def test_number_mapping_preserves_original_id_and_never_uses_idare_phone(service):
    row = seeded()[0]
    row["research_links"] = {}
    row["contacts"] = [
        {"role": "idare", "phone": "+902120000000", "source_url": "https://idare.test"}
    ]
    tender = as_tender(row, ResearchRequest(id=row["id"]))
    assert tender.tender_id == row["tender_number"]
    assert tender.company_urls == []
    assert row["id"] != tender.tender_id


def make_award_pdf(
    path, number="2026/123", company="Ornek Insaat Limited Sirketi", winner_label="Yüklenicisi"
):
    import pymupdf

    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"""1. {number} BINA INSAATI
BINA INSAATI YAPTIRILACAKTIR
ORNEK BELEDIYE BASKANLIGI
İhale kayıt numarası : {number}
1- İhalenin
a) Tarihi : 20.09.2026
b) Türü : Yapım işi
2- İhale konusu yapım işinin
a) Adı : Hastane Binası Mekanik Tesisat Yapım İşi
b) Yapılacağı yer : Istanbul
4- Sözleşmenin
a) Tarihi : 08.10.2026
b) Bedeli : 100 TRY
c) Süresi : 19.10.2026 - 21.04.2028
d) {winner_label} : {company}
e) Yüklenicinin uyruğu : Turkiye
f) Yüklenicinin adresi : Ornek is adresi
Kamuoyuna saygıyla duyurulur.
"""
    # HTML text insertion embeds a Unicode font and exercises the real PDF reader.
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_htmlbox(
            page.rect, '<div style="font-size:10pt;white-space:pre-wrap">' + text + "</div>"
        )
        document.save(path)


def test_imported_contractors_are_not_award_evidence(service):
    row = dict(
        seeded()[0],
        source_key="ekap",
        stage="sonuc",
        contractors=[{"name": "FAKE"}],
        bulletin_reference={"filename": "BULTEN_19102026_YAPIM_SONUC.pdf"},
    )
    tender = normalize_tender(
        TenderInput(tender_id=row["tender_number"], title=row["title"], authority="A")
    )
    collection = BulletinWinnerProvider(row, ekap_bulletin.STORE).collect(tender)
    assert collection.winner_claims == []
    assert collection.issues[0].code == "bulletin_missing"


def test_real_pdf_path_traversal_never_used_as_award(service):
    row = dict(
        seeded()[0],
        source_key="ekap",
        stage="sonuc",
        bulletin_reference={"filename": "../../BULTEN_19102026_YAPIM_SONUC.pdf"},
    )
    tender = normalize_tender(as_tender(row, ResearchRequest()))
    assert not BulletinWinnerProvider(row, ekap_bulletin.STORE).collect(tender).sources


@pytest.mark.parametrize("kind,label", [("YAPIM", "Yüklenicisi"), ("HIZMET", "Yüklenici")])
def test_local_pdf_is_winner_proof_without_network_or_trusting_imported_name(service, kind, label):
    service.demo = False
    path = ekap_bulletin.STORE / f"BULTEN_19102026_{kind}_SONUC.pdf"
    make_award_pdf(path, winner_label=label)
    row = {
        "id": "a" * 24,
        "title": "Hastane Binası Mekanik Tesisat Yapım İşi",
        "authority": "Örnek Belediye",
        "source": "EKAP",
        "source_key": "ekap",
        "source_url": ekap_bulletin.URL,
        "url": "https://ekapv2.kik.gov.tr/ekap/search/2026_123",
        "stage": "sonuc",
        "tender_number": "2026/123",
        "tender_date_raw": "20.09.2026",
        "relevance": "potansiyel",
        "has_detail_url": True,
        "contractors": [{"name": "FAKE IMPORTED WINNER"}],
        "bulletin_reference": {"filename": path.name, "page_start": 1},
        "acquisition_method": "official_bulletin",
        "contacts": [{"role": "idare", "phone": "+902120000000"}],
    }
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [row])
    row = bulucu.records()[0]
    service.request(row, ResearchRequest(id=row["id"]), local_only=True)
    service.drain()
    view = service.attach(bulucu.records())[0]
    result = view["enrichment"]["result"]
    assert result is not None, service.jobs()[row["id"]]
    assert result["status"] == "partial"
    assert result["winner"]["company_name"] == "Ornek Insaat Limited Sirketi"
    assert result["winner"]["phone"] is None
    assert result["winner"]["city"] is None
    assert result["sources"][0]["source_type"] == "official_award"
    assert result["evidence"][0]["locator"].startswith(path.name)
    assert view["contacts"] == row["contacts"]
    assert view["opportunity"]["target_name"] == "Ornek Insaat Limited Sirketi"
    assert service.request_batch(bulucu.records(), automatic=True) == 0


def test_pending_job_resumes_after_restart(service):
    row = seeded()[0]
    service.request(row, ResearchRequest(id=row["id"]))
    with bulucu.connect() as conn:
        conn.execute("UPDATE enrichment_jobs SET state='running' WHERE id=?", (row["id"],))
    restarted = EnrichmentService(ROOT, service.settings, demo=True, start_worker=False)
    try:
        restarted.drain()
        assert restarted.jobs()[row["id"]]["state"] == "completed"
        assert restarted.jobs()[row["id"]]["payload"]
    finally:
        restarted.close()


def call_handler(service, path, method="GET", payload=None, origin=None, length=None):
    import io
    from email.message import Message

    handler = object.__new__(app.handler_for(service))
    handler.path = path
    handler.headers = Message()
    handler.headers["Host"] = "127.0.0.1:8765"
    raw = json.dumps(payload).encode() if payload is not None else b"{}"
    handler.headers["Content-Length"] = str(length if length is not None else len(raw))
    if origin:
        handler.headers["Origin"] = origin
    handler.rfile = io.BytesIO(raw)
    captured = []
    handler.send = lambda data, code=200, **kwargs: captured.append((data, code))
    getattr(handler, "do_" + method)()
    return captured[0]


def test_http_research_and_combined_export_contract(service):
    row = seeded()[0]
    data, code = call_handler(service, "/api/enrich", "POST", {"id": row["id"]})
    assert code == 202 and data["state"] == "queued"
    service.drain()
    data, code = call_handler(service, "/api/export")
    assert code == 200 and data["schema_version"] == "2.0"
    assert all("enrichment" in item for item in data["items"])
    full = next(item for item in data["items"] if item["id"] == row["id"])
    assert full["enrichment"]["result"]["evidence"]
    data, code = call_handler(service, "/api/tenders?compact=1")
    assert code == 200
    assert all("announcement_text" not in item for item in data["items"])
    data, code = call_handler(service, "/api/status")
    assert code == 200 and data["is_demo"] is True
    assert data["enrichment"]["counts"]["completed"] == 1
    data, code = call_handler(service, "/api/enrichment?id=" + row["id"])
    assert code == 200 and data["result"]


@pytest.mark.parametrize(
    "payload,origin,length,code",
    [
        ({}, "https://other.example", None, 403),
        ({"id": "does-not-exist"}, None, None, 404),
        ({"company_urls": ["javascript:alert(1)"]}, None, None, 400),
        ({"company_urls": ["https://company.example/"]}, None, None, 400),
        ({"force": True}, None, None, 400),
        ({}, None, 20000, 413),
    ],
)
def test_research_request_validation(service, payload, origin, length, code):
    _, actual = call_handler(service, "/api/enrich", "POST", payload, origin, length)
    assert actual == code
    assert service.jobs() == {}


def test_auto_research_does_not_replace_manual_result(service):
    row = seeded()[0]
    row["acquisition_method"] = "official_bulletin"
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [row])
    row = next(item for item in bulucu.records() if item["id"] == row["id"])
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    assert service.request_batch([row], automatic=True) == 0
    assert service.jobs()[row["id"]]["local_only"] == 0


def test_import_wrong_document_is_rejected(service, tmp_path):
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps({"tender_id": "2026/123", "title": "wrong input format"}))
    with pytest.raises(ValueError):
        app.import_discovery(path, demo=True)


def test_batch_does_not_count_already_pending_jobs(service):
    rows = seeded()
    assert service.request_batch(rows) == 2
    assert service.request_batch(rows) == 0
    assert service.request_batch(rows, limit=0) == 0


def test_second_process_cannot_reuse_the_same_runtime(tmp_path, capsys):
    from filelock import FileLock

    with FileLock(tmp_path / ".ihalesystem.lock", timeout=0):
        assert app.main(["--data-dir", str(tmp_path), "--no-auto"]) == 2
    assert "zaten çalışıyor" in capsys.readouterr().out


def test_scan_command_reports_total_source_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "DISCOVERY_SCAN", lambda: {"sources": [{"status": "error"}]})
    monkeypatch.setattr(bulucu, "DATA", tmp_path / "discovery")
    monkeypatch.setattr(bulucu, "DB", tmp_path / "discovery" / "ihaleler.sqlite3")
    monkeypatch.setattr(ekap_bulletin, "STORE", tmp_path / "discovery" / "ekap-bulten")
    monkeypatch.setattr(bulucu, "scan", app.DISCOVERY_SCAN)
    assert app.main(["--scan", "--data-dir", str(tmp_path)]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("contacts", ["bad"]),
        ("contractors", [42]),
        ("contractors", [{"name": {"bad": "name"}}]),
        ("research_links", "bad"),
        ("research_links", {"company_urls": ["javascript:alert(1)"]}),
        ("bulletin_references", ["bad"]),
        ("bulletin_reference", {"filename": 123}),
        ("document_links", ["bad"]),
        ("related_announcements", ["bad"]),
        ("is_demo", "false"),
        ("tender_date_raw", ["invalid-date-type"]),
        ("published_date_raw", {"date": "19.10.2026"}),
        ("announcement_text", ["bad"]),
        ("contractors", [{"name": "Firma", "period_end_raw": ["bad"]}]),
        ("contractors", [{"name": "Firma", "period_start_raw": 123}]),
        ("contractors", [{"name": "Firma", "contract_date_raw": {"date": "bad"}}]),
        ("related_announcements", [{"url": {"invalid": "url"}}]),
        ("related_announcements", [{"tender_date_raw": ["bad"]}]),
        ("related_announcements", [{"document_links": [{"url": "javascript:alert(1)"}]}]),
        ("project_owner", ["bad"]),
        ("matched_keywords", [{"bad": "keyword"}]),
        ("document_url", ["https://example.com/file.pdf"]),
    ],
)
def test_invalid_nested_import_is_rejected_before_any_record_is_written(
    service, tmp_path, field, value
):
    from pydantic import ValidationError

    row = seeded()[0]
    new_id = hashlib.sha256(b"new import").hexdigest()[:24]
    path = tmp_path / "import.json"
    path.write_text(
        json.dumps([dict(row, id=new_id), dict(row, **{field: value})]), encoding="utf-8"
    )
    before = bulucu.records()
    with pytest.raises(ValidationError):
        app.import_discovery(path, demo=True)
    assert bulucu.records() == before


def test_import_normalizes_missing_optional_lists_and_remains_researchable(service, tmp_path):
    row = seeded()[0]
    path = tmp_path / "import.json"
    path.write_text(
        json.dumps(
            [
                dict(
                    row,
                    contacts=None,
                    contractors=None,
                    research_links=None,
                    bulletin_references=None,
                )
            ]
        )
    )
    assert app.import_discovery(path, demo=True) == 1
    imported = next(r for r in bulucu.records() if r["id"] == row["id"])
    service.request(imported, ResearchRequest(id=row["id"]))
    service.drain()
    assert service.job(row["id"])["state"] == "completed"


@pytest.mark.parametrize(
    "change",
    [
        {"url": "https://changed.demo.test/result"},
        {"source_url": "https://changed.demo.test/list"},
        {"has_detail_url": False},
    ],
)
def test_changed_research_source_hides_old_result_and_allows_fresh_research(service, change):
    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    request = ResearchRequest(id=row["id"])
    service.request(row, request)
    service.drain()
    changed = dict(row, **change)
    assert service.attach([changed])[0]["enrichment"]["state"] == "stale"
    assert service.attach([changed])[0]["enrichment"]["result"] is None
    assert service.request(changed, request) == "queued"


def test_ekap_without_local_pdf_uses_configured_award_search(service, monkeypatch):
    from dataclasses import replace

    from pydantic import SecretStr

    import system_bridge
    from tender_enricher.collectors.demo import DemoFetcher

    searches = []

    class Search:
        def search(self, query, limit=5):
            searches.append(query)
            return ["https://awards.demo.test/2026-123456"]

        def close(self):
            pass

    class FixtureFetcher(DemoFetcher):
        def fetch(self, url):
            return replace(super().fetch(url), is_demo=False)

    monkeypatch.setattr(system_bridge, "build_search_provider", lambda _: Search())
    monkeypatch.setattr(system_bridge, "WebClient", lambda _: FixtureFetcher(ROOT / "data/demo"))
    service.demo = False
    service.settings = service.settings.model_copy(update={"brave_api_key": SecretStr("test")})
    row = dict(
        next(r for r in seeded() if r["tender_number"] == "2026/123456"),
        source_key="ekap",
        research_links={},
        is_demo=False,
        match_basis="scope",
        match_evidence="Mekanik tesisat montajı",
    )
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [row])
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    result = service.attach([row])[0]["enrichment"]["result"]
    assert any("2026/123456" in query for query in searches)
    assert result["winner"]["company_name"].startswith("ABC")


@pytest.mark.parametrize("local_kind", ["ambiguous", "winner"])
def test_local_winner_decision_skips_web_award_search(service, local_kind):
    import system_bridge
    from tender_enricher.collectors.demo import DemoFetcher
    from tender_enricher.collectors.ekap.award import PublicAwardCollector
    from tender_enricher.models import Collection, Issue

    # Ambiguous local official evidence must stay in review, not be replaced by web results.
    class Local:
        name = "local"

        def collect(self, tender):
            if local_kind == "winner":
                return PublicAwardCollector(
                    DemoFetcher(ROOT / "data/demo"), service.settings
                ).collect(tender)
            return Collection(
                issues=[Issue(stage="winner_collection", code="award_ambiguous", message="JV")]
            )

    class Web:
        name = "web"

        def collect(self, tender):
            raise AssertionError("Web award search must not override the local decision")

    provider = system_bridge.AwardFallbackProvider(Local(), Web())
    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    result = provider.collect(normalize_tender(as_tender(row, ResearchRequest())))
    if local_kind == "winner":
        assert result.winner_claims[0].company.company_name.startswith("ABC")
    else:
        assert result.issues[0].code == "award_ambiguous"


def test_corrupt_local_pdf_can_fall_back_to_award_page(service):
    from system_bridge import AwardFallbackProvider
    from tender_enricher.collectors.demo import DemoFetcher
    from tender_enricher.collectors.ekap.award import PublicAwardCollector

    row = dict(
        next(r for r in seeded() if r["tender_number"] == "2026/123456"),
        source_key="ekap",
        bulletin_reference={"filename": "BULTEN_19102026_YAPIM_SONUC.pdf"},
    )
    ekap_bulletin.STORE.mkdir(parents=True)
    (ekap_bulletin.STORE / row["bulletin_reference"]["filename"]).write_bytes(b"broken PDF")
    result = AwardFallbackProvider(
        BulletinWinnerProvider(row, ekap_bulletin.STORE),
        PublicAwardCollector(DemoFetcher(ROOT / "data/demo"), service.settings),
    ).collect(normalize_tender(as_tender(row, ResearchRequest())))
    assert result.winner_claims[0].company.company_name.startswith("ABC")
    assert any(issue.code == "provider_error" for issue in result.issues)


def test_incremental_export_includes_research_completed_within_the_same_second(
    service, monkeypatch
):
    from datetime import UTC, datetime

    class Clock(datetime):
        value = datetime(2026, 10, 19, 12, 0, 0, 100000, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.value.astimezone(tz)

    monkeypatch.setattr(bulucu, "datetime", Clock)
    row = seeded()[0]
    cursor = service.snapshot()["exported_at"]
    Clock.value = Clock.value.replace(microsecond=200000)
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    changes = service.snapshot(since=cursor)["items"]
    assert [item["id"] for item in changes] == [row["id"]]
    assert changes[0]["enrichment"]["state"] == "completed"


def test_manually_supplied_urls_survive_persistent_queue_and_resolve_company(service):
    row = dict(
        next(r for r in seeded() if r["tender_number"] == "2026/123456"),
        source_key="ekap",
        research_links={},
    )
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [row])
    request = ResearchRequest(
        id=row["id"],
        award_urls=["https://awards.demo.test/2026-123456"],
        company_urls=["https://abc.demo.test/"],
        registry_urls=["https://registry.demo.test/abc"],
    )
    service.request(row, request)
    restarted = EnrichmentService(ROOT, service.settings, demo=True, start_worker=False)
    try:
        restarted.drain()
        result = restarted.attach([row])[0]["enrichment"]["result"]
        assert result["status"] == "resolved"
        assert result["winner"]["company_name"].startswith("ABC")
    finally:
        restarted.close()


def test_import_rolls_back_when_merged_records_cannot_be_rendered(service, tmp_path, monkeypatch):
    row = seeded()[0]
    before = bulucu.records()
    new_id = hashlib.sha256(b"unrenderable import").hexdigest()[:24]
    path = tmp_path / "import.json"
    path.write_text(json.dumps([dict(row, id=new_id, source_key="other")]))
    render = bulucu.opportunities.enrich

    def fail_for_new_row(item):
        if item["id"] == new_id:
            raise ValueError("Parser failed after merging")
        return render(item)

    monkeypatch.setattr(bulucu.opportunities, "enrich", fail_for_new_row)
    with pytest.raises(ValueError):
        app.import_discovery(path, demo=True)
    assert bulucu.records() == before


@pytest.mark.parametrize("old_link", [None, "https://www.google.com/search?q=old-authority"])
def test_resolved_winner_updates_contact_search_link(service, old_link):
    from urllib.parse import parse_qs, urlsplit

    row = next(r for r in seeded() if r["tender_number"] == "2026/123456")
    service.request(row, ResearchRequest(id=row["id"]))
    service.drain()
    result = service.attach([dict(row, contact_search_url=old_link)])[0]
    target = result["opportunity"]["target_name"]
    assert parse_qs(urlsplit(result["contact_search_url"]).query)["q"] == [
        target + " kurumsal iletişim"
    ]
    archived = dict(row, opportunity={**row["opportunity"], "status": "arsiv"})
    assert service.attach([archived])[0]["contact_search_url"] == row["contact_search_url"]


def test_api_reports_multiple_configured_search_providers_without_secrets(service):
    from pydantic import SecretStr

    service.demo = False
    service.settings = service.settings.model_copy(
        update={
            "brave_api_key": SecretStr("private-brave"),
            "serper_api_key": SecretStr("private-serper"),
        }
    )
    status = service.status()
    assert status["search_configured"] is True
    assert [provider["id"] for provider in status["search_providers"]] == ["brave", "serper"]
    assert len(status["search_available_providers"]) == 4
    assert "private" not in json.dumps(status)
    service.demo = True
    assert service.status()["search_providers"] == []


def test_adding_search_provider_bypasses_old_manual_research_cache(service):
    from pydantic import SecretStr

    service.demo = False
    path = ekap_bulletin.STORE / "BULTEN_19102026_YAPIM_SONUC.pdf"
    make_award_pdf(path)
    row = dict(
        seeded()[0],
        is_demo=False,
        match_basis="scope",
        match_evidence="Mekanik tesisat montajı",
        source_key="ekap",
        tender_number="2026/123",
        research_links={},
        bulletin_reference={"filename": path.name},
    )
    with bulucu.connect() as conn:
        bulucu.save_items(conn, [row])
    row = next(r for r in bulucu.records() if r["id"] == row["id"])
    request = ResearchRequest(id=row["id"])
    service.request(row, request)
    service.drain()
    assert service.request(row, request) == "cached"
    service.settings = service.settings.model_copy(
        update={"tavily_api_key": SecretStr("private-tavily")}
    )
    assert service.request(row, request) == "queued"


def test_status_shows_search_engines_inside_searxng(service):
    service.demo = False
    service.settings = service.settings.model_copy(
        update={
            "searxng_url": "http://127.0.0.1:8080/",
            "searxng_engines": ["brave", "duckduckgo", "yahoo"],
        }
    )
    assert service.status()["search_providers"] == [
        {"id": "searxng", "label": "SearXNG (Brave, DuckDuckGo, Yahoo)"}
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"searxng_engines": ["brave", "duckduckgo"]},
        {"searxng_url": "http://127.0.0.1:8888/"},
    ],
)
def test_changed_searxng_configuration_bypasses_manual_cache(service, monkeypatch, change):
    service.demo = False
    service.settings = service.settings.model_copy(
        update={"searxng_url": "http://127.0.0.1:8080/", "searxng_engines": ["brave"]}
    )
    monkeypatch.setattr("system_bridge.build_search_provider", lambda _: None)
    path = ekap_bulletin.STORE / "BULTEN_19102026_YAPIM_SONUC.pdf"
    make_award_pdf(path)
    row = dict(
        seeded()[0],
        is_demo=False,
        match_basis="scope",
        match_evidence="Mekanik tesisat montajı",
        source_key="ekap",
        tender_number="2026/123",
        research_links={},
        bulletin_reference={"filename": path.name},
    )
    with bulucu.connect() as connection:
        bulucu.save_items(connection, [row])
    row = next(r for r in bulucu.records() if r["id"] == row["id"])
    request = ResearchRequest(id=row["id"])
    service.request(row, request)
    service.drain()
    assert service.request(row, request) == "cached"
    service.settings = service.settings.model_copy(update=change)
    assert service.request(row, request) == "queued"


def test_efa_unrelated_records_cannot_consume_research_queue(service):
    service.demo = False
    row = dict(
        seeded()[0],
        is_demo=False,
        title="Çim bakım makineleri alımı",
        match_basis="scope",
        match_evidence="Kök havalandırma makinesi alımı",
    )
    with bulucu.connect() as connection:
        bulucu.save_items(connection, [row])
    row = next(record for record in bulucu.records() if record["id"] == row["id"])
    assert row["efa_scope"]["matched"] is False
    assert service.request_batch([row], automatic=True) == 0
    assert service.attach([row])[0]["enrichment"]["eligible"] is False
    _, code = call_handler(service, "/api/enrich", "POST", {"id": row["id"]})
    assert code == 400
    assert service.jobs() == {}
