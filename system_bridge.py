"""Direct discovery → evidence → enrichment integration; no bot-to-bot export step."""

import hashlib
import json
import logging
import os
import queue
import re
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import bulucu
import ekap_bulletin
from pdf_text import read_pdf
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from tender_enricher.collectors.browser import BrowserClient
from tender_enricher.collectors.company_website.website import CompanyWebsiteCollector
from tender_enricher.collectors.demo import DemoFetcher
from tender_enricher.collectors.ekap.award import PublicAwardCollector
from tender_enricher.collectors.search.brave import BraveSearchProvider
from tender_enricher.collectors.trade_registry.registry import PublicRegistryCollector
from tender_enricher.collectors.web import WebClient
from tender_enricher.config import Settings
from tender_enricher.db.migrate import upgrade_database
from tender_enricher.db.repository import SqlAlchemyResultRepository
from tender_enricher.db.session import make_engine
from tender_enricher.enrichment import provider_failure
from tender_enricher.evidence import make_evidence, make_source
from tender_enricher.models import (
    Collection,
    CompanyField,
    CompanyProfile,
    Issue,
    NormalizedTender,
    SourceType,
    TenderInput,
    WinnerClaim,
)
from tender_enricher.normalization import company_key, tender_id, text_key
from tender_enricher.pipeline import Pipeline
from tender_enricher.ports import WinnerProvider

Record = dict[str, Any]


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, min_length=1, max_length=128)
    award_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    company_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    registry_urls: list[HttpUrl] = Field(default_factory=list, max_length=10)
    force: bool = False

    @model_validator(mode="after")
    def options_require_record(self) -> "ResearchRequest":
        if self.id is None and (
            self.force or self.award_urls or self.company_urls or self.registry_urls
        ):
            raise ValueError("Araştırma seçenekleri için bir kayıt kimliği gerekli.")
        return self


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def eligibility(row: Record, *, demo: bool = False) -> str | None:
    if bool(row.get("is_demo")) != demo:
        return "Demo ve gerçek kayıtlar ayrı çalışma alanlarında tutulur."
    if row.get("stage") in {"iptal", "kapandi"}:
        return "İptal/kapalı kayıt için firma araştırması başlatılmaz."
    if row.get("stage") == "proje":
        return "Yatırım projesinin ihale numarası yok; mevcut proje takibi sürer."
    try:
        tender_id(row.get("tender_number") or "")
    except ValueError:
        return "Firma araştırması için geçerli ihale numarası gerekli."
    if not row.get("authority"):
        return "Firma araştırması için idare bilgisi kaynakta tamamlanmalı."
    return None


def as_tender(row: Record, request: ResearchRequest) -> TenderInput:
    links = row.get("research_links") or {}
    company_urls = [
        contact["source_url"]
        for contact in row.get("contacts", [])
        if contact.get("role") == "yuklenici"
        and contact.get("acquisition_method") == "verified_company_directory"
        and contact.get("source_url")
    ]
    awards = list(links.get("award_urls", []))
    if row.get("stage") == "sonuc" and row.get("source_key") != "ekap":
        if row.get("has_detail_url") and not re.search(r"\.(pdf|docx?)(?:[?#]|$)", row["url"]):
            awards.append(row["url"])
    return TenderInput(
        tender_id=row["tender_number"],
        title=row["title"],
        authority=row["authority"],
        location=row.get("city"),
        award_urls=list(dict.fromkeys([*awards, *map(str, request.award_urls)]))[:20],
        company_urls=list(
            dict.fromkeys(
                [*company_urls, *links.get("company_urls", []), *map(str, request.company_urls)]
            )
        )[:20],
        registry_urls=list(
            dict.fromkeys([*links.get("registry_urls", []), *map(str, request.registry_urls)])
        )[:20],
    )


@lru_cache(maxsize=8)
def _parsed_bulletin(filename: str, modified: int, size: int) -> tuple[str, list[Record]]:
    path = Path(filename)
    text, _, _ = read_pdf(path)
    name = path.name
    day = datetime.strptime(name.split("_")[1], "%d%m%Y").strftime("%d.%m.%Y")
    rows, _ = ekap_bulletin.parse_text(text, {"name": "EKAP"}, bulucu.classify, name, day)
    return hashlib.sha256(path.read_bytes()).hexdigest(), rows


