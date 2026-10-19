"""EFA ihale keşfi: Python 3.11+, PDF okuyucuları için requirements.txt."""
import argparse
import hashlib
import json
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.request
from contextlib import contextmanager, closing
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit, parse_qs
import source_adapters as adapters
import opportunities

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "ihaleler.sqlite3"
SCAN_LOCK = threading.Lock()
TR = timezone(timedelta(hours=3))


def now():
    return datetime.now(TR).isoformat(timespec="seconds")


def normalize(value):
    value = value.lower().replace("ı", "i")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def classify(title):
    text = normalize(title)
    direct = [w for w in ["klima", "iklimlendirme", "havalandirma", "isitma", "sogutma", "mekanik tesisat", "vrf", "vrv", "chiller", "isi pompasi", "kazan", "boyler", "fan coil", "fancoil", "kondenser", "konderser", "kondanser"] if re.search(r'\b' + re.escape(w) + (r'\b' if w == 'kazan' else r'(?:lar\w*|ler\w*|nin|nın|in|i)?\b'), text)]
    if direct:
        return "dogrudan", direct
    buildings = [w for w in ["hastane", "okul", "derslik", "otel", "bina", "konut", "is yeri", "isyeri", "saglik merkezi", "sosyal tesis", "yurt", "ticaret merkezi", "egitim yapilari", "yerleske", "lise", "konukevi"] if w in text]
    work = any(w in text for w in ["insaat", "yapim", "onarim", "yenileme", "restorasyon", "tadilat"])
    return ("potansiyel", buildings) if buildings and work else (None, [])


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td" and self.row is not None:
            self.cell = {"text": "", "href": None}
        elif tag == "a" and self.cell is not None:
            self.cell["href"] = dict(attrs).get("href")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"] += data

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.cell["text"] = " ".join(self.cell["text"].split())
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_toki(html, source):
    parser = TableParser()
    parser.feed(html)
    items = []
    for row in parser.rows:
        if len(row) < 4 or not row[0]["text"].isdigit():
            continue
        title = row[1]["text"]
        kind, matches = classify(title)
        if not kind:
            continue
        href = row[1]["href"]
        url = urljoin(source["url"], href) if href else source["url"]
        if urlsplit(url).scheme not in ("http", "https"):
            continue
        # Başlık kimliği sayesinde tarihin değişmesi yeni kayıt oluşturmaz.
        identity = normalize(title)
        ident = hashlib.sha256(identity.encode()).hexdigest()[:24]
        items.append({"id": ident, "title": title, "url": url,
                      "source": source["name"], "source_url": source["url"],
                      "stage": source["stage"], "tender_date_raw": row[3]["text"],
                      "relevance": kind, "matched_keywords": matches,
                      "has_detail_url": bool(href), "needs_verification": True})
    return items


def fetch(url):
    from network import fetch_html
    return fetch_html(url)


@contextmanager
def connect():
    DATA.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("CREATE TABLE IF NOT EXISTS tenders (id TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS detail_cache_v2 (url TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload TEXT NOT NULL)")
    try:
        with conn:
            migrate_tender_identity(conn)
            yield conn
    finally:
        conn.close()


def identified_item(item):
    item = dict(item)
    key = item.get('source_key')
    if key == 'ekap' and item.get('stage') == 'duzeltme' and item.get('announcement_text'):
        from ekap_bulletin import correction_date
        corrected = correction_date(item['announcement_text'])
        if corrected:
            item['tender_date_raw'] = corrected
            item['tender_date_iso'], item['date_precision'] = adapters.parse_date(corrected)
    number = item.get('tender_number') or adapters.extract_tender_number(
        item.get('announcement_text', ''), item.get('title', ''))
    if key and item.get('stage') != 'proje' and re.fullmatch(r'20\d{2}/\d+', number or ''):
        item['tender_number'] = number
        return item, key, number
    return item, None, None


def migrate_tender_identity(conn):
    """Eski URL kayıtlarını kurum + numara ile eşleştir; önce yerel yedek al."""
    columns = {row[1] for row in conn.execute('PRAGMA table_info(tenders)')}
    if 'source_key' in columns:
        return
    rows = conn.execute('SELECT payload FROM tenders ORDER BY first_seen,id').fetchall()
    backup = DB.with_name(DB.stem + '-before-lifecycle.sqlite3')
    if rows and not backup.exists():
        with closing(sqlite3.connect(backup)) as target:
            conn.backup(target)
    if not conn.in_transaction:
        conn.execute('BEGIN')
    conn.execute('ALTER TABLE tenders ADD COLUMN source_key TEXT')
    conn.execute('ALTER TABLE tenders ADD COLUMN tender_number TEXT')
    prepared = []
    for (payload,) in rows:
        item, key, number = identified_item(json.loads(payload))
        prepared.append(item)
        conn.execute('UPDATE tenders SET source_key=?,tender_number=? WHERE id=?', (key,number,item['id']))
    # Aynı numaranın eski ilan/iptal satırları da ilk açılışta birleşir.
    for item in prepared:
        save_items(conn, [item], seen=False)
    conn.execute('CREATE UNIQUE INDEX tender_identity ON tenders(source_key,tender_number) WHERE source_key IS NOT NULL AND tender_number IS NOT NULL')


