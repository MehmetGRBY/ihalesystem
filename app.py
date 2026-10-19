"""IhaleSystem: one local panel for discovery and evidence-based company research."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "discovery"))

import bulucu  # noqa: E402
import ekap_bulletin  # noqa: E402
import project_sources  # noqa: E402

from system_bridge import EnrichmentService, ResearchRequest  # noqa: E402
from tender_enricher.config import Settings  # noqa: E402

DISCOVERY_SCAN = bulucu.scan


class ImportedRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(pattern=r"^[0-9a-f]{24}$")
    title: str = Field(min_length=1, max_length=10000)
    url: HttpUrl
    source_url: HttpUrl
    source: str = Field(min_length=1)
    stage: str = Field(pattern=r"^(ilan|duzeltme|degerlendirme|iptal|sonuc|kapandi|proje)$")


def configure_paths(directory: Path) -> None:
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    bulucu.DATA = directory / "discovery"
    bulucu.DATA.mkdir(exist_ok=True)
    bulucu.DB = bulucu.DATA / "ihaleler.sqlite3"
    ekap_bulletin.STORE = bulucu.DATA / "ekap-bulten"
    project_sources.CACHE = bulucu.DATA / "project-cache"


def import_discovery(path: Path, *, demo: bool = False) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(document, dict) and "items" not in document:
        raise ValueError("EFA dışa aktarımı items dizisi içermeli.")
    records = document.get("items", []) if isinstance(document, dict) else document
    if not isinstance(records, list):
        raise ValueError("Keşif JSON’u items dizisi içermeli.")
    prepared = []
    for value in records:
        row = ImportedRecord.model_validate(value).model_dump(mode="json")
        if bool(row.get("is_demo")) != demo:
            raise ValueError("Demo ve gerçek kayıtlar aynı çalışma alanına aktarılamaz.")
        for field in (
            "enrichment",
            "first_seen_at",
            "last_seen_at",
            "updated_at",
            "revision",
            "opportunity",
            "freshness",
            "missing_fields",
            "evidence",
        ):
            row.pop(field, None)
        prepared.append(row)
    with bulucu.connect() as conn:
        bulucu.save_items(conn, prepared)
    # Only the import's own optional archive, using validated bulletin names.
    archive = path.parent / "ekap-bulten"
    if archive.is_dir():
        ekap_bulletin.STORE.mkdir(parents=True, exist_ok=True)
        for file in archive.glob("BULTEN_*.pdf"):
            if re.fullmatch(r"BULTEN_\d{8}_[A-Z_]+\.pdf", file.name) and not file.is_symlink():
                destination = ekap_bulletin.STORE / file.name
                if file.resolve() != destination.resolve():
                    shutil.copy2(file, destination)
    bulucu.export()
    return len(prepared)


def seed_demo() -> list[dict[str, Any]]:
    rows = []
    for record in json.loads((ROOT / "data/demo/tenders.json").read_text(encoding="utf-8")):
        rows.append(
            {
                "id": hashlib.sha256(("demo|" + record["tender_id"]).encode()).hexdigest()[:24],
                "title": record["title"],
                "tender_number": record["tender_id"],
                "authority": record["authority"],
                "city": record.get("location"),
                "source": "SENTETİK DEMO",
                "source_key": "demo",
                "source_url": "https://awards.demo.test/",
                "url": (record.get("award_urls") or ["https://awards.demo.test/"])[0],
                "has_detail_url": bool(record.get("award_urls")),
                "stage": "sonuc",
                "tender_date_raw": "",
                "relevance": "potansiyel",
                "matched_keywords": ["hastane"],
                "needs_verification": True,
                "is_demo": True,
                "research_links": {
                    key: record.get(key, [])
                    for key in ("award_urls", "company_urls", "registry_urls")
                },
            }
        )
    with bulucu.connect() as conn:
        bulucu.save_items(conn, rows)
    return bulucu.records()


def handler_for(service: EnrichmentService) -> type[bulucu.Handler]:
    class Handler(bulucu.Handler):
        def do_GET(self) -> None:
            path = urlsplit(self.path)
            query = parse_qs(path.query)
            if path.path == "/api/status":
                self.send(
                    {**bulucu.status(), "enrichment": service.status(), "is_demo": service.demo}
                )
            elif path.path == "/favicon.ico":
                self.send(b"", 204, content_type="image/x-icon")
            elif path.path in {"/api/tenders", "/api/export"}:
                try:
                    compact = path.path == "/api/tenders" and query.get("compact") == ["1"]
                    document = service.snapshot(
                        compact=compact, since=query.get("since", [None])[0]
                    )
                    if compact:
                        document["items"] = [
                            {
                                k: v
                                for k, v in row.items()
                                if k
                                not in {
                                    "announcement_text",
                                    "source_excerpt",
                                    "related_announcements",
                                    "bulletin_references",
                                }
                            }
                            for row in document["items"]
                        ]
                    self.send(document)
                except ValueError as error:
                    self.send({"error": str(error)}, 400)
            elif path.path == "/api/enrichment":
                ident = query.get("id", [None])[0]
                row = next((r for r in bulucu.records() if r["id"] == ident), None)
                self.send(
                    service.attach([row])[0]["enrichment"]
                    if row
                    else {"error": "Kayıt bulunamadı"},
                    200 if row else 404,
                )
            else:
                super().do_GET()

        def do_POST(self) -> None:
            if self.path != "/api/enrich":
                if service.demo and self.path == "/api/scan":
                    self.send({"error": "Demo çevrimdışı çalışır; canlı tarama kapalı."}, 409)
                    return
                super().do_POST()
                return
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers.get("Host", ""):
                self.send({"error": "Origin reddedildi"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 16384:
                    self.send({"error": "İstek boyutu sınırı aşıldı"}, 413)
                    return
                data = json.loads(self.rfile.read(length) or b"{}")
                request = ResearchRequest.model_validate(data)
                rows = bulucu.records()
                if request.id:
                    row = next((r for r in rows if r["id"] == request.id), None)
                    if row is None:
                        self.send({"error": "Kayıt bulunamadı"}, 404)
                        return
                    state = service.request(row, request)
                    self.send({"state": state, "id": row["id"]}, 200 if state == "cached" else 202)
                else:
                    self.send({"queued": service.request_batch(rows)}, 202)
            except (ValueError, ValidationError):
                self.send(
                    {"error": "İhale bilgilerini ve geçerli kaynak bağlantılarını kontrol edin."},
                    400,
                )

    return Handler


def install_scan_hook(service: EnrichmentService) -> None:
    def scan(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = DISCOVERY_SCAN(*args, **kwargs)
        if not result.get("busy"):
            result["enrichment_queued"] = service.request_batch(bulucu.records(), automatic=True)
            service.export_snapshot()
        return result

    bulucu.scan = scan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IhaleSystem — keşif ve firma araştırması")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-auto", action="store_true", help="Canlı otomatik taramayı kapat")
    parser.add_argument(
        "--scan", action="store_true", help="Bir kez tara, yerel kanıtları işle ve çık"
    )
    parser.add_argument("--enrich", metavar="ID", help="Bir keşif kaydını araştır ve çık")
    parser.add_argument(
        "--enrich-all", action="store_true", help="En fazla 10 sonuç kaydını araştır"
    )
    parser.add_argument(
        "--import", dest="import_path", type=Path, help="EFA JSON çıktısını içe aktar"
    )
    parser.add_argument("--demo", action="store_true", help="Tamamen çevrimdışı sentetik demo")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    if args.demo and args.scan:
        parser.error("Demo canlı tarama yapmaz.")
    runtime = args.data_dir or ROOT / "data/runtime" / ("demo" if args.demo else "live")
    runtime = runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(runtime / ".ihalesystem.lock", timeout=0):
            return run(args, runtime)
    except Timeout:
        print("Bu veri klasörünü kullanan IhaleSystem zaten çalışıyor.")
        return 2


def run(args: argparse.Namespace, runtime: Path) -> int:
    configure_paths(runtime)
    settings = Settings(_env_file=ROOT / ".env")
    default_db = Settings.model_fields["database_url"].default
    if args.demo or settings.database_url == default_db:
        settings = settings.model_copy(
            update={"database_url": "sqlite:///" + str(runtime.resolve() / "enrichment.sqlite3")}
        )
    if args.demo:
        settings = settings.model_copy(
            update={
                "official_award_hosts": ["awards.demo.test"],
                "registry_hosts": ["registry.demo.test"],
                "brave_api_key": None,
                "browser_enabled": False,
            }
        )
    commands_only = args.scan or args.enrich or args.enrich_all or args.import_path
    service = EnrichmentService(ROOT, settings, demo=args.demo, start_worker=not commands_only)
    try:
        scan_failed = False
        if args.import_path:
            print(json.dumps({"imported": import_discovery(args.import_path, demo=args.demo)}))
        if args.demo:
            for row in seed_demo():
                service.request(row, ResearchRequest(id=row["id"]))
        install_scan_hook(service)
        if args.scan:
            result = bulucu.scan()
            print(json.dumps(result, ensure_ascii=False))
            scan_failed = not any(
                source.get("status") in {"ok", "partial"} for source in result.get("sources", [])
            )
        if args.enrich:
            row = next((r for r in bulucu.records() if r["id"] == args.enrich), None)
            if row is None:
                raise ValueError("Kayıt bulunamadı.")
            service.request(row, ResearchRequest(id=row["id"], force=True))
        if args.enrich_all:
            service.request_batch(bulucu.records())
        if commands_only:
            processed = service.drain()
            service.export_snapshot()
            failed = any((service.job(ident) or {}).get("state") == "failed" for ident in processed)
            return 1 if scan_failed or failed else 0
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(service))
        if not args.no_auto and not args.demo:
            threading.Thread(target=bulucu.schedule, daemon=True).start()
        print(f"IhaleSystem: http://127.0.0.1:{server.server_port} (Ctrl+C ile durdur)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, SQLAlchemyError):
        print("İşlem tamamlanamadı; kurulum, dosya yolları ve ayarları kontrol edin.")
        raise SystemExit(2) from None