class BulletinWinnerProvider:
    """Reparse locally archived official PDFs; never trust imported winner flags."""

    name = "efa_official_bulletin"

    def __init__(self, row: Record, store: Path) -> None:
        self.row, self.store = row, store

    def collect(self, tender: NormalizedTender) -> Collection:
        result = Collection()
        if self.row.get("source_key") != "ekap" or self.row.get("stage") != "sonuc":
            return result
        refs = list(self.row.get("bulletin_references") or [])
        if self.row.get("bulletin_reference"):
            refs.append(self.row["bulletin_reference"])
        seen: set[str] = set()
        for ref in refs:
            name = ref.get("filename", "")
            if name in seen or not re.fullmatch(r"BULTEN_\d{8}_[A-Z]+_SONUC\.pdf", name):
                continue
            seen.add(name)
            path = self.store / name
            if not path.is_file() or path.resolve().parent != self.store.resolve():
                result.issues.append(
                    Issue(
                        stage="winner_collection",
                        code="bulletin_missing",
                        provider=self.name,
                        message="Resmî sonuç PDF’i yerel arşivde bulunamadı.",
                    )
                )
                continue
            stat = path.stat()
            digest, rows = _parsed_bulletin(str(path), stat.st_mtime_ns, stat.st_size)
            matching = [row for row in rows if tender_id(row["tender_number"]) == tender.tender_id]
            if not matching:
                continue
            url = ekap_bulletin.URL + "#" + name
            source = make_source(url, url, "", SourceType.OFFICIAL_AWARD).model_copy(
                update={
                    "content_sha256": digest,
                    "retrieved_at": datetime.fromtimestamp(stat.st_mtime, UTC),
                }
            )
            result.sources.append(source)
            for row in matching:
                for company in row.get("contractors", []):
                    name_value = company.get("name")
                    if not name_value:
                        continue
                    name_key = company_key(name_value)
                    if (
                        any(
                            marker in text_key(name_value)
                            for marker in ("is ortakligi", "ortak girisim", "konsorsiyum")
                        )
                        or sum(token in {"as", "ltd"} for token in name_key.split()) > 1
                    ):
                        result.issues.append(
                            Issue(
                                stage="winner_collection",
                                code="award_ambiguous",
                                provider=self.name,
                                message="Ortak girişim elle incelenmeli.",
                            )
                        )
                    page = row["bulletin_reference"]["page_start"]
                    locator = f"{path.name}#page={page}; IKN={tender.tender_id}"
                    proof = make_evidence(
                        CompanyField.WINNER,
                        name_value,
                        source,
                        locator,
                        f"İKN: {tender.tender_id}; Yüklenicisi: {name_value}",
                    )
                    evidence = [
                        proof,
                        make_evidence(
                            CompanyField.COMPANY_NAME,
                            name_value,
                            source,
                            locator + "; Yüklenicisi",
                            name_value,
                        ),
                    ]
                    address = company.get("address") or None
                    if address:
                        evidence.append(
                            make_evidence(
                                CompanyField.ADDRESS,
                                address,
                                source,
                                locator + "; Yüklenicinin adresi",
                                address,
                            )
                        )
                    result.winner_claims.append(
                        WinnerClaim(
                            tender_id=tender.tender_id,
                            company=CompanyProfile(company_name=name_value, address=address),
                            evidence=evidence,
                        )
                    )
        return result


class AwardFallbackProvider:
    """Use web award research only when the local archive has no winner decision."""

    name = "award_fallback"

    def __init__(self, local: WinnerProvider, web: WinnerProvider) -> None:
        self.local, self.web = local, web

    def collect(self, tender: NormalizedTender) -> Collection:
        try:
            result = self.local.collect(tender)
        except Exception as error:
            result = Collection(
                issues=[provider_failure(self.local.name, "winner_collection", error)]
            )
        if result.winner_claims or any(issue.code == "award_ambiguous" for issue in result.issues):
            return result
        fallback = self.web.collect(tender)
        return Collection(
            sources=[*result.sources, *fallback.sources],
            winner_claims=[*result.winner_claims, *fallback.winner_claims],
            candidates=[*result.candidates, *fallback.candidates],
            issues=[*result.issues, *fallback.issues],
        )