def save_items(conn, items, seen=True):
    added = changed = 0
    stamp = now()
    for item in items:
        item, key, number = identified_item(item)
        if key:
            from ekap_bulletin import merge_record
            item = merge_record(item, item)
        previous = conn.execute('SELECT id,payload,first_seen,last_seen,revision FROM tenders WHERE id=? OR (source_key=? AND tender_number=?) ORDER BY first_seen,id', (item['id'],key,number)).fetchall()
        old = previous[0] if previous else None
        if old and (key or item.get('source_key') == 'ekap'):
            from ekap_bulletin import merge_record
            merged = identified_item(json.loads(old[1]))[0]
            for duplicate in previous[1:]:
                merged = merge_record(merged, identified_item(json.loads(duplicate[1]))[0])
            item = merge_record(merged, item)
            item['id'] = old[0]
        from company_contacts import enrich as enrich_contacts
        item = enrich_contacts(item)
        encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if old is None:
            conn.execute('INSERT INTO tenders(id,payload,first_seen,last_seen,updated_at,revision,source_key,tender_number) VALUES (?,?,?,?,?,1,?,?)', (item['id'],encoded,stamp,stamp,stamp,key,number))
            added += not item.get('lifecycle_only',False)
        elif old[1] != encoded or len(previous) > 1:
            for duplicate in previous[1:]:
                conn.execute('DELETE FROM tenders WHERE id=?', (duplicate[0],))
            last_seen = stamp if seen else max(row[3] for row in previous)
            revision = max(row[4] for row in previous) + 1
            conn.execute('UPDATE tenders SET payload=?,last_seen=?,updated_at=?,revision=?,source_key=?,tender_number=? WHERE id=?', (encoded,last_seen,stamp,revision,key,number,item['id']))
            changed += not item.get('lifecycle_only',False)
        elif seen:
            conn.execute("UPDATE tenders SET last_seen=? WHERE id=?", (stamp, item["id"]))
    return added, changed


def reconcile_projects(conn, source, items):
    """Tam ve başarılı Emlak Konut listesinde artık bulunmayanları doğrulamaya ayır."""
    visible = {item['id'] for item in items}
    changed = 0
    for ident, payload in conn.execute('SELECT id,payload FROM tenders').fetchall():
        item = json.loads(payload)
        if item.get('source_key') != source['key'] or ident in visible or item.get('source_presence') == 'missing':
            continue
        item.update(source_presence='missing', last_known_source_status=item.get('source_status'),
                    source_status='Kaynak listesinde bulunamadı', missing_since_at=now())
        conn.execute('UPDATE tenders SET payload=?,updated_at=?,revision=revision+1 WHERE id=?',
                     (json.dumps(item,ensure_ascii=False,sort_keys=True),now(),ident))
        changed += 1
    return changed


def records(since=None):
    with connect() as conn:
        rows = conn.execute("SELECT payload,first_seen,last_seen,updated_at,revision FROM tenders ORDER BY updated_at DESC,id").fetchall()
    items = []
    cutoff = datetime.fromisoformat(since) if since else None
    if cutoff and cutoff.tzinfo is None:
        raise ValueError("since saat dilimi içermeli")
    for payload, first, last, updated, revision in rows:
        if cutoff and datetime.fromisoformat(updated) <= cutoff:
            continue
        item = dict(json.loads(payload), first_seen_at=first, last_seen_at=last, updated_at=updated, revision=revision)
        if item.get('lifecycle_only'):
            continue
        # Eski sürümden kalan kayıtlarda da tarih filtresi çalışır.
        item['tender_date_iso'], item['date_precision'] = adapters.parse_date(item.get('tender_date_raw', ''))
        item['freshness'] = adapters.freshness(item)
        items.append(opportunities.enrich(adapters.transfer_record(item)))
    return items


def export():
    payload = {"schema_version": "1.3", "exported_at": now(), "items": records()}
    temp = DATA / "ihaleler.json.tmp"
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(DATA / "ihaleler.json")


def cached_detail_info(url):
    with connect() as conn:
        cached = conn.execute('SELECT fetched_at,payload FROM detail_cache_v2 WHERE url=?', (url,)).fetchone()
    if cached and 'announcement_text' in json.loads(cached[1]) and datetime.now(TR) - datetime.fromisoformat(cached[0]) < timedelta(hours=6):
        return json.loads(cached[1])
    info = adapters.detail_info(fetch(url))
    with connect() as conn:
        conn.execute('INSERT OR REPLACE INTO detail_cache_v2 VALUES (?,?,?)', (url, now(), json.dumps(info, ensure_ascii=False)))
    return info


def collect_source(source, on_batch=None):
    if source.get('adapter') == 'ekap':
        from ekap_adapter import collect
        return collect(source, classify)
    if source.get('adapter') == 'ekap_bulletin':
        from ekap_bulletin import collect
        return collect(source, classify, on_batch=on_batch)
    if source.get('adapter') in ('csb_projects','emlak_projects'):
        from project_sources import collect
        return collect(source, classify, fetch)
    items, count, pages = [], 0, 0
    page_url = source['url']
    warnings = []
    visited = set()
    for _ in range(min(5, max(1, source.get('max_pages', 1)))):
        if not page_url or page_url in visited:
            break
        visited.add(page_url)
        try:
            html = fetch(page_url)
            if source['adapter'] == 'toki':
                page_items = parse_toki(html, source)
                if not page_items:
                    raise ValueError('Beklenen uygun TOKİ satırları bulunamadı')
                row_count = len(page_items)
                for item in page_items:
                    item['source_key'] = source.get('key', '')
            else:
                page_items, row_count = adapters.parse(html, source, classify)
            items.extend(page_items)
            count += row_count
            pages += 1
            page_url = adapters.next_page(html, page_url)
        except Exception as exc:
            if not pages:
                raise
            warnings.append(f'Sayfa {pages + 1} okunamadı: {exc}')
            break
    items = list({item['id']: item for item in items}.values())
    for index, item in enumerate(items):
        if source.get('detail_dates') and item['has_detail_url'] and index < 20:
            try:
                info = cached_detail_info(item['url'])
                for key, value in info.items():
                    if value:
                        item[key] = value
            except Exception as exc:
                warnings.append(f'Detay tarihi okunamadı: {item["url"]}: {exc}')
        item['tender_date_iso'], item['date_precision'] = adapters.parse_date(item.get('tender_date_raw', ''))
    return items, count, pages, warnings


def scan(only_sources=None):
    if not SCAN_LOCK.acquire(blocking=False):
        return {"busy": True}
    try:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        with connect() as conn:
            previous = conn.execute('SELECT payload FROM scans ORDER BY id DESC LIMIT 1').fetchone()
        previous=json.loads(previous[0]) if previous else None
        result = {"started_at": now(), "sources": [], "new": 0, "changed": 0}
        result['scope']='ekap_archive' if only_sources else 'all_sources'
        for source in config["sources"]:
            if only_sources and source.get('key') not in only_sources:
                continue
            status = {"name": source["name"], "url": source["url"]}
            if not source.get('enabled', True):
                status.update(status='disabled', reason=source.get('reason', 'Otomatik tarama kapalı'))
                result['sources'].append(status)
                continue
            try:
                print('Taranıyor: ' + source['name'], flush=True)
                batch_totals=[0,0]
                def persist_batch(batch):
                    with connect() as conn:
                        added, changed = save_items(conn,batch)
                    batch_totals[0]+=added
                    batch_totals[1]+=changed
                    export()
                items, count, pages, warnings = collect_source(source,on_batch=persist_batch) if source.get('adapter')=='ekap_bulletin' else collect_source(source)
                with connect() as conn:
                    added, changed = save_items(conn, items)
                    if source.get('adapter') == 'emlak_projects' and not warnings:
                        changed += reconcile_projects(conn, source, items)
                added+=batch_totals[0]
                changed+=batch_totals[1]
                result["new"] += added
                result["changed"] += changed
                status.update(status="partial" if warnings else "ok", found=sum(not item.get('lifecycle_only',False) for item in items), examined=count, pages=pages, new=added, changed=changed, warnings=warnings)
                if source.get('adapter')=='ekap_bulletin':
                    from ekap_bulletin import progress_summary
                    status['archive']=progress_summary(source)
            except Exception as exc:
                status.update(status="error", error=str(exc))
            status['last_checked_at']=now()
            result["sources"].append(status)
        if only_sources and previous:
            combined={s['url']:dict(s,last_checked_at=s.get('last_checked_at',previous.get('finished_at'))) for s in previous['sources']}
            combined.update({s['url']:s for s in result['sources']})
            result['sources']=[combined[s['url']] for s in config['sources'] if s['url'] in combined]
        result["finished_at"] = now()
        with connect() as conn:
            conn.execute("INSERT INTO scans(payload) VALUES (?)", (json.dumps(result, ensure_ascii=False),))
        export()
        return result
    finally:
        SCAN_LOCK.release()