class EnrichmentService:
    def __init__(
        self, root: Path, settings: Settings, *, demo: bool = False, start_worker: bool = True
    ) -> None:
        self.root, self.settings, self.demo = root, settings, demo
        self._lock = threading.RLock()
        self._exports = threading.Lock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self.engine = make_engine(settings.database_url)
        if self.engine.url.get_backend_name() == "sqlite" and self.engine.url.database:
            if Path(self.engine.url.database).resolve() == bulucu.DB.resolve():
                self.engine.dispose()
                raise ValueError("Discovery and enrichment databases must use separate files")
        upgrade_database(self.engine)
        with bulucu.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS enrichment_jobs (
                id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, options TEXT NOT NULL, local_only INTEGER NOT NULL,
                requested_at TEXT NOT NULL, finished_at TEXT, payload TEXT, error TEXT)""")
            conn.execute("UPDATE enrichment_jobs SET state='queued' WHERE state='running'")
            pending = conn.execute(
                "SELECT id FROM enrichment_jobs WHERE state='queued' ORDER BY requested_at"
            ).fetchall()
        for (ident,) in pending:
            self._queue.put_nowait(ident)
        if start_worker:
            self._thread = threading.Thread(
                target=self._worker, daemon=True, name="firma-arastirma"
            )
            self._thread.start()

    def close(self) -> None:
        if self._thread and self._thread.is_alive():
            self._queue.put(None)
            self._thread.join(timeout=5)
        if not self._thread or not self._thread.is_alive():
            self.engine.dispose()

    def jobs(self) -> dict[str, Record]:
        with bulucu.connect() as conn:
            conn.row_factory = sqlite3.Row
            return {row["id"]: dict(row) for row in conn.execute("SELECT * FROM enrichment_jobs")}

    def job(self, ident: str) -> Record | None:
        with bulucu.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM enrichment_jobs WHERE id=?", (ident,)).fetchone()
            return dict(row) if row else None

    def input_hash(self, row: Record) -> str:
        keys = (
            "id",
            "title",
            "source_key",
            "url",
            "source_url",
            "has_detail_url",
            "tender_number",
            "authority",
            "city",
            "stage",
            "contractors",
            "contacts",
            "bulletin_reference",
            "bulletin_references",
            "announcement_text",
            "research_links",
            "is_demo",
        )
        value = {key: row.get(key) for key in keys}
        files = []
        refs = [*(row.get("bulletin_references") or []), row.get("bulletin_reference") or {}]
        for ref in refs:
            name = ref.get("filename", "")
            if re.fullmatch(r"BULTEN_\d{8}_[A-Z_]+\.pdf", name):
                path = ekap_bulletin.STORE / name
                if path.is_file():
                    stat = path.stat()
                    files.append((name, stat.st_mtime_ns, stat.st_size))
        value["archive_files"] = sorted(files)
        return canonical_hash(value)

    def request(
        self,
        row: Record,
        request: ResearchRequest,
        *,
        local_only: bool = False,
        automatic: bool = False,
    ) -> str:
        reason = eligibility(row, demo=self.demo)
        if reason:
            raise ValueError(reason)
        as_tender(row, request)  # Validate URL lists before persisting a job.
        input_hash = self.input_hash(row)
        options = request.model_dump(mode="json", exclude={"id", "force"})
        fingerprint = canonical_hash([input_hash, options, local_only])
        with self._lock:
            old = self.job(row["id"])
            if old and old["state"] in {"queued", "running"}:
                return old["state"]
            if old and old["input_hash"] == input_hash and old["state"] == "completed":
                if automatic:
                    return "cached"
                if old["fingerprint"] == fingerprint and not request.force:
                    finished = old.get("finished_at")
                    if finished and datetime.now(UTC) - datetime.fromisoformat(
                        finished
                    ) < timedelta(hours=24):
                        return "cached"
            if automatic and old and old["state"] == "failed" and old.get("finished_at"):
                if datetime.now(UTC) - datetime.fromisoformat(old["finished_at"]) < timedelta(
                    hours=1
                ):
                    return "cached"
            if self._queue.qsize() >= 100:
                raise ValueError("Araştırma kuyruğu dolu; mevcut işlerin bitmesini bekleyin.")
            with bulucu.connect() as conn:
                conn.execute(
                    """INSERT INTO enrichment_jobs
                    (id,input_hash,fingerprint,state,options,local_only,requested_at)
                    VALUES (?,?,?,'queued',?,?,?) ON CONFLICT(id) DO UPDATE SET
                    input_hash=excluded.input_hash,fingerprint=excluded.fingerprint,state='queued',
                    options=excluded.options,local_only=excluded.local_only,
                    requested_at=excluded.requested_at,finished_at=NULL,payload=NULL,error=NULL""",
                    (
                        row["id"],
                        input_hash,
                        fingerprint,
                        json.dumps(options),
                        int(local_only),
                        datetime.now(UTC).isoformat(),
                    ),
                )
            self._queue.put_nowait(row["id"])
            return "queued"

    def request_batch(self, rows: list[Record], *, limit: int = 10, automatic: bool = False) -> int:
        if limit <= 0:
            return 0
        queued = 0
        ordered = sorted(
            rows, key=lambda row: row.get("opportunity", {}).get("priority", 0), reverse=True
        )
        for row in ordered:
            if self._queue.qsize() >= 100:
                break
            if row.get("stage") != "sonuc" or eligibility(row, demo=self.demo):
                continue
            if automatic and row.get("acquisition_method") != "official_bulletin":
                continue
            current = self.job(row["id"])
            if current and current["state"] in {"queued", "running"}:
                continue
            try:
                state = self.request(
                    row, ResearchRequest(id=row["id"]), local_only=automatic, automatic=automatic
                )
            except ValueError:
                logging.getLogger(__name__).warning("Record needs valid research inputs; skipped.")
                continue
            if state == "queued":
                queued += 1
            if queued >= limit:
                break
        return queued

    def _worker(self) -> None:
        while True:
            ident = self._queue.get()
            try:
                if ident is None:
                    return
                self.process(ident)
            except Exception:
                logging.getLogger(__name__).error("Research job failed; pending jobs continue.")
            finally:
                self._queue.task_done()

    def drain(self) -> list[str]:
        """Synchronous command/test mode, using the same persistent queue."""
        processed = []
        while not self._queue.empty():
            ident = self._queue.get_nowait()
            try:
                if ident is not None:
                    self.process(ident)
                    processed.append(ident)
            finally:
                self._queue.task_done()
        return processed

    def process(self, ident: str) -> None:
        job = self.job(ident)
        if job is None:
            return
        row = next((item for item in bulucu.records() if item["id"] == ident), None)
        if (
            row is None
            or eligibility(row, demo=self.demo)
            or self.input_hash(row) != job["input_hash"]
        ):
            self._finish(ident, "stale", error="Kayıt değişti; güncel haliyle yeniden araştırın.")
            return
        with bulucu.connect() as conn:
            conn.execute("UPDATE enrichment_jobs SET state='running' WHERE id=?", (ident,))
        fetcher = None
        search = None
        try:
            request = ResearchRequest.model_validate({**json.loads(job["options"]), "id": ident})
            tender = as_tender(row, request)
            winners: list[Any] = [BulletinWinnerProvider(row, ekap_bulletin.STORE)]
            companies: list[Any] = []
            if not job["local_only"]:
                if self.demo:
                    fetcher = DemoFetcher(self.root / "data/demo")
                else:
                    web = WebClient(self.settings)
                    fetcher = BrowserClient(web) if self.settings.browser_enabled else web
                    if (
                        self.settings.brave_api_key
                        and self.settings.brave_api_key.get_secret_value()
                    ):
                        search = BraveSearchProvider(self.settings)
                web_awards = PublicAwardCollector(fetcher, self.settings, search)
                if tender.award_urls:
                    winners.append(web_awards)
                else:
                    winners = [AwardFallbackProvider(winners[0], web_awards)]
                companies = [
                    CompanyWebsiteCollector(fetcher, self.settings, search),
                    PublicRegistryCollector(fetcher, self.settings),
                ]
            repository = SqlAlchemyResultRepository(self.engine, identity_key="efa:" + ident)
            result = Pipeline(winners, companies, repository, is_demo=self.demo).process(tender)
            self._finish(
                ident,
                "failed" if result.status == "failed" else "completed",
                payload=result.model_dump(mode="json"),
            )
        except Exception:
            self._finish(
                ident, "failed", error="Firma araştırması tamamlanamadı; tekrar deneyebilirsiniz."
            )
        finally:
            if fetcher:
                fetcher.close()
            if search:
                search.close()

    def _finish(
        self, ident: str, state: str, *, payload: Record | None = None, error: str | None = None
    ) -> None:
        with bulucu.connect() as conn:
            conn.execute(
                """UPDATE enrichment_jobs SET state=?,finished_at=?,payload=?,error=?
                WHERE id=?""",
                (
                    state,
                    datetime.now(UTC).isoformat(),
                    json.dumps(payload, ensure_ascii=False) if payload else None,
                    error,
                    ident,
                ),
            )
            conn.execute(
                "UPDATE tenders SET updated_at=?,revision=revision+1 WHERE id=?",
                (bulucu.now(), ident),
            )
        self.export_snapshot()

    def attach(self, rows: list[Record], *, compact: bool = False) -> list[Record]:
        jobs = self.jobs()
        output = []
        for row in rows:
            item = dict(row)
            reason = eligibility(row, demo=self.demo)
            job = jobs.get(row["id"])
            state = "not_started" if reason is None else "unavailable"
            info: Record = {
                "state": state,
                "eligible": reason is None,
                "reason": reason,
                "result": None,
            }
            if job:
                stale = reason is not None or self.input_hash(row) != job["input_hash"]
                info.update(
                    state="stale" if stale else job["state"],
                    requested_at=job["requested_at"],
                    finished_at=job["finished_at"],
                    error=job["error"],
                    local_only=bool(job["local_only"]),
                )
                if not stale and job["payload"]:
                    result = json.loads(job["payload"])
                    if compact:
                        result.pop("evidence", None)
                        result.pop("field_verification", None)
                    info["result"] = result
                    winner = result.get("winner")
                    opportunity = item.get("opportunity") or {}
                    if (
                        winner
                        and result["status"] in {"partial", "resolved"}
                        and row.get("stage") == "sonuc"
                        and opportunity.get("status") != "arsiv"
                    ):
                        item["opportunity"] = dict(
                            opportunity,
                            kind="yuklenici",
                            target_name=winner["company_name"],
                            target_role="İşi alan yüklenici / proje satınalma birimi",
                            status="yuklenici",
                            priority=max(
                                opportunity.get("priority", 0),
                                85 if row.get("relevance") == "dogrudan" else 70,
                            ),
                            next_action="Doğrulanan yüklenicinin HVAC satınalma aşamasını öğren.",
                        )
                        supplied = {"target_name"}
                        if winner.get("phone") or winner.get("email"):
                            supplied.add("target_phone_or_email")
                        item["missing_sales_fields"] = [
                            field
                            for field in item.get("missing_sales_fields", [])
                            if field not in supplied
                        ]
            item["enrichment"] = info
            output.append(item)
        return output

    def status(self) -> Record:
        counts: dict[str, int] = {}
        for row in self.jobs().values():
            counts[row["state"]] = counts.get(row["state"], 0) + 1
        return {
            "counts": counts,
            "is_demo": self.demo,
            "search_configured": bool(self.settings.brave_api_key),
            "automatic_mode": "local_official_pdf_only",
        }

    def snapshot(self, *, compact: bool = False, since: str | None = None) -> Record:
        return {
            "schema_version": "2.0",
            "discovery_schema_version": "1.3",
            "enrichment_schema_version": "1.0",
            "is_demo": self.demo,
            "exported_at": bulucu.now(),
            "items": self.attach(bulucu.records(since), compact=compact),
        }

    def export_snapshot(self) -> None:
        with self._exports:
            path = bulucu.DATA.parent / "ihalesystem.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=path.parent, delete=False
                ) as file:
                    name = file.name
                    json.dump(self.snapshot(), file, ensure_ascii=False, indent=2)
                os.replace(name, path)
            finally:
                if name and Path(name).exists():
                    Path(name).unlink()