def status():
    with connect() as conn:
        latest = conn.execute("SELECT payload FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    return {"scanning": SCAN_LOCK.locked(), "last_scan": json.loads(latest[0]) if latest else None,
              "configured_sources": config['sources'], "interval_minutes": config.get('interval_minutes', 360),
              'archive_interval_minutes':config.get('archive_interval_minutes',1)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Panelin otomatik yenilemeleri terminalde tarama ilerlemesini boğmasın.
        if len(args)>1 and str(args[1])!='200':
            super().log_message(format,*args)
    def send(self, payload, code=200, content_type="application/json; charset=utf-8"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/":
            self.send((ROOT / "panel.html").read_bytes(), content_type="text/html; charset=utf-8")
        elif path.path == '/panel.js':
            self.send((ROOT / 'panel.js').read_bytes(), content_type='text/javascript; charset=utf-8')
        elif path.path == "/api/status":
            self.send(status())
        elif path.path.startswith('/api/bulletins/'):
            name=path.path.rsplit('/',1)[-1]
            if not re.fullmatch(r'BULTEN_\d{8}_[A-Z_]+\.pdf',name):
                self.send({'error':'Geçersiz bülten adı'},400)
            else:
                file=DATA/'ekap-bulten'/name
                if file.exists():
                    self.send(file.read_bytes(),content_type='application/pdf')
                else:
                    self.send({'error':'Bülten dosyası bulunamadı'},404)
        elif path.path in ("/api/tenders", "/api/export"):
            try:
                since = parse_qs(path.query).get("since", [None])[0]
                data=records(since)
                if path.path=='/api/tenders' and parse_qs(path.query).get('compact')==['1']:
                    data=[{k:v for k,v in row.items() if k not in ('announcement_text','source_excerpt','bulletin_references','related_announcements')} for row in data]
                self.send({"schema_version": "1.3", "exported_at": now(), "items": data})
            except ValueError as exc:
                self.send({"error": str(exc)}, 400)
        else:
            self.send({"error": "Bulunamadı"}, 404)

    def do_POST(self):
        # Başka sitelerin yerel taramayı tetiklemesini önle.
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + self.headers.get("Host", ""):
            self.send({"error": "Origin reddedildi"}, 403)
            return
        if self.path == "/api/scan":
            threading.Thread(target=scan, daemon=True).start()
            self.send({"accepted": True}, 202)
        else:
            self.send({"error": "Bulunamadı"}, 404)


def schedule():
    full_scan_due=0
    while True:
        try:
            config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
            full=time.monotonic()>=full_scan_due
            result=scan() if full else scan(only_sources={'ekap'})
            print(json.dumps(result,ensure_ascii=False),flush=True)
            if full:
                full_scan_due=time.monotonic()+max(1,config.get('interval_minutes',360))*60
        except Exception as exc:
            print(f"Tarama hatası: {exc}", flush=True)
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        from ekap_bulletin import progress_summary
        source=next((s for s in config['sources'] if s.get('adapter')=='ekap_bulletin' and s.get('enabled',True)),None)
        pending=progress_summary(source)['remaining_days'] if source else 0
        delay=max(1,config.get('archive_interval_minutes',1))*60 if pending else max(1,full_scan_due-time.monotonic())
        print(f'Sonraki tarama: {round(delay/60,1)} dakika; EKAP geçmişinde {pending} gün kaldı.',flush=True)
        time.sleep(delay)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan", action="store_true", help="Bir kez tara ve çık")
    parser.add_argument("--ekap-setup", action="store_true", help="EKAP kullanıcı doğrulamasını ayrı bot tarayıcısında tamamla")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-auto", action="store_true", help="Otomatik tarama olmadan paneli aç")
    args = parser.parse_args()
    if args.ekap_setup:
        configured = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
        if any(s.get('key') == 'ekap' and s.get('adapter') == 'ekap_bulletin' for s in configured['sources']):
            print('EKAP artık resmî Kamu İhale Bülteni üzerinden okunuyor; tarayıcı doğrulaması gerekmiyor. python bulucu.py ile başlatın.')
            return 0
        from ekap_adapter import setup
        setup()
        return 0
    with connect():
        pass
    if args.scan:
        result = scan()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if not any(s['status'] in ('ok', 'partial') for s in result['sources']) else 0
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if not args.no_auto:
        threading.Thread(target=schedule, daemon=True).start()
    print(f"EFA İhale Bulucu: http://127.0.0.1:{args.port} (çıkış: Ctrl+C)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
